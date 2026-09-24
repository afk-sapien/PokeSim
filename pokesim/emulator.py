"""Headless PyBoy loop: policy-driven input, save states, RAM diff -> events, frame publishing."""
from __future__ import annotations

import hashlib
import io
import logging
import queue
import secrets
import threading
from importlib.metadata import version
import time
from pathlib import Path

from PIL import Image
from pyboy import PyBoy

from . import __version__, config
from .build_info import build_info
from .checkpoints import open_state
from .events import HIGH, Event, RunMemory, diff
from . import rewards
from .legendary import LegendaryRecovery
from .play_clock import PlayClock
from .policies import make_policy
from .policies.base import BUTTONS, Action, PolicyContext
from .ram import Snapshot, read_snapshot
from .screen import W_OPTIONS
from .stalls import PROGRESS_EVENTS, StallWatch, advanced
from .strategy_data import MAPS

LEAGUE = {MAPS[name] for name in ('LORELEIS_ROOM', 'BRUNOS_ROOM', 'AGATHAS_ROOM', 'LANCES_ROOM', 'CHAMPIONS_ROOM', 'HALL_OF_FAME')}
LEAGUE_ENTRY = MAPS['LORELEIS_ROOM']
LEAGUE_CHECKPOINT = 'league-entry.state'
BEFORE_STALL_CHECKPOINT = 'before-stall.state'

log = logging.getLogger("pokesim.emu")

SHOT_SCALE = 4
SNAPSHOT_EVERY = 30       # frames
CHUNK = 4                 # frames per render / pacing step
WATCH_GRACE = 2.0         # seconds a frame request keeps the stream considered live
RETAKE_FRAMES = 600       # how long a journal screenshot waits for a fade or warp to end
BLANK_SHARE = 0.98        # a frame this much one colour shows nothing worth keeping


def blank_frame(image) -> bool:
    """True for a frame caught mid-fade or mid-warp: nearly every pixel one colour."""
    pixels = image.width * image.height
    colors = image.getcolors(pixels)
    return bool(colors) and max(count for count, _ in colors) >= BLANK_SHARE * pixels


