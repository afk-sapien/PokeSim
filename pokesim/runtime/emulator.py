"""The half of the application's emulator that Red, Blue, Yellow, Gold, Silver and Crystal share.

``pokesim/emulator.py`` (Gen I) and ``pokesim/gen2/emulator.py`` (Gen II) subclass ``EmulatorBase``. The
base runs the command queue, the control lease, manual presses, the step with its pacing and frame
publishing, the named checkpoints, the trade and reward barriers, and the choice of save a reload goes
back to. Each generation keeps what reads its own cartridge: boot, load, observation, the journal, the
guards, when an autosave is allowed, the run loop and the status page. Where the two differ in one step,
the base calls a hook below that the generation fills. docs/design/one-bot.md, item 2.
"""
from __future__ import annotations

import io
import logging
import queue
import threading
import time

from .. import config
from ..planning import pin
from . import trace
from .manifest import checkpoint_manifest
from .policy import BUTTONS, Action
from .reload import reload_target
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
            audible = self.audio.active()
            self._sync_audio(audible)
            k = min(1 if audible else CHUNK, n)
            observing = (self.frame + k) // SNAPSHOT_EVERY != self.frame // SNAPSHOT_EVERY
            publishing = self._due_to_publish(time.monotonic())
            # Policy reads the cartridge tilemap, not the rendered image. Keep
            # observation frames fresh for journal screenshots and fade retakes.
            self.pb.tick(k, render=observing or publishing, sound=audible)
            if audible:
                self.audio.publish(self.pb.sound.raw_buffer[:self.pb.sound.raw_buffer_head])
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
