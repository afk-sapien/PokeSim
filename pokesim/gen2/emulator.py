"""Managed Gen II runtime with isolated saves, manual input and policy control."""
from __future__ import annotations

from dataclasses import dataclass, replace
import io
import logging
from pathlib import Path
import queue
import secrets
import threading
import time

from .. import __version__, config
from ..audio import AudioFeed
from ..build_info import build_info
from ..checkpoints import open_state
from ..events import HIGH, LOW
from ..experimental.gen2 import identify
from ..loop_errors import loop_failed
from ..play_clock import PlayClock
from ..stalls import StallWatch
from pokecore.gen2.clock import boot, clock_elapsed, clock_lock_state, follow_game_time, host_elapsed, rebase_to_host
from pokecore.emulator_state import checkpoint_metadata, validate_runtime
from .data import GameData
from . import journal
from .menus import stack_pointer
from .policy import Action, Policy
from pokecore.gen2.ram import BADGES, read_snapshot
from .store_stock import StoreStock

log = logging.getLogger('pokesim.gen2')

# The running cartridge clock's latest reading, in seconds since its zero point (see core.clock_elapsed).
CLOCK_KEY = 'gen2-clock-v1'


# pret engine/events/halloffame.asm: the cartridge stops counting Hall of Fame entries at
# HOF_MASTER_COUNT, so every League win after the 200th leaves wHallOfFameCount where it is.
HOF_MASTER_COUNT = 200


def count_league(history, data, snapshot, *, observe=True):
    """Return the snapshot with the League wins the cartridge no longer counts added back.

    Reaching the Hall of Fame from Lance's Room with the count already at the cap is a win the
    cartridge drops. The run then saw no new victory, so its League loop waited for one forever
    and the stall alert fired every few hours. The visit is kept in the history so a reload
    rewinds it along with the count. Only the observation loop records a win. Other reads only
    add the wins already recorded.
    """
    if snapshot is None or not snapshot.valid or not snapshot.started:
        return snapshot
    if observe and snapshot.map == data.map_ids['LANCES_ROOM']:
        history['league_attempt'] = snapshot.hall_of_fame_count >= HOF_MASTER_COUNT
    elif observe and snapshot.map == data.map_ids['HALL_OF_FAME'] and history.pop('league_attempt', False):
        history['capped_wins'] = history.get('capped_wins', 0) + 1
    extra = history.get('capped_wins', 0)
    return replace(snapshot, hall_of_fame_count=snapshot.hall_of_fame_count + extra) if extra else snapshot


WEEKDAYS = ('Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday')
# pret engine/overworld/time.asm GetTimeOfDay: MORN_HOUR 4, DAY_HOUR 10, NITE_HOUR 18.
MORNING_HOUR, DAY_HOUR, NIGHT_HOUR = 4, 10, 18


def period(hour):
    """The Gen II part of the day: Morning 4:00-9:59, Day 10:00-17:59, Night 18:00-3:59."""
    return 'Morning' if MORNING_HOUR <= hour < DAY_HOUR else 'Day' if DAY_HOUR <= hour < NIGHT_HOUR else 'Night'


def game_clock(memory, data):
    """The in-game clock as the game last worked it out: weekday, hour, minute and part of the day.

    The game copies the cartridge clock plus its own saved offsets into these bytes as it runs,
    so this is a few memory reads with no emulator stepping.
    """
    from pokecore.gen2.ram import Memory
    try:
        mem = Memory(memory, data)
        day, hour, minute = mem.byte('wCurDay'), mem.byte('hHours'), mem.byte('hMinutes')
    except (KeyError, IndexError, TypeError):
        return None
    if hour > 23 or minute > 59:
        return None
    return {'weekday': WEEKDAYS[day % 7], 'hour': hour, 'minute': minute, 'period': period(hour)}


def solid(image):
    """Whether a frame is one flat colour, like the white flash between Gold and Silver screens."""
    extrema = image.getextrema()
    bands = extrema if isinstance(extrema[0], tuple) else (extrema,)
    return all(low == high for low, high in bands)
# A screen that has not changed for half a game minute is a loop, not a pause.
SCREEN_FRAMES = 1800
STALL_RELOADS = 3  # reloads in a row without new progress before the run is reported as stalled
MAX_RELOADS = 12  # and the number after which reloading stops, since it only replays the same trouble
# Written on arriving at the Indigo Plateau Pokémon Center, the last place before an Elite Four attempt.
LEAGUE_CHECKPOINT = 'league-entry.state'
CANNOT_END = 'battle cannot end'
# League attempts restarted from the entry save without a new Hall of Fame entry before the run is
# called off. Experience gained before each loss counts as progress, so the reload streak never caps it.
LEAGUE_RESTARTS = 3
BUTTONS = ('up', 'down', 'left', 'right', 'a', 'b', 'start', 'select')


def league_restart(restarts, wins):
    """Count a League attempt restarted from its entry save: the new count, and whether to call the run off.

    A live Crystal run reloaded its League entry fourteen times in half an hour, as the same team
    met the same trouble at Koga each time. The entry save forgets every attempt, so the count lives
    in the emulator and starts again only with a new Hall of Fame entry.
    """
    seen, count = restarts
    count = count + 1 if wins <= seen else 1
    if count >= LEAGUE_RESTARTS:
        return (max(wins, seen), 0), True
    return (max(wins, seen), count), False


@dataclass(frozen=True)
class Event:
    type: str
    title: str
    body: str = ''
    priority: int = 3
    notable: bool = True


def settled(metadata):
    """Whether a checkpoint was taken with no menu task running and nothing being backed out of.

    A reload drops the running menu task, so a save taken inside a menu brings the run back into a
    screen no plan owns. Saves from before this flag existed count when no menu task was saved.
    """
    if 'settled' in metadata:
        return bool(metadata['settled'])
    return not (metadata.get('policy_state') or {}).get('menu')


