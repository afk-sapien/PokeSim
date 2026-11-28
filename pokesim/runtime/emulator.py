"""The half of the application's emulator that Red, Blue, Yellow, Gold, Silver and Crystal share.

``pokesim/emulator.py`` (Gen I) and ``pokesim/gen2/emulator.py`` (Gen II) subclass ``EmulatorBase``. The
base runs the command queue, the control lease, manual presses, the step with its pacing and frame
publishing, the named checkpoints, the trade and reward barriers, the autosave once one is allowed, and
the choice of save a reload goes back to. It also writes each journal entry, reports a stall, a dropped
pin and a shiny that cannot be caught, serves the PC values and release requests, and gives the status
keys both generations report alike. Each generation keeps what reads its own cartridge: boot, load,
observation, what goes in the journal, the guards, when an autosave is allowed, the run loop and its own
status keys. Where the two differ in one step, the base calls a hook below that the generation fills.
docs/design/one-bot.md, item 2.
"""
from __future__ import annotations

import io
import logging
import queue
import threading
import time

from .. import __version__, audio, config
from ..build_info import build_info
from ..events import HIGH, LOW, Event
from ..planning import pin
from . import capture, trace
from .manifest import checkpoint_manifest
from .policy import BUTTONS, Action
from .reload import FRAMES_PER_SECOND, reload_target
from .restart import restart

log = logging.getLogger(__name__)

# Written on the way into the League, the last place before an Elite Four attempt.
LEAGUE_CHECKPOINT = 'league-entry.state'
# Kept by name, so a wrong rewind or restart can be undone from the saves list.
BEFORE_LOAD_CHECKPOINT = 'before-load.state'
BEFORE_RESTART_CHECKPOINT = 'before-restart.state'
# A manual press holds its button for 6 frames and then waits 2. Two presses can wait their turn,
# so a held key on the page cannot queue up seconds of input.
MANUAL_PRESS = (6, 2)
MANUAL_QUEUE = 2
SNAPSHOT_EVERY = 30       # frames between observations
CHUNK = 4                 # frames per render and pacing step while nobody listens
WATCH_GRACE = 2.0         # seconds a frame request keeps the stream considered live
MAX_SPEED = 16.0
# A save without the latest completed trade or custom reward would undo it, so it never loads.
BARRIERS = (('trade_barrier', 'trade_id'), ('custom-reward-barrier-v1', 'reward_id'))


