"""Headless PyBoy loop: policy-driven input, save states, RAM diff -> events, frame publishing."""
from __future__ import annotations

import hashlib
import io
import logging
import queue
import threading
from importlib.metadata import version
import time
from pathlib import Path

from PIL import Image
from pyboy import PyBoy

from . import __version__, config
from .events import RunMemory, diff
from .policies import make_policy
from .policies.base import BUTTONS, Action, PolicyContext
from .ram import Snapshot, read_snapshot
from .screen import W_OPTIONS

log = logging.getLogger("pokesim.emu")

SHOT_SCALE = 4
STREAM_SCALE = 3
SNAPSHOT_EVERY = 30       # frames
CHUNK = 4                 # frames per render / pacing step


class Emulator:
    def __init__(self, store, ntfy=None):
        self.store = store
        self.ntfy = ntfy
        self.rom = Path(config.ROM_PATH)
        self.speed = config.SPEED
        self.paused = False
        self.manual_mode = False
        self.policy = make_policy(config.POLICY, config.SEED)
        self.lock = threading.Lock()
        self.frame_cond = threading.Condition()
        self.frame_jpeg: bytes = b""
        self.frame_seq = 0
        self.frame = 0
        self.snapshot: Snapshot | None = None
        self.prev_snapshot: Snapshot | None = None
        self.mem = RunMemory.from_dict(store.get("run_memory", {}))
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
        if hasattr(self.policy, "collection"):
            self.policy.collection.version = "blue" if "Blue" in self.rom_note else "red"
        if hasattr(self.policy, "nav"):
            self.policy.nav.use_world = not self.rom_note.startswith("unverified")
        self.input_epoch = 0
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
        pb = PyBoy(str(self.rom), window="null", sound_emulated=False)
        pb.set_emulation_speed(0)
        return pb

    def start(self):
        saves = self.store.autosaves()
        if saves:
            self._restore_first_valid(reversed(saves))
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

    def press(self, button: str):
        if button in BUTTONS:
            self.command("press", button)

    def status(self) -> dict:
        snap = self.snapshot
        return {
            "version": __version__, "viewer_only": config.VIEWER_ONLY,
            "health": self.health(),
            "paused": self.paused, "speed": self.speed, "policy": self.policy.describe(),
            "manual_mode": self.manual_mode, "help_request": None,
            "frame": self.frame, "uptime": int(time.time() - self.started_at),
            "stuck_seconds": int(time.time() - self.stuck_since), "rom": self.rom_note,
            "game": snap.to_dict() if snap else None,
            "areas_discovered": len(self.mem.seen_maps), "reloads": self.reloads,
            "glitched": bool(self.invalid_since),
            "strategy": self.policy.details(),
        }

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
        if metadata:
            if metadata.get("rom_sha1") != self.rom_sha1:
                raise ValueError("Checkpoint was created with a different ROM")
            if metadata.get("pyboy_version") != version("pyboy"):
                raise ValueError("Checkpoint requires a different PyBoy version")
            if metadata.get("policy") != config.POLICY:
                raise ValueError("Checkpoint requires a different policy")
        with open(path, "rb") as f:
            self.pb.load_state(f)
        if metadata:
            self.policy.load_state_dict(metadata["policy_state"])
            self.mem = RunMemory.from_dict(metadata["run_memory"])
            self.frame = metadata.get("frame", self.frame)
        self.prev_snapshot = None
        self.pending = []
        self.stuck_since = time.time()
        self.policy.on_restore()
        self.input_epoch += 1
        self.snapshot = read_snapshot(self.pb.memory, self.frame)

    def _state_bytes(self) -> bytes:
        buf = io.BytesIO()
        self.pb.save_state(buf)
        return buf.getvalue()

    def _image(self) -> Image.Image:
        return self.pb.screen.image.convert("RGB")

    def _shot_png(self) -> bytes:
        img = self._image()
        img = img.resize((img.width * SHOT_SCALE, img.height * SHOT_SCALE), Image.NEAREST)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue()

    def _publish_frame(self):
        img = self._image()
        img = img.resize((img.width * STREAM_SCALE, img.height * STREAM_SCALE), Image.NEAREST)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        with self.frame_cond:
            self.frame_jpeg = buf.getvalue()
            self.frame_seq += 1
            self.frame_cond.notify_all()

    def _tick(self, n: int):
        """Advance n frames, rendering/pacing every CHUNK frames and snapshotting every SNAPSHOT_EVERY."""
        while n > 0 and not self.stopping:
            k = min(CHUNK, n)
            self.pb.tick(k, render=True)
            self.frame += k
            n -= k
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
        snap = read_snapshot(self.pb.memory, self.frame)
        if snap.started:
            self._enforce_options()
        new = diff(self.prev_snapshot, snap, self.mem)
        self.prev_snapshot = snap
        # confirm last round's tentative events against this snapshot, then hold this round's tentative ones
        events = [ev for ev in self.pending if ev.still(snap)]
        dropped = len(self.pending) - len(events)
        if dropped:
            log.info("dropped %d transient event(s)", dropped)
        self.pending = [ev for ev in new if ev.still is not None]
        events += [ev for ev in new if ev.still is None]
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

    def _handle_events(self, events, snap):
        png = self._shot_png()
        state = None
        for ev in events:
            if ev.notable and state is None:
                state = self._state_bytes()
            eid = self.store.add_event(ev, snap, png, state if ev.notable else None)
            log.info("event #%d %s p%d: %s", eid, ev.type, ev.priority, ev.title)
            if ev.notable and self.ntfy and self.ntfy.wants(ev):
                self.ntfy.send(ev.title, ev.body, tags=ev.tags, priority=ev.priority, image=png,
                               click=f"{config.PUBLIC_URL}/events/{eid}")

    def _enforce_options(self):
        """Keep text speed FAST (random menu presses can set it to SLOW) and optionally animations off."""
        want = self.pb.memory[W_OPTIONS]
        if config.FAST_TEXT:
            want = (want & ~0x07) | 0x01
        if not config.BATTLE_ANIMATIONS:
            want |= 0x80
        if want != self.pb.memory[W_OPTIONS]:
            self.pb.memory[W_OPTIONS] = want

    def _autosave(self):
        snap = self.snapshot
        if snap is not None and not snap.valid:
            log.warning("skipping autosave: game state looks glitched")
            return
        self.store.write_checkpoint(self._state_bytes(), {
            "app_version": __version__, "pyboy_version": version("pyboy"),
            "rom_sha1": self.rom_sha1, "policy": config.POLICY,
            "policy_state": self.policy.state_dict(), "run_memory": self.mem.to_dict(),
            "frame": self.frame,
        })
        self.store.prune_autosaves(config.KEEP_AUTOSAVES)
        self.store.prune_events(config.EVENT_RETENTION_DAYS)
        self.store.set("policy_state", self.policy.state_dict())

    def _unstick(self, since: float, why: str):
        """Go back to an autosave from before the trouble started (or power-cycle if there is none)."""
        saves = self.store.autosaves()
        older = [p for p in saves if p.stat().st_mtime < since - 30]
        target = older[-1] if older else (saves[0] if saves else None)
        if target:
            log.warning("%s for %ds, reloading %s", why, time.time() - since, target.name)
            candidates = [target] + [p for p in reversed(saves) if p != target]
            self._restore_first_valid(candidates)
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
            self._unstick(self.stuck_since, "stuck")
        elif self.battle_since and now - self.battle_since > config.BATTLE_TIMEOUT_SECONDS:
            self._unstick(self.battle_since, "battle never ended")

    def _handle_command(self, name, arg) -> bool:
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
            self.policy.on_restore()
            self.stuck_since = self.last_reload = time.time()
            self.battle_since = self.invalid_since = None
            while not self.manual.empty():
                self.manual.get_nowait()
        elif name == "exploration":
            if hasattr(self.policy, "exploration"):
                self.policy.exploration = max(0.0, min(float(arg), 0.3))
        elif name == 'adventure_pace':
            if hasattr(self.policy,'collection') and arg in ('focused','balanced','thorough'):
                self.policy.collection.pace = arg
                self.policy.collection.project = None
                self.policy.collection.cooldown = 0
                self.store.set('policy_state',self.policy.state_dict())
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
            for p in self.store.states.glob("auto-*.state"):
                p.unlink()
                p.with_suffix(".json").unlink(missing_ok=True)
            self.mem = RunMemory()
            self.store.set("run_memory", self.mem.to_dict())
            self.policy.reset()
            self.store.set("policy_state", {})
            self.pb = self._boot()
            self.prev_snapshot = None
            self.stuck_since = time.time()
            self.pending = []
            self.input_epoch += 1
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
                    pending = list(self.policy.step(ctx)) or [Action(None, 0, 12)]
                act = pending.pop(0)
                nav = getattr(self.policy, "nav", None) if self.manual_mode else None
                if nav and act.button in ("up", "down", "left", "right") and not self.pb.memory[0xCFC5]:
                    before = read_snapshot(self.pb.memory, self.frame)
                    if not before.in_battle and not before.textbox and not before.start_menu:
                        nav.issued((before.map, before.x, before.y), act.button, self.frame)
                if act.button is not None:
                    self.pb.button_press(act.button)
                self._tick(act.hold)
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
                if not self.manual_mode:
                    self._check_guards()
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
        finally:
            self.pb.stop(save=False)