def hatch_progress(best, snapshot):
    """Whether a carried egg lost a cycle or hatched since the best seen, updating ``best``.

    A level 100 party walking stored eggs to hatching earns no experience, and a hatchling of a
    registered species adds nothing either, yet each egg can take hours of game time and a box of
    them days. Each egg counts once per cycle below its lowest seen and once on hatching, so a
    reload back to a fuller egg replays steps that already counted.
    """
    walked = False
    for mon in snapshot.party:
        key = (getattr(mon, 'trainer_id', None), tuple(getattr(mon, 'dvs', ()) or ()), getattr(mon, 'species', None))
        # A hatched egg stays on record below any cycle count, so its hatching counts only once.
        cycles = mon.friendship if getattr(mon, 'egg', False) else -1
        if key not in best:
            if cycles >= 0:
                best[key] = cycles
        elif cycles < best[key]:
            best[key] = cycles
            walked = True
    return walked


def progress_key(tiles, maps, snapshot):
    """What must change within the no-progress limit for a run to count as getting somewhere.

    Hit points and PP move during a battle that never ends, so they are not progress. The Day Care
    walk can outlast the limit with nothing else changing, so it counts two things that end:

    - An egg keeps its species, level and experience when it hatches, and walking one to hatching
      takes longer than the limit for many species. Each egg cycle counts, the friendship byte that
      drops every 256 steps until the egg hatches.
    - While a compatible pair waits for an egg, every step is another draw at it, and a poorly
      matched pair can take longer than the limit to make one. The cartridge clears the flag once
      the egg is made, so steps stop counting after that.
    """
    return (tiles, maps, snapshot.event_flags, snapshot.badges, snapshot.owned, snapshot.items,
            tuple((mon.species, mon.level, mon.experience, mon.egg, mon.friendship if mon.egg else None)
                  for mon in snapshot.party),
            snapshot.step_count if snapshot.breeding_compatible else None)