class EmulatorBase:
    """The shared half of the application's emulator. See the module docstring."""

    generation = 0
    stopping = False
    _audio_enabled = False
    # Encoding a frame costs far more than emulating one, so only encode while something is
    # actually asking for frames, and no faster than the stream can show them. Class defaults so
    # a partially built emulator still ticks.
    _watch_until = 0.0
    _last_publish = 0.0
    # The emulator frame and the guard clocks that count it, also class defaults for a partially
    # built emulator. No reload has happened yet, so its quiet spell is long past.
    frame = 0
    stuck_frame = 0
    last_reload_frame = -10 ** 9
    invalid_frame = None
    battle_frame = None
    # The latest ball thrown in this wild battle, which restarts the battle timeout (battle_clock).
    throws = None
    # Red, Blue and Yellow push an entry with its emoji tags. Gold, Silver and Crystal never have.
    PUSH_TAGS = True
    # The sentence a stall entry ends with.
    STALL_NOTE = ''

    # ---------------- lifecycle ----------------
    def stop(self):
        self.stopping = True
        self.commands.put(('stop', None))
        self.thread.join(timeout=20)
        if self.thread.is_alive():
            raise RuntimeError('The emulator did not stop within 20 seconds')

    def health(self) -> dict:
        alive = self.thread.is_alive()
        age = max(0, time.monotonic() - self.last_activity)
        healthy = alive and not self.fatal_error and age < 30 and not self.stopping
        return {'ok': healthy, 'worker_alive': alive, 'activity_age_seconds': round(age, 1),
                'error': self.fatal_error}

    def _shared_status(self) -> dict:
        """The status keys both generations report alike. Each generation's ``status`` adds its own."""
        from .. import rewards
        from ..randomized import status as randomizer_status
        return {'version': __version__, 'build': build_info(), 'viewer_only': config.VIEWER_ONLY,
                'stopped': self.frozen, 'health': self.health(), 'paused': self.paused,
                'manual_mode': self.manual_mode, 'speed': self.speed, 'policy': self.policy.describe(),
                'frame': self.frame, 'rom': self.rom_note, 'play_clock': self.play_clock.status(),
                'performance': {'frames': self.executed_frames, 'sampled_at': time.monotonic()},
                'uptime': int(time.time() - self.started_at),
                'stuck_seconds': max(0, self.frame - self.stuck_frame) // FRAMES_PER_SECOND,
                'reloads': self.reloads, 'league_rewards': rewards.status(self.store),
                'legendary_recovery': self.legendary_recovery.state_dict(), 'randomizer': randomizer_status()}

    # ---------------- public controls (thread-safe) ----------------
    def command(self, name: str, arg=None):
        self.commands.put((name, arg))

    def call(self, function, timeout=30):
        """Run a participant operation in the same queue as ticks and controls."""
        if threading.current_thread() is self.thread:
            return function()
        if not self.thread.is_alive():
            raise RuntimeError('The emulator is not running')
        done, response = threading.Event(), {}
        self.commands.put(('runtime_call', (function, done, response)))
        if not done.wait(timeout):
            raise TimeoutError('The operation is still pending. Retry the same operation ID.')
        if 'error' in response:
            raise response['error']
        return response.get('result')

    def goals(self, query=None):
        """The goals a manager can set as the next activity, named like ``query`` if given. Runs on the
        game thread."""
        goals, reason = self.policy.goals(self.snapshot, query)
        return pin.listing(goals, self.policy.pin, reason)

    def catalogue(self, query=None, limit=None):
        """The goal catalogue (planning/catalogue.py), named like ``query`` if given. Runs on the game
        thread and changes nothing the run does."""
        if limit is None:
            return self.policy.catalogue(self.snapshot, query)
        return self.policy.catalogue(self.snapshot, query, limit)

    def pin_goal(self, key):
        """Set the next activity. A ValueError says why the planner cannot take it now."""
        trace.note(self, 'pin', {'key': key})
        return self.policy.pin_goal(self.snapshot, key).to_dict()

    def unpin_goal(self):
        trace.note(self, 'pin', {'key': None})
        self.policy.unpin_goal()

    def _drop_pin(self, reason):
        """Drop the manager's pin before a recovery, and journal it here since a reload loses any note."""
        drop = getattr(getattr(self, 'policy', None), 'drop_pin', None)
        label = drop() if drop else None
        if label is not None and getattr(self, 'snapshot', None) is not None:
            self._event(Event(**pin.gave_up(label, reason)), self.snapshot)

    def _headroom(self, snapshot) -> int:
        """The free storage space a PC value weighs a release against."""

    def _identity(self, mon):
        """The key a release request names a boxed Pokémon by."""

    def pc_values(self):
        """Each boxed Pokémon's PC value by (box, position), and whether nothing may go (pcvalue.annotate)."""
        from ..pcvalue import annotate, deadlocked

        def view():
            snapshot = self.snapshot
            if snapshot is None or not hasattr(self.policy, 'pc_rated'):
                return {}, False
            rated = self.policy.pc_rated(snapshot)
            return annotate(rated, snapshot.active_box), deadlocked(rated, self._headroom(snapshot))
        return self.call(view, timeout=5)

    def _request_slots(self, snapshot, key):
        """The (box, position) of each held Pokémon a release request's key names, None for a party copy."""

    def request_release(self, box, position, key, confirm=''):
        """Store the owner's Release for the boxed Pokémon at (box, position), or raise ValueError.

        The request is saved under the full trade key the PC row carries, which names that one copy, so
        a release never takes its twin.
        """
        from ..pcvalue import pc_request
        from ..trade.preferences import base

        def request():
            snapshot = self.snapshot
            if snapshot is None or not hasattr(self.policy, 'pc_rated'):
                raise ValueError('Wait for the adventure to be ready before releasing.')
            value = pc_request(self.policy.pc_rated(snapshot), (box, position), base(key), self._identity,
                               self._request_slots(snapshot, key), confirm)
            self.store.set_release_request(key, value)
            return value
        return self.call(request)

    def press(self, button: str):
        if button in BUTTONS:
            self.command('press', button)

    def control(self, name, timeout=4, gate=None):
        """Run take_control, resume or pause now. Returns why the game held it back, or None.
        `gate` is asked on the game thread first: None runs it, '' counts it as done already."""
        def apply():
            reason = self.held_back(name)
            if reason is None and gate is not None:
                reason = gate()
            if reason is None:
                self._handle_command(name, None)
            return reason or None
        return self.call(apply, timeout)

    def watch(self):
        """Note that something wants frames. Viewers call this as they poll or stream."""
        self._watch_until = time.monotonic() + WATCH_GRACE

    def audio_packet(self, after):
        state = 'paused' if self.paused and not self.manual_mode else 'playing'
        sequence, pcm, measured, dropped = self.audio.read(after, state)
        # The worker catches up in bursts after a stall, so the measured pace jumps around the
        # setting. Report the setting and let the page's buffer absorb the bursts. Unlimited has
        # no setting to report, so it keeps the measurement.
        speed = 1 if self.manual_mode else self.speed
        return state, sequence, pcm, speed if speed > 0 else measured, dropped

    # ---------------- the step ----------------
    def _sync_audio(self, enabled):
        if enabled == self._audio_enabled:
            return
        # Keep hardware registers and clocks running while muted. Only PCM sampling
        # follows listeners, so a browser reconnect cannot restore stale channels.
        self._audio_enabled = enabled
        self.audio.clear()

    def _tick(self, n: int):
        """Advance frames, rendering only for an observation or a waiting viewer."""
        while n > 0 and not self.stopping:
            listening = self.audio.active()
            # Above the audio limit the page mutes and the server sends no sound, so sampling it
            # would only slow the game. Unlimited speed counts as above the limit.
            speed = 1 if self.manual_mode else self.speed
            audible = listening and 0 < speed <= audio.MAX_SPEED
            self._sync_audio(audible)
            k = min(1 if audible else CHUNK, n)
            observing = (self.frame + k) // SNAPSHOT_EVERY != self.frame // SNAPSHOT_EVERY
            publishing = self._due_to_publish(time.monotonic())
            # Policy reads the cartridge tilemap, not the rendered image. Keep
            # observation frames fresh for journal screenshots and fade retakes.
            self.pb.tick(k, render=observing or publishing, sound=audible)
            if audible:
                self.audio.publish(self.pb.sound.raw_buffer[:self.pb.sound.raw_buffer_head])
            elif listening:
                # Count the frames with no sound, so the page still sees the pace and says why
                # the sound is off.
                self.audio.publish(b'', k)
            self.frame += k
            self.executed_frames += k
            self.play_clock.advance(k)
            n -= k
            if publishing:
                self._last_publish = time.monotonic()
                self._publish_frame()
            if observing:
                self._observe()
            self._pace(k)
            self.last_activity = time.monotonic()

    def _due_to_publish(self, now: float) -> bool:
        if now >= self._watch_until:
            return False
        # A tick step is already about one stream interval at 1x speed, so allow a little slack
        # rather than dropping every other frame to rounding.
        return now - self._last_publish >= 0.8 / max(1, config.STREAM_FPS)

    def _pace(self, k: int):
        speed = 1 if self.manual_mode else self.speed
        if speed <= 0:
            return
        self._target = getattr(self, '_target', time.perf_counter()) + k / 60.0 / speed
        now = time.perf_counter()
        if self._target - now > 1.0 or now - self._target > 1.0:
            self._target = now
        elif self._target > now:
            time.sleep(self._target - now)

    def _frame_png(self) -> bytes:
        """The picture the stream shows now, as a PNG."""
        raise NotImplementedError

    def _publish_frame(self):
        png = self._frame_png()
        with self.frame_cond:
            self.frame_image = png
            self.frame_seq += 1
            self.frame_cond.notify_all()

    # ---------------- checkpoints ----------------
    def _before_save(self):
        """Get the emulator ready for its save state to be taken."""

    def _state_bytes(self) -> bytes:
        self._before_save()
        buf = io.BytesIO()
        self.pb.save_state(buf)
        return buf.getvalue()

    def _manifest_fields(self) -> dict:
        """The fields this generation's checkpoint manifest adds."""
        return {}

    def _manifest(self):
        return checkpoint_manifest(self.policy, rom_sha1=self.rom_sha1, frame=self.frame, play_clock=self.play_clock,
                                   store=self.store, legendary_recovery=self.legendary_recovery,
                                   **self._manifest_fields())

    def _write_autosave(self):
        """Write the autosave of this moment, start its trace segment and prune what the store keeps.
        Each generation's ``_autosave`` decides first whether this moment may be saved."""
        # The state comes before the manifest, since Gen II's _before_save rebases the clock its manifest reads.
        state, manifest = self._state_bytes(), self._manifest()
        path = self.store.write_checkpoint(state, manifest)
        tracer = getattr(self, 'tracer', None)
        if tracer is not None:
            tracer.begin(path.stem, state, manifest, kept=path, pin=trace.pin_state(self.policy))
        # The first save after an achievement is the last one known to be from before any stall.
        capture.keep_before(self, path, self.snapshot)
        self.store.prune_autosaves(config.KEEP_AUTOSAVES)
        capture.prune_trace(self)
        self.store.prune_events(config.EVENT_RETENTION_DAYS)
        self.store.prune_attachments(config.EVENT_ATTACHMENT_KEEP)
        self.store.prune_milestone_saves(config.EVENT_MILESTONE_SAVE_KEEP)
        self.store.prune_milestone_shots(config.EVENT_MILESTONE_SHOT_KEEP)
        self.store.prune_reward_results()
        return path

    def _checkpoint_before(self, name: str):
        """Keep the game as it is now under `name` before a rewind or restart replaces it."""
        if self.store.get('trade_hold'):
            return
        try:
            # A named checkpoint, not an autosave: as the newest autosave it would undo the rewind on the next start.
            self.store.write_checkpoint(self._state_bytes(), self._manifest(), name)
        except Exception:
            log.exception('cannot keep the save from before %s', name)

    def _behind_barrier(self, metadata):
        """Whether a checkpoint predates the latest completed trade or custom reward.

        Loading one would undo that trade or reward, so it is never a place to go back to.
        """
        for key, field in BARRIERS:
            barrier = self.store.get(key)
            if barrier and (metadata or {}).get(field) != barrier:
                return True
        return False

    def _reload_saves(self, since_frame, league, why):
        """The saves a reload may go back to, and the one it tries first.

        Returns ``(all_saves, saves, target, entry)``: every autosave, the ones after the latest
        trade and reward barriers, the save picked by the frame the trouble started on
        (reload.reload_target), and the League entry save when the attempt restarts from it, else None.
        A save from before a barrier is refused on load. Choosing it anyway spent a reload on an
        error and fell back to whatever came next.
        """
        all_saves = self.store.autosaves()
        saves = [path for path in all_saves if not self._behind_barrier(self.store.checkpoint_metadata(path))]
        target = reload_target(self.store, saves, since_frame)
        entry = None
        if league:
            # A save part way through the League keeps the PP already spent and can already be
            # lost, so going back a little replays the same battle. Restart the attempt instead.
            entry = self.store.state_path(LEAGUE_CHECKPOINT)
            if entry and not self._behind_barrier(self.store.checkpoint_metadata(entry)):
                log.warning('%s inside the League, restarting the attempt', why)
                target, saves = entry, [entry] + saves
            else:
                entry = None
        return all_saves, saves, target, entry

    # ---------------- the journal ----------------
    def _event(self, event, snapshot):
        """Journal one event: the generation takes its screenshot and passes it to ``_journal``."""

    def _note_achievement(self, event, eid):
        """Keep the entry as the latest achievement when this generation counts its kind as one."""

    def _journal(self, event, snapshot, shot, state=None, push=True) -> int:
        """Write one journal entry with its screenshot, and its save state when given, then push it
        unless ``push`` is False. Returns the entry's id."""
        eid = self.store.add_event(event, snapshot, shot, state)
        if state:
            # Rewinding needs the cartridge identity and the Gen II clock lock in the manifest. The save is
            # compressed like the one add_event wrote, about 13 KB instead of 200 KB.
            self.store.write_checkpoint(state, self._manifest(), name=f'event-{eid}.state', compress=True)
        self._note_achievement(event, eid)
        if push:
            self._push(eid, event, shot)
        return eid

    def _push(self, eid, event, shot):
        if event.notable and self.ntfy and self.ntfy.wants(event):
            self.ntfy.send(event.title, event.body, tags=event.tags if self.PUSH_TAGS else '', priority=event.priority,
                           image=shot, click=f'{config.PUBLIC_URL}/events/{eid}', event_type=event.type)

    def _shiny_reason(self, snapshot):
        """Why the wild shiny in this battle cannot be caught, or None when it can."""

    def _species_name(self, species):
        """The species' name, or None when the game data has none."""

    def _report_missed_shiny(self, snapshot):
        """Say once per battle why a wild shiny cannot be caught. The policy runs from it as usual.

        Balls cannot be bought and storage cannot be freed in battle, so pausing would only look like a
        stall. The supply and storage reserves are what keep a shiny catchable.
        """
        if not snapshot.enemy_shiny or snapshot.in_battle != 1:
            self._shiny_reported = False
            return False
        why = self._shiny_reason(snapshot)
        if not why or getattr(self, '_shiny_reported', False):
            return bool(why)
        self._shiny_reported = True
        species = self._species_name(snapshot.enemy_species) or 'Pokémon'
        self._event(Event('shiny_missed', f'Shiny {species} could not be caught: {why}',
                          f'A shiny {species} appeared with {why}, so the adventure ran from it. '
                          'The supply and storage reserves should prevent this.', priority=LOW, tags='star'), snapshot)
        return True

    # ---------------- guards ----------------
    def _check_stall(self, now=None):
        """Report a run that is healthy and moving but has achieved nothing for hours of game time."""
        snapshot = self.snapshot
        if snapshot is None or not snapshot.valid or not snapshot.started:
            return
        now = time.time() if now is None else now
        stall, frames = getattr(self, 'stall', None), self.play_clock.frames
        quiet = stall.check(frames, now) if stall else None
        if stall and stall.capture_due(frames):
            # Kept as soon as game time says it is a stall. The alert waits for real time as well.
            capture.keep(self, 'quiet', f'no progress for {stall.game_minutes(frames)} game minutes', now)
        if quiet is None:
            return
        details = self.policy.details() if hasattr(self.policy, 'details') else {}
        # Red, Blue and Yellow name the objective by its title, Gold, Silver and Crystal by its label.
        objective = details.get('objective') or {}
        objective = objective.get('title') or objective.get('label') or 'no objective'
        hours = quiet[0] / 60
        log.warning('no progress for %.1f game hours at %s: %s', hours, snapshot.map_name, objective)
        self._event(Event('stall', f'Stuck? {hours:.0f} game hours without progress',
                          f'Objective: {objective}. On {snapshot.map_name} after {quiet[1]} real minutes '
                          f'and {details.get("recoveries", 0)} recoveries.{self.STALL_NOTE}',
                          priority=HIGH, tags='warning'), snapshot)

    # ---------------- commands ----------------
    def held_back(self, name):
        """Why the game drops this command now, or None when it runs it."""
        return None

    def _side_command(self, name, arg) -> bool:
        """Run a command only this generation has. True when it was one."""
        return False

    def _take_control(self, name):
        """Hand the game to a person: what the policy drops before manual presses."""

    def _resume(self):
        """Give the game back to the policy."""

    def _flush_before_restart(self):
        """Write what the trackers hold before a restart empties them."""

    def _handle_command(self, name, arg) -> bool:
        if name == 'runtime_call':
            function, done, response = arg
            try:
                response['result'] = function()
            except Exception as error:
                response['error'] = error
            finally:
                done.set()
            return True
        if self._side_command(name, arg) or self.held_back(name):
            return True
        if name == 'stop':
            return False
        if name == 'pause':
            self.paused = True
            self.manual_mode = False
        elif name in ('take_control', 'press'):
            if name == 'take_control':
                # A new holder of the control lease never inherits presses someone else queued.
                while not self.manual.empty():
                    self.manual.get_nowait()
            self._take_control(name)
            self.manual_mode = True
            self.paused = True
            if name == 'press' and arg in BUTTONS:
                try:
                    self.manual.put_nowait(Action(arg, *MANUAL_PRESS))
                except queue.Full:
                    pass
        elif name == 'resume':
            self.paused = False
            self.manual_mode = False
            self._resume()
        elif name == 'speed':
            self.speed = max(0.0, min(float(arg), MAX_SPEED))
        elif name == 'save':
            self._autosave()
        elif name == 'load_state':
            path = self.store.state_path(arg)
            if path:
                # Undoing a rewind loads before-load itself, so it is held while the checkpoint replaces it.
                with self.store.held(path, BEFORE_LOAD_CHECKPOINT) as source:
                    self._checkpoint_before(BEFORE_LOAD_CHECKPOINT)
                    try:
                        with trace.reason(self, 'rewind'):
                            self._load_state_file(source)
                    except (ValueError, OSError, EOFError) as error:
                        # A refused rewind (a barrier, another cartridge, a damaged file) never ends the adventure.
                        log.warning('Rewind to %s refused: %s', path.name, error)
                    else:
                        log.info('loaded %s', path.name)
        elif name == 'restart':
            log.warning('restarting run from power-on')
            # The restart removes every autosave, so the game from before it stays as a named checkpoint.
            self._checkpoint_before(BEFORE_RESTART_CHECKPOINT)
            self._flush_before_restart()
            restart(self, self.generation, self._new_game(), self._start_new_game)
        return True