class Emulator:
    # Encoding a frame costs far more than emulating one, so only encode while something is
    # actually asking for frames, and no faster than the stream can show them. Class defaults so
    # a partially built emulator still ticks.
    _watch_until = 0.0
    _last_publish = 0.0
    # Journal entries whose screenshot caught a blank frame, as (event id, event), and the
    # frame after which whatever is on screen is kept anyway.
    _retakes = ()
    _retake_until = 0

    def __init__(self, store, ntfy=None, *, isolated_ram=False):
        self.isolated_ram = isolated_ram
        self.preparation = None
        self.store = store
        self.ntfy = ntfy
        from .milestones import MilestoneTracker
        self.milestones = MilestoneTracker(store)
        self.rom = Path(config.ROM_PATH)
        self.speed = config.SPEED
        self.paused = False
        self.manual_mode = False
        self.policy = make_policy(config.POLICY, config.SEED)
        self.policy.trade_preferences = store.trade_preferences
        self.lock = threading.Lock()
        self.frame_cond = threading.Condition()
        self.frame_image: bytes = b""
        self.frame_seq = 0
        self.frame = 0
        self.play_clock = PlayClock(store.get("play_clock", {}))
        self.snapshot: Snapshot | None = None
        self.prev_snapshot: Snapshot | None = None
        self.mem = RunMemory.from_dict(store.get("run_memory", {}))
        self.legendary_recovery = LegendaryRecovery()
        achievements = store.events(limit=1, types=('badge', 'catch', 'evolve', 'obtain', 'champion', 'item', 'trainer', 'level', 'map', 'trade'))
        self.last_achievement = achievements[0] if achievements else None
        self.stall = StallWatch(config.STALL_ALERT_GAME_MINUTES, config.STALL_ALERT_REAL_MINUTES,
                                config.STALL_ALERT_REPEAT_HOURS)
        self.policy.load_state_dict(store.get("policy_state", {}))
        self.commands: queue.Queue = queue.Queue()
        self.manual: queue.Queue = queue.Queue(maxsize=2)
        self.started_at = time.time()
        self.last_activity = time.monotonic()
        self.fatal_error = None
        self.stopping = False
        self.consecutive_errors = 0
        self.stuck_since = time.time()
        self.last_pos = None
        self.last_reload = 0.0
        self.invalid_since: float | None = None
        self.battle_since: float | None = None
        self.reloads = 0
        self.pending: list = []      # events waiting for confirmation on the next snapshot
        self.rom_note = self._check_rom()
        from .catches import CatchTracker
        fresh = (not store.autosaves() and not store.events(limit=1)
                 and (isolated_ram or not Path(str(self.rom) + '.ram').exists()))
        self.catch_tracker = CatchTracker(store, self.rom_sha1, fresh=fresh)
        if hasattr(self.policy, "collection"):
            self.policy.collection.version = "blue" if "Blue" in self.rom_note else "red"
        if hasattr(self.policy, "nav"):
            self.policy.nav.use_world = not self.rom_note.startswith("unverified")
        self.input_epoch = 0
        if hasattr(self.policy, 'nav'):
            # Pay optional compilation cost during startup, before gameplay begins.
            from .policies.navigation_numba import kernel
            kernel()
        self.pb = self._boot()
        self.thread = threading.Thread(target=self._run, name="emulator", daemon=True)

    # ---------------- lifecycle ----------------
    def _check_rom(self) -> str:
        sha = hashlib.sha1(self.rom.read_bytes()).hexdigest()
        self.rom_sha1 = sha
        known = config.KNOWN_ROM_SHA1.get(sha)
        if known:
            log.info("ROM verified: %s", known)
            return known
        log.warning("ROM sha1 %s is not a known clean Red/Blue dump; RAM addresses may be off", sha)
        return f"unverified ROM (sha1 {sha[:12]})"

    def _boot(self) -> PyBoy:
        options = {}
        if getattr(self, 'isolated_ram', False):
            import io
            options['ram_file'] = io.BytesIO(bytes(32768))
        pb = PyBoy(str(self.rom), window="null", sound_emulated=False, **options)
        pb.set_emulation_speed(0)
        tracker = getattr(self, 'catch_tracker', None)
        if tracker is not None:
            tracker.attach(pb)
        return pb

    def start(self):
        saves = self.store.autosaves()
        if saves:
            self._restore_first_valid(reversed(saves))
        rewards.initialize(self.store, self.mem.championships)
        self.paused = bool(self.store.get("trade_hold"))
        if self.isolated_ram:
            from .runtime.preparation import restore
            restore(self)
        self.thread.start()

    def stop(self):
        self.stopping = True
        self.commands.put(("stop", None))
        self.thread.join(timeout=20)
        if self.thread.is_alive():
            raise RuntimeError("Emulator did not stop within 20 seconds")

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

    def press(self, button: str):
        if button in BUTTONS:
            self.command("press", button)

    def status(self) -> dict:
        snap = self.snapshot
        return {
            "version": __version__, "viewer_only": config.VIEWER_ONLY,
            "build": build_info(),
            "health": self.health(),
            "paused": self.paused, "speed": self.speed, "policy": self.policy.describe(),
            "manual_mode": self.manual_mode, "help_request": None,
            "play_clock": self.play_clock.status(),
            "frame": self.frame, "uptime": int(time.time() - self.started_at),
            "stuck_seconds": int(time.time() - self.stuck_since), "rom": self.rom_note,
            "game": snap.to_dict() if snap else None,
            "areas_discovered": len(self.mem.seen_maps), "reloads": self.reloads,
            "glitched": bool(self.invalid_since),
            "strategy": self.policy.details(),
            "progress": self.progress_status(),
            "league_rewards": rewards.status(self.store),
            "legendary_recovery": self.legendary_recovery.state_dict(),
        }

    def progress_status(self):
        achievement = getattr(self, 'last_achievement', None)
        age = max(0, int(time.time() - achievement['ts'])) if achievement else None
        mode = self.policy.details().get('action', '')
        state = 'recovering' if (self.invalid_since or time.time() - self.last_reload < 30
                                 or mode == 'finding another approach') else 'making_progress' if age is not None and age < 120 else 'exploring'
        stall, now = getattr(self, 'stall', None), time.time()
        if stall and stall.stalled(self.frame, now):
            state = 'stalled'
        return {'state': state, 'quiet_game_minutes': stall.quiet(self.frame, now)[0] if stall else 0,
                'last_achievement': {
                    'id': achievement['id'], 'title': achievement['title'], 'ts': achievement['ts'],
                    'age_seconds': age,
                } if achievement else None}

    # ---------------- internals ----------------
    def health(self) -> dict:
        alive = self.thread.is_alive()
        age = max(0, time.monotonic() - self.last_activity)
        healthy = alive and not self.fatal_error and age < 30 and not self.stopping
        return {"ok": healthy, "worker_alive": alive, "activity_age_seconds": round(age, 1),
                "error": self.fatal_error}

    def _restore_first_valid(self, paths):
        errors = []
        for path in paths:
            try:
                self._load_state_file(path)
                log.info("resumed from %s", path.name)
                return
            except Exception as error:
                errors.append(path.name)
                log.warning("cannot restore %s: %s", path.name, error)
                self.pb.stop(save=False)
                self.pb = self._boot()
        raise RuntimeError(f"No compatible autosave could be restored ({len(errors)} tried). Restore a backup or use a new data directory.")

    def _load_state_file(self, path: Path):
        metadata = self.store.checkpoint_metadata(path)
        barrier = self.store.get("trade_barrier")
        if barrier and (metadata or {}).get("trade_id") != barrier:
            raise ValueError("Checkpoint predates the latest completed trade")
        reward_barrier = self.store.get('custom-reward-barrier-v1')
        if reward_barrier and (metadata or {}).get('reward_id') != reward_barrier:
            raise ValueError('Checkpoint predates the latest custom reward')
        if metadata:
            if metadata.get("rom_sha1") != self.rom_sha1:
                raise ValueError("Checkpoint was created with a different ROM")
            if metadata.get("pyboy_version") != version("pyboy"):
                raise ValueError("Checkpoint requires a different PyBoy version")
            if metadata.get("policy") != config.POLICY:
                raise ValueError("Checkpoint requires a different policy")
        with open_state(path) as f:
            self.pb.load_state(f)
        if metadata:
            self.policy.load_state_dict(metadata["policy_state"])
            announced = getattr(self, 'mem', RunMemory()).playtime_milestones.copy()
            announced.update(self.store.get('run_memory', {}).get('playtime_milestones', []))
            self.mem = RunMemory.from_dict(metadata["run_memory"])
            with self.store.lock:
                self.mem.championships = max(self.mem.championships,
                                            rewards.championship_count(rewards.ledger(self.store.db)))
            self.mem.playtime_milestones.update(announced)
            self.store.set('run_memory', self.mem.to_dict())
            self.frame = metadata.get("frame", self.frame)
        self._reset_transient(clear_observation=True)
        self.legendary_recovery = LegendaryRecovery((metadata or {}).get('legendary_recovery'))
        self.play_clock.restore(metadata.get("play_clock") if metadata else None)
        self.snapshot = read_snapshot(self.pb.memory, self.frame)
        if self.snapshot.started:
            self.play_clock.seed(self.snapshot.playtime_seconds)

    def _reset_transient(self, *, clear_observation=False):
        """Discard queued input and recovery timers without erasing durable progress."""
        self.policy.on_restore()
        self.input_epoch = getattr(self, 'input_epoch', 0) + 1
        self.stuck_since = self.last_reload = time.time()
        self.last_pos = None
        self.invalid_since = self.battle_since = None
        manual = getattr(self, 'manual', None)
        if manual is not None:
            while not manual.empty():
                manual.get_nowait()
        if clear_observation:
            self.prev_snapshot = None
            self.pending = []

    def _state_bytes(self) -> bytes:
        buf = io.BytesIO()
        self.pb.save_state(buf)
        return buf.getvalue()

    def _image(self) -> Image.Image:
        return self.pb.screen.image.convert("RGB")

    def _shot_png(self, img=None) -> bytes:
        img = self._image() if img is None else img
        img = img.resize((img.width * SHOT_SCALE, img.height * SHOT_SCALE), Image.NEAREST)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue()

    def watch(self):
        """Note that something wants frames. Viewers call this as they poll or stream."""
        self._watch_until = time.monotonic() + WATCH_GRACE

    def current_frame(self, timeout: float = 1.0) -> bytes:
        """The latest frame, waiting for the first one if the run has only just started."""
        self.watch()
        if self.frame_image:
            return self.frame_image
        with self.frame_cond:
            self.frame_cond.wait_for(lambda: bool(self.frame_image), timeout)
            return self.frame_image

    def _due_to_publish(self, now: float) -> bool:
        if now >= self._watch_until:
            return False
        # A tick step is already about one stream interval at 1x speed, so allow a little slack
        # rather than dropping every other frame to rounding.
        return now - self._last_publish >= 0.8 / max(1, config.STREAM_FPS)

    def _publish_frame(self):
        # Native size, lossless: about 3 KB against 90 KB for an upscaled JPEG, and
        # quicker to encode. The page scales it up with crisp pixels.
        buf = io.BytesIO()
        self._image().save(buf, "PNG", compress_level=1)
        with self.frame_cond:
            self.frame_image = buf.getvalue()
            self.frame_seq += 1
            self.frame_cond.notify_all()

    def _tick(self, n: int):
        """Advance n frames, rendering/pacing every CHUNK frames and snapshotting every SNAPSHOT_EVERY."""
        while n > 0 and not self.stopping:
            k = min(CHUNK, n)
            self.pb.tick(k, render=True)
            self.frame += k
            self.play_clock.advance(k)
            n -= k
            now = time.monotonic()
            if self._due_to_publish(now):
                self._last_publish = now
                self._publish_frame()
            if self.frame // SNAPSHOT_EVERY != (self.frame - k) // SNAPSHOT_EVERY:
                self._observe()
            self._pace(k)
            self.last_activity = time.monotonic()

    def _pace(self, k: int):
        speed = 1 if self.manual_mode else self.speed
        if speed <= 0:
            return
        self._target = getattr(self, "_target", time.perf_counter()) + k / 60.0 / speed
        now = time.perf_counter()
        if self._target - now > 1.0 or now - self._target > 1.0:
            self._target = now
        elif self._target > now:
            time.sleep(self._target - now)

    def _observe(self):
        self._retake_shots()
        snap = read_snapshot(self.pb.memory, self.frame)
        if snap.started:
            self.play_clock.seed(snap.playtime_seconds)
            self._enforce_options()
        came_from = self.prev_snapshot.map if self.prev_snapshot else None
        if (self.prev_snapshot is not None and snap.valid and self.prev_snapshot.valid
                and advanced(self.prev_snapshot, snap) and getattr(self, 'stall', None)):
            # A long hunt catches plenty that the Pokédex already has, and training earns experience
            # between level milestones. Neither is a stall.
            self.stall.progress(self.frame, time.time())
        new = diff(self.prev_snapshot, snap, self.mem)
        if (snap.valid and snap.map == LEAGUE_ENTRY and came_from is not None and came_from not in LEAGUE
                and not snap.in_battle):
            # Nobody can leave the League, and no trade happens inside it, so this is the one save that
            # can undo an attempt that reaches a battle neither side can finish.
            try:
                self.store.write_checkpoint(self._state_bytes(), self._manifest(), name=LEAGUE_CHECKPOINT)
            except OSError:
                log.exception("cannot write the League entry checkpoint")
        # Party structures briefly fail validation while a PC transfer writes them.
        # Keep a recent valid event baseline across that write, while publishing the
        # actual snapshot to health and policy below. Longer invalid gaps start fresh.
        if (snap.valid or self.prev_snapshot is None
                or not 0 <= snap.frame - self.prev_snapshot.frame <= 120):
            self.prev_snapshot = snap
        # confirm last round's tentative events against this snapshot, then hold this round's tentative ones
        events = [ev for ev in self.pending if ev.still(snap)]
        dropped = len(self.pending) - len(events)
        if dropped:
            log.info("dropped %d transient event(s)", dropped)
        self.pending = [ev for ev in new if ev.still is not None]
        events += [ev for ev in new if ev.still is None]
        restored_legendary = False
        if (self.rom_sha1 in config.KNOWN_ROM_SHA1 and not self.manual_mode
                and not self.store.get('trade_hold')):
            recovery_events, restored_legendary = self.legendary_recovery.observe(snap, self.pb.memory)
            events += recovery_events
            if restored_legendary:
                snap = read_snapshot(self.pb.memory, self.frame)
                self.prev_snapshot = snap
        if hasattr(self, 'milestones'):
            self.milestones.observe(snap)
            if hasattr(self.policy, 'collection'):
                from .milestones import status as milestone_status
                self.policy.collection.milestones = milestone_status(self.store)
        with self.lock:
            self.snapshot = snap
        now = time.time()
        pos = (snap.map, snap.x, snap.y)
        if pos != self.last_pos or snap.in_battle or not snap.started:
            self.last_pos = pos
            self.stuck_since = now
        if not snap.valid:
            self.invalid_since = self.invalid_since or now
        else:
            self.invalid_since = None
        if snap.in_battle and snap.started:
            self.battle_since = self.battle_since or now
        else:
            self.battle_since = None
        if events:
            self._handle_events(events, snap)
            self.store.set("run_memory", self.mem.to_dict())
        if restored_legendary:
            self._autosave()

    def _handle_events(self, events, snap):
        if any(ev.type in ('catch', 'obtain', 'evolve', 'champion', 'trainer') for ev in events):
            rewards.observe_progress(self.store, snap)
        if any(ev.type == 'champion' for ev in events):
            rewards.earn(self.store, self.mem.championships,
                         enabled=getattr(config, 'LEAGUE_REWARDS', False))
        image = self._image()
        blank = blank_frame(image)
        png = self._shot_png(image)
        # A journal entry keeps its screenshot, not a save state. Going back to a moment is what
        # the rotating autosaves are for, and on any adventure that has completed a trade the
        # rewind is refused anyway, because every earlier checkpoint predates the trade barrier.
        for ev in events:
            eid = self.store.add_event(ev, snap, png, None)
            if ev.type in ('badge', 'catch', 'evolve', 'obtain', 'champion', 'item', 'trainer', 'level', 'map', 'trade'):
                self.last_achievement = {'id': eid, 'title': ev.title, 'ts': time.time()}
            if ev.type in PROGRESS_EVENTS:
                self.unstick_streak = 0
            if ev.type in PROGRESS_EVENTS and getattr(self, 'stall', None):
                self.stall.progress(self.frame, time.time())
            log.info("event #%d %s p%d: %s", eid, ev.type, ev.priority, ev.title)
            if blank:
                # Badges, warps and catches often land during a fade. Keep the entry now and
                # take its picture, and push it, once the screen shows something again.
                self._retakes = (*self._retakes, (eid, ev))
                self._retake_until = self.frame + RETAKE_FRAMES
            else:
                self._push(eid, ev, png)

    def _push(self, eid, ev, png):
        if ev.notable and self.ntfy and self.ntfy.wants(ev):
            self.ntfy.send(ev.title, ev.body, tags=ev.tags, priority=ev.priority, image=png,
                           click=f"{config.PUBLIC_URL}/events/{eid}")

    def _retake_shots(self):
        if not self._retakes:
            return
        image = self._image()
        blank = blank_frame(image)
        if blank and self.frame < self._retake_until:
            return
        png = self._shot_png(image)
        retakes, self._retakes = self._retakes, ()
        for eid, ev in retakes:
            if not blank:
                try:
                    self.store.replace_shot(eid, png)
                except OSError:
                    log.exception("cannot retake the screenshot for event #%d", eid)
            self._push(eid, ev, png)

    def _enforce_options(self):
        """Keep text speed FAST (random menu presses can set it to SLOW) and optionally animations off."""
        want = self.pb.memory[W_OPTIONS]
        if config.FAST_TEXT:
            want = (want & ~0x07) | 0x01
        if not config.BATTLE_ANIMATIONS:
            want |= 0x80
        if want != self.pb.memory[W_OPTIONS]:
            self.pb.memory[W_OPTIONS] = want

    def _manifest(self):
        return {
            "app_version": __version__, "pyboy_version": version("pyboy"),
            "rom_sha1": self.rom_sha1, "policy": config.POLICY,
            "policy_state": self.policy.state_dict(), "run_memory": self.mem.to_dict(),
            "frame": self.frame, "play_clock": self.play_clock.state_dict(),
            "trade_id": self.store.get("trade_barrier"),
            "reward_id": self.store.get("custom-reward-barrier-v1"),
            "legendary_recovery": self.legendary_recovery.state_dict(),
        }

    def _autosave(self, trade_prepare=False):
        if self.store.get("trade_hold") and not trade_prepare:
            return
        self.store.set("play_clock", self.play_clock.state_dict())
        snap = self.snapshot
        battle_since = getattr(self, 'battle_since', None)
        if battle_since and not trade_prepare and (time.time() - battle_since > config.BATTLE_TIMEOUT_SECONDS / 3
                                                   or getattr(self.policy, 'hopeless_battle', False)):
            # A battle this long may never end, and the only way out is a save from before it began.
            # Rotating autosaves during it would push that save out before the timeout reloads it.
            return
        if snap is not None and not snap.valid:
            log.warning("skipping autosave: game state looks glitched")
            return
        path = self.store.write_checkpoint(self._state_bytes(), self._manifest())
        stall = getattr(self, 'stall', None)
        if stall and stall.fresh and config.KEEP_STALL_BUNDLES and not (snap is not None and snap.in_battle):
            # The first save after an achievement is the last one known to be from before any stall.
            # Autosaves rotate out long before a stall is noticed, so keep it under its own name.
            try:
                self.store.keep_as(path, BEFORE_STALL_CHECKPOINT)
                stall.fresh = False
            except OSError:
                log.exception("cannot keep the save from before a stall")
        self.store.prune_autosaves(config.KEEP_AUTOSAVES)
        self.store.prune_events(config.EVENT_RETENTION_DAYS)
        self.store.set("policy_state", self.policy.state_dict())

    def _unstick(self, since: float, why: str):
        """Go back to an autosave from before the trouble started (or power-cycle if there is none)."""
        saves = self.store.autosaves()
        older = [p for p in saves if p.stat().st_mtime < since - 30]
        target = older[-1] if older else (saves[0] if saves else None)
        # A recent save inside the League can already be lost: one frozen partner left and an
        # opponent that never attacks. If going back a little did not help, restart the attempt.
        self.unstick_streak = getattr(self, 'unstick_streak', 0) + 1
        entry = self.store.state_path(LEAGUE_CHECKPOINT)
        if self.unstick_streak >= 2 and entry and self.snapshot is not None and self.snapshot.map in LEAGUE:
            log.warning("%s again with no progress, restarting the League attempt", why)
            target, saves = entry, [entry] + saves
        if target:
            log.warning("%s for %ds, reloading %s", why, time.time() - since, target.name)
            candidates = [target] + [p for p in reversed(saves) if p != target]
            self._restore_first_valid(candidates)
            # The emulator is deterministic, so the same save and the same choices would replay the
            # same trouble. Idling a random moment moves the game's random numbers along.
            self._tick(1 + secrets.randbelow(180))
        else:
            log.warning("%s and no save state to go back to; power-cycling", why)
            self.pb.stop(save=False)
            self.pb = self._boot()
            self.prev_snapshot = None
            self.policy.on_restore()
            self.input_epoch += 1
        now = time.time()
        self.stuck_since = self.last_reload = now
        self.invalid_since = self.battle_since = None
        self.reloads += 1

    def _check_guards(self):
        now = time.time()
        if now - self.last_reload < 60:
            return
        if self.invalid_since and now - self.invalid_since > 5:
            self._unstick(self.invalid_since, "game state glitched")
        elif config.STUCK_RELOAD_SECONDS and now - self.stuck_since > config.STUCK_RELOAD_SECONDS:
            recover = getattr(self.policy, 'recover_stall', None)
            if recover and self.snapshot and self.snapshot.valid and not self.snapshot.in_battle:
                recover(self.snapshot)
                self.stuck_since = now
                self.input_epoch += 1
                log.warning('stationary objective abandoned, replanning without a save reload')
            else:
                self._unstick(self.stuck_since, "stuck")
        elif self.battle_since and now - self.battle_since > config.BATTLE_TIMEOUT_SECONDS:
            self._unstick(self.battle_since, "battle never ended")
        elif self.battle_since and getattr(self.policy, 'hopeless_battle', False):
            # The player has worked out that neither side can finish, so the timeout has nothing to wait for.
            self._unstick(self.battle_since, "battle cannot end")
        self._check_stall(now)

    def _check_stall(self, now):
        """Report a run that is healthy and moving but has achieved nothing for hours of game time."""
        snap = self.snapshot
        if snap is None or not snap.valid or not snap.started:
            return
        stall = getattr(self, 'stall', None)
        quiet = stall.check(self.frame, now) if stall else None
        if quiet is None:
            return
        details = self.policy.details() if hasattr(self.policy, 'details') else {}
        objective = (details.get('objective') or {}).get('title') or 'no objective'
        hours = quiet[0] / 60
        log.warning('no progress for %.1f game hours at %s: %s', hours, snap.map_name, objective)
        if config.KEEP_STALL_BUNDLES:
            try:
                report = {'quiet_game_minutes': quiet[0], 'quiet_real_minutes': quiet[1], 'frame': self.frame,
                          'map': snap.map_name, 'position': [snap.x, snap.y], 'in_battle': bool(snap.in_battle),
                          'objective': details.get('objective'), 'action': details.get('action'),
                          'reason': details.get('reason'), 'recoveries': details.get('recoveries', 0),
                          'reloads': self.reloads, 'party': [[mon.name, mon.level, mon.hp, mon.status] for mon in snap.party]}
                folder = self.store.write_stall_bundle(self._state_bytes(), self._manifest(), report, self._shot_png(),
                                                       self.store.state_path(BEFORE_STALL_CHECKPOINT),
                                                       config.KEEP_STALL_BUNDLES)
                log.warning('kept the stall and the save from before it in %s', folder)
            except Exception:
                log.exception('cannot keep the stall bundle')
        self._handle_events([Event('stall', f'Stuck? {hours:.0f} game hours without progress',
                                   f'Objective: {objective}. On {snap.map_name} after {quiet[1]} real minutes '
                                   f'and {details.get("recoveries", 0)} recoveries. The saved moment is attached '
                                   'to this journal entry.', priority=HIGH, tags='warning')], snap)

    def set_trade_preference(self, key, state):
        done, response = threading.Event(), {}
        self.commands.put(('trade_preference', (key, state, done, response)))
        if not done.wait(15):
            raise ValueError('The preference update is still pending. Refresh before retrying.')
        if 'error' in response:
            raise ValueError(response['error'])

    def _set_trade_preference(self, key, state):
        from .trade.preferences import update
        from .web.pokedex import live_status
        snapshot = read_snapshot(self.pb.memory, self.frame)
        if not snapshot.valid or not snapshot.started:
            raise ValueError('Wait for the adventure to be ready before changing partner protection.')
        update(self.store, live_status(snapshot.to_dict()), key, state)
        self.snapshot = snapshot
        self.input_epoch += 1

    def trade(self, action, transaction):
        done, response = threading.Event(), {}
        self.commands.put(('trade', (action, transaction, done, response)))
        if not done.wait(15):
            raise ValueError('Trade command is still pending, retry the same transaction')
        if 'error' in response:
            raise ValueError(response['error'])
        return response['result']

    def _trade(self, action, transaction):
        hold = self.store.get('trade_hold')
        if hold and hold['id'] != transaction:
            raise ValueError('Another exchange holds this game')
        if action == 'prepare':
            if hold and hold.get('source'):
                return hold
            if not hold:
                s = read_snapshot(self.pb.memory, self.frame)
                if self.paused or not s.valid or not s.started or s.in_battle or s.textbox or s.start_menu:
                    raise ValueError('Waiting for an unpaused overworld safe point')
                self.paused = True
                self.manual_mode = False
                self.snapshot = s
                hold = {'id': transaction, 'source': None, 'phase': 'preparing'}
                self.store.set('trade_hold', hold)
            self._autosave(trade_prepare=True)
            hold.update(source=self.store.latest_state().name, phase='prepared')
            self.store.set('trade_hold', hold)
            return hold
        if not hold:
            if action in ('load', 'release') and self.store.get('trade_barrier') != transaction:
                raise ValueError('This exchange has not committed')
            return {'id': transaction, 'phase': 'released'}
        if action == 'load':
            if hold['phase'] != 'loaded':
                path = self.store.state_path(f'auto-v1-trade-{transaction}.state')
                if not path or self.store.get('trade_barrier') != transaction:
                    raise ValueError('The committed checkpoint is not ready')
                self._load_state_file(path)
                events = self.store.events(limit=1, types=('trade', 'obtain'))
                if events:
                    self.last_achievement = events[0]
                hold['phase'] = 'loaded'
                self.store.set('trade_hold', hold)
            return hold
        if action == 'release':
            if hold['phase'] != 'loaded':
                raise ValueError('The exchanged inventory has not loaded')
        elif action == 'abort':
            if self.store.get('trade_barrier') == transaction:
                raise ValueError('A committed exchange cannot be cancelled')
            source = self.store.state_path(hold['source']) if hold.get('source') else self.store.latest_state()
            if source:
                self._load_state_file(source)
        else:
            raise ValueError('Unknown trade action')
        self.store.set('trade_hold', None)
        self.paused = False
        self.policy.on_restore()
        self.stuck_since = time.time()
        return {'id': transaction, 'phase': 'released'}

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
        if name == 'trade_preference':
            key, state, done, response = arg
            try:
                self._set_trade_preference(key, state)
            except Exception as error:
                response['error'] = str(error)
            finally:
                done.set()
            return True
        if name == 'trade':
            action, transaction, done, response = arg
            try:
                response['result'] = self._trade(action, transaction)
            except Exception as error:
                response['error'] = str(error)
            finally:
                done.set()
            return True
        if getattr(self, 'store', None):
            preparation = self.store.get('interaction_preparation') or {}
            if preparation.get('phase') in {'travelling', 'storage', 'rendezvous'}:
                if name == 'pause' and getattr(self, 'preparation', None):
                    from .runtime.preparation import cancel
                    cancel(self, preparation['id'])
                elif name not in ('stop', 'speed', 'pause'):
                    return True
        if getattr(self, 'store', None) and self.store.get('trade_hold') and name not in ('stop', 'speed', 'pause'):
            return True
        if name == "stop":
            return False
        if name == "pause":
            self.paused = True
            self.manual_mode = False
        elif name in ("take_control", "press"):
            if not self.manual_mode:
                self.policy.on_restore()
            self.manual_mode = True
            self.paused = True
            if name == "press" and arg in BUTTONS:
                try:
                    self.manual.put_nowait(Action(arg, 6, 2))
                except queue.Full:
                    pass
        elif name == "resume":
            self.paused = False
            self.manual_mode = False
            self._reset_transient()
        elif name == "speed":
            self.speed = max(0.0, min(float(arg), 16.0))
        elif name == "save":
            self._autosave()
        elif name == "load_state":
            p = self.store.state_path(arg)
            if p:
                self._load_state_file(p)
                log.info("loaded %s", p.name)
        elif name == "restart":
            log.warning("restarting run from power-on")
            self.pb.stop(save=False)
            if getattr(self, 'catch_tracker', None) is not None:
                self.catch_tracker.reset()
            for p in self.store.states.glob("auto-*.state"):
                p.unlink()
                p.with_suffix(".json").unlink(missing_ok=True)
            self.mem = RunMemory()
            self.legendary_recovery = LegendaryRecovery()
            self.last_achievement = None
            self.store.set("trade_barrier", None)
            self.store.clear_trade_preferences()
            self.store.set("custom-reward-barrier-v1", None)
            self.store.set("custom-reward-pending-v1", None)
            if hasattr(self, 'milestones'):
                self.milestones.reset()
            self.store.set(rewards.KEY, None)
            self.play_clock = PlayClock()
            self.store.set("play_clock", self.play_clock.state_dict())
            self.snapshot = None
            self.store.set("run_memory", self.mem.to_dict())
            self.policy.reset()
            self.store.set("policy_state", {})
            self.pb = self._boot()
            self.frame = 0
            self.paused = self.manual_mode = False
            self._reset_transient(clear_observation=True)
        return True

    def _run(self):
        pending: list[Action] = []
        next_autosave = time.time() + config.AUTOSAVE_SECONDS
        running = True
        self.consecutive_errors = 0
        input_epoch = self.input_epoch
        while running and not getattr(self, "stopping", False):
            try:
                while running and not self.commands.empty():
                    name, arg = self.commands.get_nowait()
                    running = self._handle_command(name, arg)
                if not running:
                    break
                if input_epoch != self.input_epoch:
                    pending.clear()
                    input_epoch = self.input_epoch
                    while not self.manual.empty():
                        self.manual.get_nowait()
                if not self.manual.empty():
                    pending = [self.manual.get_nowait()]
                elif self.manual_mode:
                    pending = [Action(None, 0, 4)]
                elif self.paused:
                    self.last_activity = time.monotonic()
                    self.consecutive_errors = 0
                    pending.clear()
                    time.sleep(0.1)
                    continue
                if not pending:
                    snap = read_snapshot(self.pb.memory, self.frame)
                    ctx = PolicyContext(snap, time.time() - self.stuck_since, time.time(), self.pb.memory)
                    preparation = getattr(self, 'preparation', None)
                    pending = list(preparation.step(ctx) if preparation else self.policy.step(ctx))
                    if self.paused:
                        continue
                    pending = pending or [Action(None, 0, 12)]
                act = pending.pop(0)
                nav = getattr(self.policy, "nav", None) if self.manual_mode else None
                if nav and act.button in ("up", "down", "left", "right") and not self.pb.memory[0xCFC5]:
                    before = read_snapshot(self.pb.memory, self.frame)
                    if not before.in_battle and not before.textbox and not before.start_menu:
                        nav.issued((before.map, before.x, before.y), act.button, self.frame)
                if act.button is not None:
                    self.pb.button_press(act.button)
                try:
                    self._tick(act.hold)
                finally:
                    if act.button is not None:
                        self.pb.button_release(act.button)
                self._tick(act.gap)
                if nav:
                    after = read_snapshot(self.pb.memory, self.frame)
                    nav.observe((after.map, after.x, after.y), self.frame, bool(self.pb.memory[0xCFC5]),
                                interrupted=bool(after.in_battle or after.textbox or after.start_menu))
                now = time.time()
                if now >= next_autosave:
                    self._autosave()
                    next_autosave = now + config.AUTOSAVE_SECONDS
                if not self.manual_mode and not getattr(self, 'preparation', None):
                    self._check_guards()
                if getattr(self, 'isolated_ram', False) and now >= getattr(self, '_next_reward', 0):
                    from .runtime.reward_delivery import deliver
                    self._next_reward = now + 60
                    delivered = deliver(self, league_rewards=getattr(config, 'LEAGUE_REWARDS', False),
                                        mew_event=getattr(config, 'MEW_EVENT', False))
                    # A battle or menu should not postpone a pending gift for another minute.
                    self._next_reward = now + (60 if delivered else 1)
                self.last_activity = time.monotonic()
                self.consecutive_errors = 0
            except Exception:  # noqa: BLE001
                log.exception("emulator loop error")
                self.consecutive_errors += 1
                if self.consecutive_errors >= 10:
                    self.fatal_error = "Emulator stopped after 10 consecutive errors. See server logs."
                    break
                time.sleep(1)
        try:
            if not getattr(self, "fatal_error", None):
                self._autosave()
        except Exception:
            self.fatal_error = 'The final save failed. Check disk space and the logs before relaunching.'
            log.exception('Final emulator save failed')
        finally:
            self.pb.stop(save=False)