def reload_target(store, saves, since_frame):
    """The newest settled autosave made at least SCREEN_FRAMES of game time before ``since_frame``.

    Autosaves record the game frame, the clock the stuck guards count in, so the choice does not
    depend on wall-clock time or emulation speed. A save taken inside a menu is used only when no
    settled save is old enough. The oldest save is the fallback.
    """
    early = []
    for path in reversed(saves):
        metadata = store.checkpoint_metadata(path) or {}
        frame = metadata.get('frame')
        if isinstance(frame, int) and frame < since_frame - SCREEN_FRAMES:
            if settled(metadata):
                return path
            early.append(path)
    return early[0] if early else saves[0] if saves else None


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
        from ..planning.cost import gen2_cartridge_rows
        self.data.encounters = gen2_cartridge_rows(self.rom, self.profile.game, self.data.encounters)
        self.isolated_ram = isolated_ram
        self.preparation = None
        self.options_applied = False
        self.policy = Policy(self.data, seed=config.SEED, starter=config.STARTER)
        self.policy.load_state_dict(store.get('policy_state', {}))
        self.policy.trade_preferences = store.trade_preferences
        self.policy.trade_partners = store.trade_partners
        self.speed = config.SPEED
        self.paused = False
        self.frozen = False
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
        self.explored = set()
        self.stall = StallWatch(config.STALL_ALERT_GAME_MINUTES, config.STALL_ALERT_REAL_MINUTES,
                                config.STALL_ALERT_REPEAT_HOURS)
        self.reloads = 0
        self.last_reload = 0.0
        self.unstick_streak = 0
        self.reloads_exhausted = False
        self.league_restarts = (0, 0)
        self.waiting = False
        self.best_progress = (0,) * 6
        self.failure_streak = 0
        self.invalid_frame = self.battle_frame = None
        self.screen_key = None
        self.screen_frame = self.stuck_frame = 0
        self.stuck_ts = time.time()
        self.last_reload_frame = -10 ** 9
        self._guard_frame = 0
        self._watch_until = self._last_publish = 0.0
        self.history = store.get('gen2-history', {'maps': [], 'owned': [], 'badges': 0, 'league': 0})
        self.last_achievement = next(iter(store.events(limit=1)), None)
        from .tracking import Tracker
        self.tracker = Tracker(store, self.data, fresh=not bool(store.autosaves()))
        from .activity import Ledger
        self.activity = Ledger(store, self.data, fresh=not bool(store.autosaves()))
        from .statistics import Statistics
        self.statistics = Statistics(store, clock=lambda: self.play_clock.status())
        from ..goal_time import GoalTime
        self.goal_time = GoalTime(store)
        self.releases = journal.Releases()
        from .legendary import Recovery
        self.legendary_recovery = Recovery()
        from .steps import StepTracker
        self.steps = StepTracker(store, self.data)
        self.pb = self._boot()
        self.thread = threading.Thread(target=self._run, name='gen2-emulator', daemon=True)

    def _boot(self):
        # Save states own both SRAM and RTC. Shared ROM assets never own save files.
        from ..randomized import rom_stream
        pb = boot(rom_stream(self.rom), sound=True)
        # Game time from the first frame. The reading belongs to no adventure yet: a loaded state
        # or _sync_clock sets it before the policy plays.
        follow_game_time(pb)
        self._clock_live = False
        self.tracker.attach(pb)
        self.activity.attach(pb)
        self.steps.attach(pb)
        self.store_stock = StoreStock(self.data, champion=self._champion_catalogue, on_bought=self.activity.bought)
        self.store_stock.attach(pb)
        return pb

    def _champion_catalogue(self):
        """The planned Champion shop item for the clerk who opens the BUY list."""
        from . import champion_shop
        plan = self.policy.collection.get(champion_shop.PLAN)
        return champion_shop.catalogue(self.data, plan, champion_shop.ready(self.store, self.data, self.steps.value))

    def _champion_shop(self, snapshot):
        """Start the walking countdowns, share ready offers and record landed purchases."""
        from . import champion_shop
        champion_shop.observe(self.store, snapshot, self.steps.value)
        stock = getattr(self, 'store_stock', None)
        purchases = list(stock.purchases) if stock else []
        if stock:
            stock.purchases.clear()
        for item, count, price in purchases:
            champion_shop.consume(self.store, self.data, item, self.steps.value)
            plan = self.policy.collection.get(champion_shop.PLAN)
            if plan and plan['item'] == item:
                plan['bought'] = True
            name = champion_shop.label(self.data, item)
            self._event(Event('item', f'Bought {f"{count} × " if count > 1 else ""}{name}',
                              f'Spent ₽{price * count:,} at the Goldenrod Dept. Store Champion counter. '
                              'The purchase went through the cartridge BUY menu into the bag.', priority=3), snapshot)
        self.policy.shop_offers = champion_shop.ready(self.store, self.data, self.steps.value)

    def _remember_clock(self, elapsed):
        """Store the running clock's reading, so no restart, reload or trade can go back before it.

        Callers pass the live reading, which only moves forward with frames unless the game itself
        writes the clock registers: it zeroes the clock on a blank cartridge and takes 140 days off
        once the day counter reaches 140. Those writes are the game's time, so the newest reading
        replaces the stored one even when it is lower. Keeping the largest instead would put the
        clock back to before such a write on the next restart, and the game would see its time rewind.
        """
        self.store.set(CLOCK_KEY, {'elapsed': elapsed})

    def _clock_reading(self):
        """Seconds the running cartridge clock shows, or None before it belongs to an adventure."""
        return clock_elapsed(self.pb) if getattr(self, '_clock_live', False) else None

    def _sync_clock(self, metadata=None, running=None, fresh=False):
        """Lock the cartridge clock to game time at the furthest reading this adventure has seen.

        Gen II reads a clock earlier than its saved time as a reset, so the clock resumes from the
        largest of the stored reading, the checkpoint's own reading and the reading just before a
        reload. ``fresh`` adds what the state shows on the host clock, for a trade result made a
        moment ago on unlocked copies. A save from before game time existed has none of these and
        keeps the reading it had on the host clock, which then moves on with frames.
        """
        stored = (self.store.get(CLOCK_KEY) or {}).get('elapsed')
        candidates = [value for value in (stored, (metadata or {}).get('rtc_elapsed'), running)
                      if isinstance(value, (int, float))]
        if fresh or not candidates:
            candidates.append(host_elapsed(self.pb))
        elapsed = follow_game_time(self.pb, max(candidates))
        self._clock_live = True
        self._remember_clock(elapsed)
        return elapsed

    def start(self):
        # Any failure before the thread runs, such as a Core capability error, would otherwise leave
        # the booted emulator open with nothing to stop it.
        try:
            self._prepare_start()
        except BaseException:
            self.pb.stop(save=False)
            raise
        self.thread.start()

    def freeze(self):
        """Show the newest save of a stopped adventure without running it."""
        for path in reversed(self.store.autosaves()):
            try:
                self._load_state_file(path)
                break
            except (ValueError, OSError, EOFError):
                log.exception('Cannot show Gen II checkpoint %s', path.name)
        else:
            raise RuntimeError('This adventure has no save to show yet')
        self.frozen = self.paused = True

    def _prepare_start(self):
        errors = []
        for path in reversed(self.store.autosaves()):
            try:
                self._load_state_file(path)
                break
            except (ValueError, OSError, EOFError) as error:
                errors.append(error)
                log.exception('Cannot restore Gen II checkpoint %s', path.name)
        else:
            if errors:
                raise ValueError('No compatible Gen II autosave could be restored') from errors[-1]
            self._sync_clock()
        from .. import rewards
        rewards.initialize(self.store, self.snapshot.hall_of_fame_count if self.snapshot else 0)
        self._clear_stale_hold()
        preparation = self.store.get('interaction_preparation') or {}
        if preparation.get('phase') in {'travelling', 'storage', 'rendezvous'} or self.store.get('trade_hold'):
            self.paused = True

    def _clear_stale_hold(self):
        """Drop a trade hold whose exchange no longer exists, since a hold freezes every command."""
        hold = self.store.get('trade_hold')
        if not hold:
            return
        from ..runtime.participant import _records
        live = {row.get('id') for row in _records(self.store) if row.get('phase') != 'aborted'}
        if hold.get('id') not in live:
            log.warning('Clearing a trade hold with no live exchange')
            self.store.set('trade_hold', None)

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
        if (self.paused or not self.frame_image) and not self.frozen:
            self.call(self._publish_frame, timeout=max(1, timeout))
        with self.frame_cond:
            if not self.frame_image:
                self.frame_cond.wait(timeout)
        return self.frame_image

    def audio_packet(self, after):
        state = 'playing' if not self.paused or self.manual_mode else 'paused'
        sequence, pcm, measured, dropped = self.audio.read(after, state)
        # The worker catches up in bursts after a stall, and the measured pace then reads well above
        # the setting, past the point where the page mutes. Report the setting as Red and Blue do.
        # Unlimited has no setting to report, so it keeps the measurement.
        speed = 1 if self.manual_mode else self.speed
        return state, sequence, pcm, speed if speed > 0 else measured, dropped

    def _shot_png(self):
        output = io.BytesIO()
        image = self.pb.screen.image
        image.save(output, format='PNG')
        # Gold and Silver flash a single colour between screens. A thumbnail keeps the last picture.
        if not solid(image):
            self.still_image = output.getvalue()
        return output.getvalue()

    def still_frame(self, timeout=1):
        """The latest frame that shows a picture, never a blank screen transition."""
        frame = self.current_frame(timeout)
        return getattr(self, 'still_image', b'') or frame

    def _publish_frame(self):
        with self.frame_cond:
            self.frame_image = self._shot_png()
            self.frame_seq += 1
            self.frame_cond.notify_all()

    def _state_bytes(self):
        # The raw state keeps only the clock's zero point. Rebasing it on the host clock first means
        # an unlocked copy (a cable session or a save export) reads this game time or later.
        rebase_to_host(self.pb)
        output = io.BytesIO()
        self.pb.save_state(output)
        return output.getvalue()

    def _manifest(self):
        # Gen II saves with the clock locked to game time, which PyBoy 2.7.0 cannot reproduce, so the
        # lock goes into the manifest and Core leaves off the legacy pyboy_version tag.
        lock = clock_lock_state(self.pb)
        return {'app_version': __version__, **checkpoint_metadata(rtc_clock=lock), 'rtc_clock': lock, 'generation': 2,
                'rom_sha1': self.rom_sha1, 'frame': self.frame, 'policy': config.POLICY,
                'policy_state': self.policy.state_dict(), 'run_memory': {}, 'play_clock': self.play_clock.state_dict(),
                'gen2_history': self.history, 'legendary_recovery': self.legendary_recovery.state_dict(),
                'trade_id': self.store.get('trade_barrier'),
                'reward_id': self.store.get('custom-reward-barrier-v1'),
                'rtc_elapsed': clock_elapsed(self.pb),
                'settled': self.policy.menu is None and not getattr(self.policy, 'backing_out', False)}

    def _autosave(self, trade_prepare=False):
        if self.store.get('trade_hold') and not trade_prepare:
            return
        # Remember the clock even when no checkpoint follows, so a crash never resumes before it.
        if getattr(self, '_clock_live', False):
            self._remember_clock(clock_elapsed(self.pb))
        if self.snapshot is not None and not self.snapshot.valid:
            return
        # A save taken while backing out of a screen no plan owns would only bring the run back there.
        if not trade_prepare and getattr(self.policy, 'backing_out', False):
            return
        # Keep older saves intact while the run is wedged so a reload has somewhere good to go.
        if not trade_prepare and (self.frame - self.screen_frame >= SCREEN_FRAMES
                                  or self.battle_frame is not None
                                  and self.frame - self.battle_frame > config.BATTLE_TIMEOUT_SECONDS * 20):
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

    def _behind_barrier(self, metadata):
        """Whether a checkpoint predates the latest completed trade or custom reward.

        Loading one would undo that trade or reward, so it is never a place to go back to.
        """
        for key, field in [('trade_barrier', 'trade_id'), ('custom-reward-barrier-v1', 'reward_id')]:
            barrier = self.store.get(key)
            if barrier and (metadata or {}).get(field) != barrier:
                return True
        return False

    def _load_state_file(self, path):
        metadata = self.store.checkpoint_metadata(path)
        if self._behind_barrier(metadata):
            raise ValueError('Checkpoint predates a completed trade or custom reward')
        if metadata and (metadata.get('rom_sha1') != self.rom_sha1 or metadata.get('generation') != 2):
            raise ValueError('This checkpoint belongs to a different cartridge')
        if metadata is None:
            raise ValueError('Gen II checkpoints require cartridge identity metadata')
        validate_runtime(metadata)
        running = self._clock_reading()
        if running is not None:
            self._remember_clock(running)
        hold = self.store.get('trade_hold') or {}
        # A committed trade result is loaded once while its hold is still 'prepared'.
        fresh = (Path(path).name.startswith('auto-v1-link-') and hold.get('phase') == 'prepared'
                 and metadata.get('trade_id') == hold.get('id'))
        with open_state(path) as source:
            self.pb.load_state(source)
        # A raw state restores the clock's zero point but not the lock, so lock again at the furthest reading.
        self._sync_clock(metadata, running, fresh=fresh)
        for button in BUTTONS:
            self.pb.button_release(button)
        self.frame = metadata.get('frame', 0)
        self.policy.load_state_dict(metadata.get('policy_state', {}))
        self.policy.on_restore()
        self.play_clock.restore(metadata.get('play_clock'))
        if 'gen2_history' in metadata:
            self.history = metadata['gen2_history']
        else:
            # Without its own history the save's League count cannot be matched to the wins kept
            # past the cartridge's cap, and adding them to an older count would invent victories.
            self.history.pop('capped_wins', None)
            self.history.pop('league_attempt', None)
        self.previous = None
        self.statistics.previous = None
        from .legendary import Recovery
        self.legendary_recovery = Recovery(metadata.get('legendary_recovery'))
        self.snapshot = self._read()
        self.audio.clear()
        self.options_applied = False
        self._reset_watch()
        self._publish_frame()

    def _event(self, event, snapshot):
        shot = self._shot_png()
        # Timeline-only entries such as faints and first sightings keep a picture but no save, as in Red, Blue and Yellow.
        state = self._state_bytes() if event.notable else None
        eid = self.store.add_event(event, snapshot, shot, state)
        if state:
            self.store.write_checkpoint(state, self._manifest(), name=f'event-{eid}.state')
        if event.type not in journal.NOT_PROGRESS:
            self.last_achievement = self.store.event(eid)
        if event.notable and self.ntfy and self.ntfy.wants(event):
            self.ntfy.send(event.title, event.body, priority=event.priority, image=shot,
                           event_type=event.type, click=f'{config.PUBLIC_URL}/events/{eid}')

    def _report_missed_shiny(self, snapshot):
        """Say once per battle why a wild shiny was run from, with the Red, Blue and Yellow notice.

        Balls cannot be bought and storage cannot be freed in battle, so the policy runs instead
        of knocking it out. The supply and storage reserves are what keep a shiny catchable.
        """
        if not snapshot.enemy_shiny or snapshot.in_battle != 1:
            self._shiny_reported = False
            return False
        why = getattr(self.policy, 'shiny_missed', None)
        if not why or getattr(self, '_shiny_reported', False):
            return bool(why)
        self._shiny_reported = True
        species = self.data.species.get(snapshot.enemy_species, {}).get('name') or 'Pokémon'
        self._event(Event('shiny_missed', f'Shiny {species} could not be caught: {why}',
                          f'A shiny {species} appeared with {why}, so the adventure ran from it. '
                          'The supply and storage reserves should prevent this.', priority=LOW), snapshot)
        return True

    def _read(self, observe=False):
        return count_league(self.history, self.data, read_snapshot(self.pb.memory, self.data, self.frame), observe=observe)

    def _observe(self):
        snapshot = self._read(observe=True)
        self.snapshot = snapshot
        self.invalid_frame = (self.invalid_frame if self.invalid_frame is not None else self.frame) if not snapshot.valid else None
        if not snapshot.valid or not snapshot.started:
            self.stuck_frame, self.stuck_ts = self.frame, time.time()
            return
        if not self.options_applied and not self.manual_mode:
            from pokecore.gen2.ram import Memory
            mem = Memory(self.pb.memory, self.data)
            value = mem.byte('wOptions')
            if config.FAST_TEXT:
                value = value & ~7 | 1
            value = value & ~128 if config.BATTLE_ANIMATIONS else value | 128
            bank, address = self.data.symbols['wOptions']
            self.pb.memory[bank, address] = value
            self.options_applied = True
        self.play_clock.seed(snapshot.playtime_seconds)
        self.store.upgrade_trade_preferences(lambda: [mon.to_dict(egg_view=True) for mon in (*snapshot.party, *snapshot.stored)])
        self.game_clock = game_clock(self.pb.memory, self.data)
        self.tracker.observe(snapshot)
        from .steps import observe_mew
        self.steps.flush()
        self._champion_shop(snapshot)
        self.statistics.observe(snapshot)
        if hasattr(self, 'goal_time'):
            from ..goal_time import gen2_view
            self.goal_time.observe(*gen2_view(self.policy), self.frame)
        if not self.store.get('trade_hold') and not self.preparation and not self.manual_mode:
            from . import returns
            from .legendary import first_notice
            walking = self.steps.value
            notices, changed = returns.observe(self.store, snapshot, self.pb.memory, walking)
            activity, reopened = returns.observe_events(self.store, snapshot, self.pb.memory, walking)
            ready, closed = returns.claims(self.store)
            self.policy.returned = ready | returns.returned_events(self.store)
            for event in notices + activity:
                self._event(event, snapshot)
            for species in self.legendary_recovery.observe(snapshot, self.pb.memory, repeat=ready, blocked=closed):
                changed = True
                if not first_notice(self.store, species, self.legendary_recovery.attempts.get(str(species), 0)):
                    continue
                self._event(Event('legendary_retry', f'{self.data.species[species]["name"]} can be encountered again',
                    'The encounter ended without a catch. Used supplies and adventure progress are preserved.'), snapshot)
            if changed or reopened:
                snapshot = self.snapshot = self._read()
        if snapshot.map not in self.history['maps']:
            self.history['maps'].append(snapshot.map)
            self._event(Event('map', f'Arrived at {snapshot.map_name}', priority=2), snapshot)
        for dex in sorted(snapshot.owned - set(self.history['owned'])):
            self.history['owned'].append(dex)
            self._event(journal.catch(self.data, dex, self.previous, snapshot, Event), snapshot)
        from .npc_trades import completed
        if 'npc_trades' not in self.history:
            # Trades finished before this record existed are history, not news.
            completed(self.pb.memory, self.data, self.history.setdefault('npc_trades', []))
        for trade in completed(self.pb.memory, self.data, self.history['npc_trades']):
            from .activity import npc_trade
            npc_trade(self.store, trade)
            self._event(Event('trade', f'Traded {self.data.species[trade.request]["name"]} to {trade.npc} for '
                              f'{self.data.species[trade.give]["name"]}', 'An in-game trade completed on this cartridge.',
                              priority=4), snapshot)
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
        self._note_league_entry(before, snapshot)
        for event in journal.events(before, snapshot, self.history, self.data, Event):
            self._event(event, snapshot)
        for event in self.releases.observe(self.policy.menu, snapshot, self.data, Event):
            self._event(event, snapshot)
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
        now = time.time()
        self._watch_progress(snapshot, now)
        self._note_progress(snapshot, now)
        screen = hash((snapshot.tiles, snapshot.map, snapshot.x, snapshot.y, snapshot.in_battle))
        if screen != self.screen_key:
            self.screen_key, self.screen_frame = screen, self.frame
        if before and (before.map, before.x, before.y) != (snapshot.map, snapshot.x, snapshot.y) or snapshot.in_battle:
            self.stuck_since = now
            self.stuck_frame, self.stuck_ts = self.frame, now
        self._time_battle(snapshot)
        self.previous = snapshot

    def _note_league_entry(self, before, snapshot):
        """Keep a save on arriving at the Indigo Plateau Pokémon Center, the way into the League.

        Nobody leaves the League part way and nothing inside restores PP, so this is the save that
        can undo an attempt that ran out of attacks.
        """
        lobby = self.data.map_ids['INDIGO_PLATEAU_POKECENTER_1F']
        if not before or before.map == lobby or snapshot.map != lobby or self.store.get('trade_hold'):
            return
        try:
            self.store.write_checkpoint(self._state_bytes(), self._manifest(), name=LEAGUE_CHECKPOINT)
        except OSError:
            log.exception('cannot write the League entry checkpoint')

    def _time_battle(self, snapshot):
        """Restart the hung-battle clock each time a new opposing Pokémon enters.

        A long trainer battle, like Red's six Pokémon against an underlevelled team, can outlast
        BATTLE_TIMEOUT_SECONDS while still knocking out opponents. Only a battle that stops
        bringing out new opponents is hung. Each opponent counts once, so switching cannot
        keep a stuck battle alive forever.
        """
        if not snapshot.in_battle:
            self.battle_frame, self.battle_opponents = None, set()
            return
        opponents = getattr(self, 'battle_opponents', None)
        if self.battle_frame is None or opponents is None:
            self.battle_frame, opponents = self.frame, set()
        opponent = (snapshot.enemy_species, snapshot.enemy_level)
        if opponent not in opponents:
            if opponents:
                self.battle_frame = self.frame
            opponents.add(opponent)
        self.battle_opponents = opponents

    def _note_progress(self, snapshot, now):
        # Wandering to new tiles is not progress, and a reload rewinds to an older save, so only a
        # new high for badges, events, Pokédex entries, areas, experience or League wins ends a run
        # of reloads. A finished run with a full Pokédex and a level 100 team still wins the League.
        score = (snapshot.badges.bit_count(), sum(byte.bit_count() for byte in snapshot.event_flags), len(snapshot.owned),
                 len(self.history['maps']), sum(getattr(mon, 'experience', 0) or 0 for mon in snapshot.party),
                 self.history.get('league', 0))
        # The party total drops when a trained Pokémon is swapped for a new trainee, so experience
        # also counts per Pokémon: any party member beating its own best is progress.
        best_experience = self.__dict__.setdefault('best_experience', {})
        trained = False
        for mon in snapshot.party:
            key = (getattr(mon, 'trainer_id', None), tuple(getattr(mon, 'dvs', ()) or ()), getattr(mon, 'species', None))
            experience = getattr(mon, 'experience', 0) or 0
            if experience > best_experience.get(key, experience):
                trained = True
            best_experience[key] = max(experience, best_experience.get(key, 0))
        trained = hatch_progress(self.__dict__.setdefault('best_egg_cycles', {}), snapshot) or trained
        if trained or any(new > old for new, old in zip(score, self.best_progress)):
            self.best_progress = tuple(max(new, old) for new, old in zip(score, self.best_progress))
            self.stall.progress(self.frame, now)
            self.unstick_streak = 0
            self.reloads_exhausted = False

    def _watch_progress(self, snapshot, now):
        """Restart the progress clocks and the failure streak when the run achieves something new.

        Tiles stepped on count from this record, not from the policy's navigator. Each policy recovery
        starts a fresh navigator, so its first tile looked new after every failure. A goal that failed
        for want of a route then never reached the failure limit, and a Crystal run kept failing at the
        Battle Tower for hours without a reload.
        """
        self.explored.add((snapshot.map, snapshot.x, snapshot.y))
        key = progress_key(len(self.explored), len(self.history['maps']), snapshot)
        if key != self.progress_key:
            self.progress_key, self.progress_frame = key, self.frame
            self.stuck_frame, self.stuck_ts = self.frame, now
            self.failure_streak = 0

    def _reset_watch(self):
        """Restart the stuck clocks after a reload, which also rewinds the frame counter."""
        now = time.time()
        self.explored = set()
        self.progress_frame = self.screen_frame = self.stuck_frame = self.last_reload_frame = self.frame
        self.stuck_ts = self.stuck_since = now
        self.screen_key = self.progress_key = None
        self.invalid_frame = self.battle_frame = None
        self._reward_check_frame = self.frame
        # A reload rewinds the frame counter, so the next guard check must be due from the restored
        # frame. Left at the old frame, the guards slept until the run caught up, a clock wait was
        # never seen and its progress clock never restarted, and the first check then reloaded it.
        self._guard_frame = self.frame
        self.waiting = False
        self.stall.frame = None

    def _unstick(self, since_frame, why):
        """Go back to an autosave from before the trouble started, or power-cycle when there is none."""
        if self.unstick_streak >= MAX_RELOADS:
            # Reloading again would only replay the same trouble. Leave the run as it is, flagged as
            # stalled, and say so once rather than at every guard check.
            if not getattr(self, 'reloads_exhausted', False):
                log.error('%s and %d reloads did not help, not reloading again', why, self.unstick_streak)
                self.reloads_exhausted = True
            self._reset_watch()
            return
        all_saves = self.store.autosaves()
        # A save from before a completed trade or reward is refused on load. Choosing it anyway
        # spent a reload on an error and fell back to whatever came next, so the watchdog swung
        # between the refused save and the newest one until it ran out of reloads.
        saves = [path for path in all_saves if not self._behind_barrier(self.store.checkpoint_metadata(path))]
        target = reload_target(self.store, saves, since_frame)
        self.unstick_streak += 1
        entry = None
        if ((self.unstick_streak >= 2 or why == CANNOT_END) and self.snapshot is not None
                and self.policy.in_league(self.snapshot)):
            # A save part way through the League keeps the PP already spent, so going back a little
            # replays the same lost battle. Restart the attempt from before it began instead.
            entry = self.store.state_path(LEAGUE_CHECKPOINT)
            if entry and not self._behind_barrier(self.store.checkpoint_metadata(entry)):
                log.warning('%s inside the League, restarting the attempt', why)
                target, saves = entry, [entry] + saves
            else:
                entry = None
        if self.unstick_streak == 2 and self.snapshot is not None and self.snapshot.valid and self.snapshot.started:
            self._event(Event('stall', 'Stuck? The adventure had to reload twice',
                              f'{why.capitalize()} at {self.snapshot.map_name} and a reload did not help. '
                              f'{self.policy.recoveries} recoveries so far.', priority=HIGH), self.snapshot)
        restored = None
        from .standdown import carry_over, stalled_objectives
        stalled = stalled_objectives(self.policy)
        wins = getattr(self.snapshot, 'hall_of_fame_count', 0)
        if target:
            log.warning('%s for %.1f game minutes, reloading %s', why, max(0, self.frame - since_frame) / 3600, target.name)
            for path in [target] + [path for path in reversed(saves) if path != target]:
                try:
                    self._load_state_file(path)
                    restored = path
                    break
                except (ValueError, OSError, EOFError):
                    log.exception('Cannot reload Gen II checkpoint %s', path.name)
        if restored:
            carry_over(self.policy, stalled)
            if entry is not None and restored == entry:
                self.league_restarts, call_off = league_restart(getattr(self, 'league_restarts', (0, 0)), wins)
                from .collection import call_off_league
                if call_off and call_off_league(self.policy):
                    log.warning('the League attempt restarted %d times, leaving to prepare the team', LEAGUE_RESTARTS)
            # The emulator is deterministic, so the same save and choices would replay the same
            # trouble. Idling a random moment moves the game's random numbers along.
            self._tick(1 + secrets.randbelow(180))
        elif all_saves and not saves:
            # Every save predates the trade or reward. Power-cycling falls back on the cartridge's own
            # save, which can predate it too, so keep playing from here instead.
            log.warning('%s and every save predates a completed trade or reward, not reloading', why)
            self._reset_watch()
            return
        else:
            log.warning('%s and no save state to go back to, power-cycling', why)
            self.pb.stop(save=False)
            self.pb = self._boot()
            self._sync_clock()
            self.options_applied = False
            self.previous = self.snapshot = None
            self.audio.clear()
            self.policy.on_restore()
            self.statistics.previous = None
        self.policy.menu = None
        self.reloads += 1
        self.last_reload = time.time()
        self._reset_watch()

    def _check_guards(self):
        """Escalate from a gentle policy reset, to exploratory buttons, to reloading an older save."""
        if self.paused or self.manual_mode or self.preparation or self.store.get('trade_hold'):
            self.stuck_frame = self.screen_frame = self.progress_frame = self.frame
            self.stuck_ts = time.time()
            return
        snapshot = self.snapshot
        if snapshot is None or self.frame - self.last_reload_frame < 3600:
            return
        if self.policy.idle(snapshot):
            # Standing still until the cartridge clock reaches another day is the plan, not a
            # stuck run. Reloading cannot hurry the clock and only rewinds the adventure.
            self.stuck_frame = self.screen_frame = self.progress_frame = self.frame
            self.stuck_ts = time.time()
            self.stall.frame = None
            self.waiting = True
            return
        # Walking the grass while the clock is wrong is the plan too. It earns no progress, so only
        # the progress clocks restart; a patrol that stops moving still trips the stuck checks.
        self.waiting = bool(self.policy.waiting(snapshot))
        if self.waiting:
            self.progress_frame = self.frame
            self.stall.frame = None
        limit, frame = config.STUCK_RELOAD_SECONDS * 60, self.frame
        failure = self.policy.take_failure()
        if failure:
            self.failure_streak += 1
            log.warning('policy gave up: %s', failure)
        if self.invalid_frame is not None and frame - self.invalid_frame > 600:
            self._unstick(self.invalid_frame, 'game state glitched')
        elif self.failure_streak >= 3:
            self._unstick(self.stuck_frame, 'a menu task kept failing')
        elif self.battle_frame is not None and frame - self.battle_frame > config.BATTLE_TIMEOUT_SECONDS * 60:
            self._unstick(self.battle_frame, 'battle never ended')
        elif self.battle_frame is not None and self.policy.hopeless_battle(snapshot):
            # Nobody standing can hurt the foe and Struggle is out of reach, so the timeout has nothing to wait for.
            self._unstick(self.battle_frame, CANNOT_END)
        elif frame - self.stuck_frame > limit:
            self._unstick(self.stuck_frame, 'stuck')
        elif frame - self.progress_frame > 3 * limit:
            self._unstick(self.progress_frame, 'no progress')
        elif frame - self.screen_frame >= SCREEN_FRAMES:
            level = 1 if self.policy.recoveries % 3 == 0 else 2
            self.policy.recover(level)
            self.screen_frame = frame
            log.warning('the screen has not changed for %d frames, recovery level %d', SCREEN_FRAMES, level)
        self._check_stall()

    def _check_stall(self):
        """Report a run that keeps playing without achieving anything for hours of game time."""
        snapshot = self.snapshot
        if snapshot is None or not snapshot.valid or not snapshot.started:
            return
        quiet = self.stall.check(self.frame, time.time())
        if quiet is None:
            return
        details = self.policy.details()
        objective = (details.get('objective') or {}).get('label') or 'no objective'
        hours = quiet[0] / 60
        log.warning('no progress for %.1f game hours at %s: %s', hours, snapshot.map_name, objective)
        self._event(Event('stall', f'Stuck? {hours:.0f} game hours without progress',
                          f'Objective: {objective}. On {snapshot.map_name} after {quiet[1]} real minutes '
                          f'and {self.policy.recoveries} recoveries.', priority=HIGH), snapshot)

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
                try:
                    self._load_state_file(path)
                except (ValueError, OSError, EOFError) as error:
                    # A refused rewind (ownership barrier, other cartridge) must never end the adventure.
                    log.warning('Rewind to %s refused: %s', path.name, error)
        elif name == 'restart':
            self._autosave()
            for path in self.store.states.glob('auto-*.state'):
                path.unlink()
                path.with_suffix('.json').unlink(missing_ok=True)
            for key in ('trade_barrier', 'custom-reward-barrier-v1', 'custom-reward-pending-v1',
                        'league-rewards-v1', 'gen2-mythical-gift-v1', 'gen2-gs-ball-distribution-v1', 'gen2-league-partners-v1',
                        'gen2-mew-returns-v1'):
                self.store.set(key, None)
            self.store.clear_trade_preferences()
            self.pb.stop(save=False)
            self.tracker.reset()
            self.steps.flush(force=True)
            self.statistics.previous = None
            self.statistics.records.reset()
            from .legendary import Recovery
            self.legendary_recovery = Recovery()
            # A new run starts a new cartridge clock.
            self.store.set(CLOCK_KEY, None)
            self.pb = self._boot()
            self._sync_clock()
            self.options_applied = False
            self.frame = 0
            self.previous = self.snapshot = None
            self.history = {'maps': [], 'owned': [], 'badges': 0, 'league': 0}
            self.policy = Policy(self.data, seed=config.SEED, starter=config.STARTER)
            self.policy.trade_preferences = self.store.trade_preferences
            self.policy.trade_partners = self.store.trade_partners
            self.play_clock = PlayClock()
            self.paused = self.manual_mode = False
            # The old run's bests and reload streak would hold the new one stalled for good, and the
            # watch clocks still pointed at its frames, which kept the guards and reward checks off.
            self.best_progress = (0,) * 6
            self.best_experience, self.best_egg_cycles = {}, {}
            self.unstick_streak = 0
            self.reloads_exhausted = False
            self.league_restarts = (0, 0)
            self.stall = StallWatch(config.STALL_ALERT_GAME_MINUTES, config.STALL_ALERT_REAL_MINUTES,
                                    config.STALL_ALERT_REPEAT_HOURS)
            self._reset_watch()
            self._autosave()
        return True

    def _run(self):
        next_save = time.monotonic() + config.AUTOSAVE_SECONDS
        self.consecutive_errors = 0
        try:
            running = True
            while running:
                try:
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
                        from .celebi import activate
                        self._reward_check_frame = self.frame
                        if activate(self) or deliver(self):
                            continue
                    if self.preparation and not self.paused:
                        snapshot = self._read()
                        action = self.preparation.step(snapshot)
                    elif not self.manual.empty():
                        action = self.manual.get_nowait()
                    elif self.manual_mode:
                        action = Action(None, 0, 4)
                    elif self.paused:
                        self.last_activity = time.monotonic()
                        self.consecutive_errors = 0
                        time.sleep(0.03)
                        continue
                    else:
                        snapshot = self._read()
                        action = self.policy.step(snapshot, self.pb.memory, stack_pointer(self.pb))
                        self._report_missed_shiny(snapshot)
                    if action.button:
                        self.pb.button_press(action.button)
                    try:
                        self._tick(action.hold)
                    finally:
                        if action.button:
                            self.pb.button_release(action.button)
                    self._tick(action.gap)
                    if self.frame >= self._guard_frame:
                        self._guard_frame = self.frame + 60
                        self._check_guards()
                    if time.monotonic() >= next_save and not getattr(self.policy, 'backing_out', False):
                        self._autosave()
                        next_save = time.monotonic() + config.AUTOSAVE_SECONDS
                    self.consecutive_errors = 0
                except Exception:
                    if loop_failed(self, log):
                        break
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
        from ..randomized import status as randomizer_status
        achievement = self.last_achievement
        if achievement:
            # The live page says how long ago it was, the same as Red, Blue and Yellow.
            achievement = {'id': achievement['id'], 'title': achievement['title'], 'ts': achievement['ts'],
                           'age_seconds': max(0, int(time.time() - achievement['ts']))}
        quiet_minutes = max(0, self.frame - self.progress_frame) / 3600
        live = not self.paused and not self.manual_mode
        waiting = live and self.waiting
        stalled = live and not waiting and (self.stall.stalled(self.frame, time.time()) or self.unstick_streak >= STALL_RELOADS)
        recovering = time.time() - self.last_reload < 30 or self.policy.mode == 'finding another approach'
        return {'version': __version__, 'generation': 2, 'build': build_info(), 'viewer_only': config.VIEWER_ONLY,
                'stopped': self.frozen,
                'health': self.health(), 'paused': self.paused, 'manual_mode': self.manual_mode, 'speed': self.speed,
                'policy': self.policy.describe(), 'strategy': self.policy.details(), 'frame': self.frame,
                'game': self.snapshot.to_dict(egg_view=True) if self.snapshot else None, 'rom': self.rom_note,
                'play_clock': self.play_clock.status(), 'clock': getattr(self, 'game_clock', None), 'performance': {'frames': self.executed_frames, 'sampled_at': time.monotonic()},
                'uptime': int(time.time() - self.started_at), 'stuck_seconds': int(time.time() - self.stuck_since),
                'areas_discovered': len(self.history['maps']), 'reloads': self.reloads,
                'glitched': self.invalid_frame is not None and self.frame - self.invalid_frame > 300,
                'help_request': {'reason': 'The policy has stopped making game progress',
                                 'action': self.policy.mode} if stalled else None,
                'progress': {'state': 'stalled' if stalled else 'waiting' if waiting else 'recovering' if recovering
                             else 'making_progress',
                             'last_achievement': achievement, 'quiet_game_minutes': round(quiet_minutes, 1)},
                'league_rewards': rewards.status(self.store), 'legendary_recovery': self.legendary_recovery.state_dict(),
                'randomizer': randomizer_status()}

    def set_trade_preference(self, key, state):
        from ..trade.preferences import update
        from .web import live_status
        return self.call(lambda: update(self.store, live_status(self.status().get('game'),
                                                              self.policy.details()['collection']), key, state))
