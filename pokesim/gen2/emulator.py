"""Managed Gen II runtime with isolated saves, manual input and policy control."""
from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version
import io
import logging
from pathlib import Path
import queue
import threading
import time

from pyboy import PyBoy

from .. import __version__, config
from ..audio import AudioFeed
from ..build_info import build_info
from ..checkpoints import open_state
from ..experimental.gen2 import identify
from ..play_clock import PlayClock
from .data import GameData
from .policy import Action, Policy
from .ram import BADGES, read_snapshot

log = logging.getLogger('pokesim.gen2')
BUTTONS = ('up', 'down', 'left', 'right', 'a', 'b', 'start', 'select')


@dataclass(frozen=True)
class Event:
    type: str
    title: str
    body: str = ''
    priority: int = 3
    notable: bool = True


class Emulator:
    generation = 2

    def __init__(self, store, ntfy=None, *, isolated_ram=True):
        self.store, self.ntfy = store, ntfy
        self.rom = Path(config.ROM_PATH)
        self.profile = identify(self.rom.read_bytes())
        self.rom_sha1 = self.profile.sha1
        self.rom_note = f'Pokémon {self.profile.game.title()} ({self.profile.revision})'
        from ..game_data import directory
        self.data = GameData.load(directory(), self.profile.game)
        self.isolated_ram = isolated_ram
        self.preparation = None
        self.options_applied = False
        self.policy = Policy(self.data, seed=config.SEED, starter=config.STARTER)
        self.policy.load_state_dict(store.get('policy_state', {}))
        self.speed = config.SPEED
        self.paused = False
        self.manual_mode = False
        self.stopping = False
        self.fatal_error = None
        self.frame = self.executed_frames = 0
        self.frame_seq = 0
        self.frame_image = b''
        self.snapshot = self.previous = None
        self.audio = AudioFeed()
        self.play_clock = PlayClock(store.get('play_clock', {}))
        self.lock = threading.Lock()
        self.frame_cond = threading.Condition()
        self.commands = queue.Queue()
        self.manual = queue.Queue(maxsize=16)
        self.started_at = time.time()
        self.last_activity = time.monotonic()
        self.stuck_since = time.time()
        self.progress_frame = 0
        self.progress_key = None
        self._watch_until = self._last_publish = 0.0
        self.history = store.get('gen2-history', {'maps': [], 'owned': [], 'badges': 0, 'league': 0})
        self.last_achievement = next(iter(store.events(limit=1)), None)
        from .tracking import Tracker
        self.tracker = Tracker(store, self.data, fresh=not bool(store.autosaves()))
        from .statistics import Statistics
        self.statistics = Statistics(store)
        from .legendary import Recovery
        self.legendary_recovery = Recovery()
        from .steps import StepTracker
        self.steps = StepTracker(store, self.data)
        self.pb = self._boot()
        self.thread = threading.Thread(target=self._run, name='gen2-emulator', daemon=True)

    def _boot(self):
        # Save states own both SRAM and RTC. Shared ROM assets never own save files.
        pb = PyBoy(str(self.rom), window='null', cgb=True, sound_emulated=True,
                   ram_file=io.BytesIO(bytes(32768)))
        pb.set_emulation_speed(0)
        self.tracker.attach(pb)
        self.steps.attach(pb)
        return pb

    def start(self):
        errors = []
        for path in reversed(self.store.autosaves()):
            try:
                self._load_state_file(path)
                break
            except (ValueError, OSError) as error:
                errors.append(error)
                log.exception('Cannot restore Gen II checkpoint %s', path.name)
        else:
            if errors:
                self.pb.stop(save=False)
                raise ValueError('No compatible Gen II autosave could be restored') from errors[-1]
        from .. import rewards
        rewards.initialize(self.store, self.snapshot.hall_of_fame_count if self.snapshot else 0)
        if self.store.get('interaction_preparation') or self.store.get('trade_hold'):
            self.paused = True
        self.thread.start()

    def stop(self):
        self.commands.put(('stop', None))
        self.thread.join(timeout=20)
        if self.thread.is_alive():
            raise RuntimeError('Gen II emulator did not stop within 20 seconds')

    def command(self, name, arg=None):
        self.commands.put((name, arg))

    def call(self, function, timeout=30):
        if threading.current_thread() is self.thread:
            return function()
        if not self.thread.is_alive():
            raise RuntimeError('The adventure is not running')
        done, response = threading.Event(), {}
        self.commands.put(('runtime_call', (function, done, response)))
        if not done.wait(timeout):
            raise TimeoutError('The adventure is busy')
        if 'error' in response:
            raise response['error']
        return response['result']

    def press(self, button):
        if button in BUTTONS:
            self.command('press', button)

    def watch(self):
        self._watch_until = time.monotonic() + 2

    def current_frame(self, timeout=1):
        self.watch()
        if self.paused or not self.frame_image:
            self.call(self._publish_frame, timeout=max(1, timeout))
        with self.frame_cond:
            if not self.frame_image:
                self.frame_cond.wait(timeout)
        return self.frame_image

    def audio_packet(self, after):
        state = 'playing' if not self.paused or self.manual_mode else 'paused'
        sequence, pcm, speed = self.audio.read(after, state)
        return state, sequence, pcm, speed

    def _shot_png(self):
        output = io.BytesIO()
        self.pb.screen.image.save(output, format='PNG')
        return output.getvalue()

    def _publish_frame(self):
        with self.frame_cond:
            self.frame_image = self._shot_png()
            self.frame_seq += 1
            self.frame_cond.notify_all()

    def _state_bytes(self):
        output = io.BytesIO()
        self.pb.save_state(output)
        return output.getvalue()

    def _manifest(self):
        return {'app_version': __version__, 'pyboy_version': version('pyboy'), 'generation': 2,
                'rom_sha1': self.rom_sha1, 'frame': self.frame, 'policy': config.POLICY,
                'policy_state': self.policy.state_dict(), 'run_memory': {}, 'play_clock': self.play_clock.state_dict(),
                'gen2_history': self.history, 'legendary_recovery': self.legendary_recovery.state_dict(),
                'trade_id': self.store.get('trade_barrier'),
                'reward_id': self.store.get('custom-reward-barrier-v1')}

    def _autosave(self, trade_prepare=False):
        if self.store.get('trade_hold') and not trade_prepare:
            return
        if self.snapshot is not None and not self.snapshot.valid:
            return
        self.steps.flush(force=True)
        self.statistics.flush(self.snapshot)
        path = self.store.write_checkpoint(self._state_bytes(), self._manifest())
        self.store.set('policy_state', self.policy.state_dict())
        self.store.set('gen2-history', self.history)
        self.store.set('play_clock', self.play_clock.state_dict())
        self.store.prune_autosaves(config.KEEP_AUTOSAVES)
        self.store.prune_events(config.EVENT_RETENTION_DAYS)
        return path

    def _load_state_file(self, path):
        metadata = self.store.checkpoint_metadata(path)
        for key, field in [('trade_barrier', 'trade_id'), ('custom-reward-barrier-v1', 'reward_id')]:
            barrier = self.store.get(key)
            if barrier and (metadata or {}).get(field) != barrier:
                raise ValueError('Checkpoint predates a completed trade or custom reward')
        if metadata and (metadata.get('rom_sha1') != self.rom_sha1 or metadata.get('generation') != 2):
            raise ValueError('This checkpoint belongs to a different cartridge')
        if metadata is None:
            raise ValueError('Gen II checkpoints require cartridge identity metadata')
        with open_state(path) as source:
            self.pb.load_state(source)
        for button in BUTTONS:
            self.pb.button_release(button)
        self.frame = metadata.get('frame', 0)
        self.policy.load_state_dict(metadata.get('policy_state', {}))
        self.policy.on_restore()
        self.play_clock.restore(metadata.get('play_clock'))
        self.history = metadata.get('gen2_history', self.history)
        self.previous = None
        self.statistics.previous = None
        from .legendary import Recovery
        self.legendary_recovery = Recovery(metadata.get('legendary_recovery'))
        self.snapshot = read_snapshot(self.pb.memory, self.data, self.frame)
        self.audio.clear()
        self.options_applied = False
        self._publish_frame()

    def _event(self, event, snapshot):
        shot = self._shot_png()
        state = self._state_bytes()
        eid = self.store.add_event(event, snapshot, shot, state)
        self.store.write_checkpoint(state, self._manifest(), name=f'event-{eid}.state')
        self.last_achievement = self.store.event(eid)
        if self.ntfy and self.ntfy.wants(event):
            self.ntfy.send(event.title, event.body, priority=event.priority, image=shot,
                           event_type=event.type, click=f'{config.PUBLIC_URL}/events/{eid}')

    def _observe(self):
        snapshot = read_snapshot(self.pb.memory, self.data, self.frame)
        self.snapshot = snapshot
        if not snapshot.valid or not snapshot.started:
            return
        if not self.options_applied and not self.manual_mode:
            from .ram import Memory
            mem = Memory(self.pb.memory, self.data)
            value = mem.byte('wOptions')
            if config.FAST_TEXT:
                value = value & ~7 | 1
            value = value & ~128 if config.BATTLE_ANIMATIONS else value | 128
            bank, address = self.data.symbols['wOptions']
            self.pb.memory[bank, address] = value
            self.options_applied = True
        self.play_clock.seed(snapshot.playtime_seconds)
        self.tracker.observe(snapshot)
        from .steps import observe_mew
        self.steps.flush()
        self.statistics.observe(snapshot)
        if not self.store.get('trade_hold') and not self.preparation and not self.manual_mode:
            for species in self.legendary_recovery.observe(snapshot, self.pb.memory):
                self._event(Event('legendary_retry', f'{self.data.species[species]["name"]} can be encountered again',
                    'The encounter ended without a catch. Used supplies and adventure progress are preserved.'), snapshot)
        if snapshot.map not in self.history['maps']:
            self.history['maps'].append(snapshot.map)
            self._event(Event('map', f'Arrived at {snapshot.map_name}', priority=2), snapshot)
        for dex in sorted(snapshot.owned - set(self.history['owned'])):
            self.history['owned'].append(dex)
            self._event(Event('catch', f'{self.data.species[dex]["name"]} joined the Pokédex', priority=4), snapshot)
        for i, badge in enumerate(BADGES):
            if snapshot.badges & (1 << i) and not self.history['badges'] & (1 << i):
                self.history['badges'] |= 1 << i
                self._event(Event('badge', f'Earned the {badge} Badge', priority=5), snapshot)
        if snapshot.hall_of_fame_count > self.history['league']:
            from .. import rewards
            rewards.earn(self.store, snapshot.hall_of_fame_count, enabled=getattr(config, 'LEAGUE_REWARDS', False))
            from .league import record
            record(self.store, self.data, snapshot)
            self.history['league'] = snapshot.hall_of_fame_count
            self._event(Event('champion', f'Champion! League victory #{snapshot.hall_of_fame_count}', priority=5), snapshot)
        observe_mew(self.store, snapshot, self.steps.value['total'])
        before = self.previous
        if before:
            for mon in snapshot.party:
                matches = [old for old in before.party if (old.trainer_id, old.dvs) == (mon.trainer_id, mon.dvs)]
                if len(matches) != 1:
                    continue
                old = matches[0]
                if old.egg and not mon.egg:
                    self._event(Event('hatch', f'{mon.name} hatched from its Egg', priority=4), snapshot)
                elif old.species != mon.species and any(row['species'] == mon.species
                                                       for row in self.data.species[old.species]['evolutions']):
                    self._event(Event('evolve', f'{old.name} evolved into {mon.name}', priority=4), snapshot)
                elif mon.level > old.level and not mon.egg:
                    self._event(Event('level', f'{mon.nick} grew to level {mon.level}',
                                      priority=4 if mon.level in (50, 100) else 2, notable=mon.level % 10 == 0), snapshot)
        key = (len(self.policy.nav.visits), snapshot.event_flags, snapshot.badges,
               snapshot.owned, snapshot.items, snapshot.enemy_hp,
               tuple((mon.species, mon.level, mon.hp, mon.experience, mon.pp) for mon in snapshot.party))
        if key != self.progress_key:
            self.progress_key, self.progress_frame = key, self.frame
        if before and (before.map, before.x, before.y) != (snapshot.map, snapshot.x, snapshot.y):
            self.stuck_since = time.time()
        self.previous = snapshot

    def _tick(self, frames):
        while frames > 0:
            audible = self.audio.active()
            chunk = min(frames, 1 if audible else 4)
            now = time.monotonic()
            observing = (self.frame + chunk) // 30 != self.frame // 30
            publishing = now < self._watch_until and now - self._last_publish >= 1 / config.STREAM_FPS
            self.pb.tick(chunk, render=observing or publishing, sound=audible)
            if audible:
                self.audio.publish(self.pb.sound.raw_buffer[:self.pb.sound.raw_buffer_head])
            self.frame += chunk
            self.executed_frames += chunk
            self.play_clock.advance(chunk)
            frames -= chunk
            if observing:
                self._observe()
            if publishing:
                self._publish_frame()
                self._last_publish = now
            speed = 1 if self.manual_mode else self.speed
            if speed:
                self._target = getattr(self, '_target', now) + chunk / 60 / speed
                delay = self._target - time.monotonic()
                if 0 < delay < 1:
                    time.sleep(delay)
                elif abs(delay) >= 1:
                    self._target = time.monotonic()
            self.last_activity = time.monotonic()

    def _handle_command(self, name, arg):
        if name == 'runtime_call':
            function, done, response = arg
            try:
                response['result'] = function()
            except Exception as error:
                response['error'] = error
            finally:
                done.set()
        elif self.store.get('trade_hold') and name != 'stop':
            return True
        elif name == 'stop':
            return False
        elif name == 'pause':
            self.paused, self.manual_mode = True, False
        elif name in {'take_control', 'press'}:
            self.paused, self.manual_mode = True, True
            self.policy.menu = None
            self.policy.on_restore()
            if name == 'press' and arg in BUTTONS:
                try:
                    self.manual.put_nowait(Action(arg, 8, 8))
                except queue.Full:
                    pass
        elif name == 'resume':
            self.paused = self.manual_mode = False
            self.policy.on_restore()
        elif name == 'speed':
            self.speed = float(arg)
        elif name == 'save':
            self._autosave()
        elif name == 'load_state':
            path = self.store.state_path(arg)
            if path:
                self._load_state_file(path)
        elif name == 'restart':
            self._autosave()
            for path in self.store.states.glob('auto-*.state'):
                path.unlink()
                path.with_suffix('.json').unlink(missing_ok=True)
            for key in ('trade_barrier', 'custom-reward-barrier-v1', 'custom-reward-pending-v1',
                        'league-rewards-v1', 'gen2-mythical-gift-v1', 'gen2-league-partners-v1',
                        'gen2-mew-returns-v1'):
                self.store.set(key, None)
            self.store.clear_trade_preferences()
            self.pb.stop(save=False)
            self.tracker.reset()
            self.steps.flush(force=True)
            self.statistics.previous = None
            from .legendary import Recovery
            self.legendary_recovery = Recovery()
            self.pb = self._boot()
            self.options_applied = False
            self.frame = 0
            self.previous = self.snapshot = None
            self.history = {'maps': [], 'owned': [], 'badges': 0, 'league': 0}
            self.policy = Policy(self.data, seed=config.SEED, starter=config.STARTER)
            self.play_clock = PlayClock()
            self.paused = self.manual_mode = False
            self._autosave()
        return True

    def _run(self):
        next_save = time.monotonic() + config.AUTOSAVE_SECONDS
        try:
            running = True
            while running:
                while not self.commands.empty():
                    name, arg = self.commands.get_nowait()
                    running = self._handle_command(name, arg)
                    if not running:
                        break
                if not running:
                    break
                if self.store.get('trade_hold'):
                    self.last_activity = time.monotonic()
                    time.sleep(0.03)
                    continue
                if self.frame - getattr(self, '_reward_check_frame', -300) >= 300:
                    from .rewards import deliver
                    self._reward_check_frame = self.frame
                    if deliver(self):
                        continue
                if self.preparation and not self.paused:
                    snapshot = read_snapshot(self.pb.memory, self.data, self.frame)
                    action = self.preparation.step(snapshot)
                elif not self.manual.empty():
                    action = self.manual.get_nowait()
                elif self.manual_mode:
                    action = Action(None, 0, 4)
                elif self.paused:
                    self.last_activity = time.monotonic()
                    time.sleep(0.03)
                    continue
                else:
                    snapshot = read_snapshot(self.pb.memory, self.data, self.frame)
                    action = self.policy.step(snapshot, self.pb.memory)
                if action.button:
                    self.pb.button_press(action.button)
                try:
                    self._tick(action.hold)
                finally:
                    if action.button:
                        self.pb.button_release(action.button)
                self._tick(action.gap)
                if time.monotonic() >= next_save:
                    self._autosave()
                    next_save = time.monotonic() + config.AUTOSAVE_SECONDS
        except Exception as error:
            self.fatal_error = str(error)
            log.exception('Gen II adventure failed')
        finally:
            try:
                self.steps.flush(force=True)
                if not self.fatal_error:
                    self._autosave()
            except Exception as error:
                self.fatal_error = f'The final save failed: {error}'
                log.exception('Gen II final save failed')
            self.pb.stop(save=False)
            self.stopping = True

    def health(self):
        age = max(0, time.monotonic() - self.last_activity)
        return {'ok': self.thread.is_alive() and not self.fatal_error and age < 30 and not self.stopping,
                'worker_alive': self.thread.is_alive(), 'activity_age_seconds': age, 'error': self.fatal_error}

    def status(self):
        from .. import rewards
        achievement = self.last_achievement
        quiet_minutes = max(0, self.frame - self.progress_frame) / 3600
        stalled = quiet_minutes >= 10 and not self.paused and not self.manual_mode
        return {'version': __version__, 'generation': 2, 'build': build_info(), 'viewer_only': config.VIEWER_ONLY,
                'health': self.health(), 'paused': self.paused, 'manual_mode': self.manual_mode, 'speed': self.speed,
                'policy': self.policy.describe(), 'strategy': self.policy.details(), 'frame': self.frame,
                'game': self.snapshot.to_dict() if self.snapshot else None, 'rom': self.rom_note,
                'play_clock': self.play_clock.status(), 'performance': {'frames': self.executed_frames, 'sampled_at': time.monotonic()},
                'uptime': int(time.time() - self.started_at), 'stuck_seconds': int(time.time() - self.stuck_since),
                'areas_discovered': len(self.history['maps']), 'reloads': 0, 'glitched': False,
                'help_request': {'reason': 'The policy has stopped making game progress',
                                 'action': self.policy.mode} if stalled else None,
                'progress': {'state': 'stalled' if stalled else 'making_progress',
                             'last_achievement': achievement, 'quiet_game_minutes': round(quiet_minutes, 1)},
                'league_rewards': rewards.status(self.store), 'legendary_recovery': self.legendary_recovery.state_dict()}

    def set_trade_preference(self, key, state):
        from ..trade.preferences import update
        from .web import live_status
        return self.call(lambda: update(self.store, live_status(self.status().get('game'),
                                                              self.policy.details()['collection']), key, state))
