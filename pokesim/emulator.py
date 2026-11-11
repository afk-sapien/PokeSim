"""Headless CoreEmulator loop: policy-driven input, save states, RAM diff -> events, frame publishing."""
from __future__ import annotations

import dataclasses
import hashlib
import io
import logging
import queue
import threading
from pokecore.emulator_state import validate_runtime
import time
from pathlib import Path

from PIL import Image
from pokecore.emulator import Emulator as CoreEmulator

from .yellow import YELLOW_SHA1, open_emulator

from . import __version__, config
from .audio import AudioFeed, enable_checkpoint_sound
from .build_info import build_info
from .checkpoints import open_state
from .events import HIGH, LOW, Event, RunMemory, diff
from . import progress_events, rewards, seeds, stall_truth
from .legendary import LegendaryRecovery
from .loop_errors import loop_failed
from .play_clock import PlayClock
from .palettes import PALETTES, recolor, validate_palette
from .planning import pin
from .policies import make_policy
from .policies.base import BUTTONS, Action
from .ram import SPECIES_NAMES, Snapshot, read_snapshot, repair_party_nicknames
from .runtime.game_loop import GameLoop, Gen1, gen1_options
from .runtime import capture, trace
from .runtime.manifest import checkpoint_manifest
from .runtime.reload import FRAMES_PER_SECOND, reload_target
from .runtime.restart import restart
from .runtime.supervision import CANNOT_END, GIVE_UP, HOLD, Supervisor
from .runtime.supervision import report as stuck_report
from .screen import W_OPTIONS
from .stalls import BEFORE_STALL_CHECKPOINT, PROGRESS_EVENTS, LoopGuard, StallWatch, advanced  # noqa: F401
from .strategy_data import MAPS

LEAGUE = {MAPS[name] for name in ('LORELEIS_ROOM', 'BRUNOS_ROOM', 'AGATHAS_ROOM', 'LANCES_ROOM', 'CHAMPIONS_ROOM', 'HALL_OF_FAME')}
LEAGUE_ENTRY = MAPS['LORELEIS_ROOM']
LEAGUE_CHECKPOINT = 'league-entry.state'
# Kept by name, so a wrong rewind or restart can be undone from the saves list.
BEFORE_LOAD_CHECKPOINT = 'before-load.state'
BEFORE_RESTART_CHECKPOINT = 'before-restart.state'
# The playtime hours already announced. A reload keeps them, so a rewound game does not announce an hour twice.
PLAYTIME_MILESTONES = 'playtime-milestones-v1'
# The phases of an exchange's preparation that hold back every command but stop, speed and pause.
PREPARING = {'travelling', 'storage', 'rendezvous'}
# Game frames, as in Generation II: no guard runs for a minute after a reload, and a glitched state
# gets 5 seconds, or a minute in a Pokémon Center while the healing trip finishes.
RELOAD_QUIET_FRAMES = 60 * FRAMES_PER_SECOND
INVALID_GRACE_FRAMES = 5 * FRAMES_PER_SECOND
CENTER_GRACE_FRAMES = 60 * FRAMES_PER_SECOND

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
    _audio_enabled = False
    # Encoding a frame costs far more than emulating one, so only encode while something is
    # actually asking for frames, and no faster than the stream can show them. Class defaults so
    # a partially built emulator still ticks.
    _watch_until = 0.0
    _last_publish = 0.0
    # Journal entries whose screenshot caught a blank frame, as (event id, event), and the
    # frame after which whatever is on screen is kept anyway.
    _retakes = ()
    _retake_until = 0
    # The emulator frame and the guard clocks that count it, also class defaults for a partially
    # built emulator. No reload has happened yet, so its quiet spell is long past.
    frame = 0
    stuck_frame = 0
    last_reload_frame = -10 ** 9
    invalid_frame = None
    battle_frame = None

    def __init__(self, store, ntfy=None, *, isolated_ram=False):
        self.isolated_ram = isolated_ram
        self.preparation = None
        self.store = store
        self.ntfy = ntfy
        from .milestones import MilestoneTracker
        self.milestones = MilestoneTracker(store)
        from .statistics import StatisticsTracker
        self.statistics = StatisticsTracker(store)
        from .goal_time import GoalTime
        self.goal_time = GoalTime(store)
        self.rom = Path(config.ROM_PATH)
        self.speed = config.SPEED
        self.palette = validate_palette(getattr(config, 'PALETTE', 'original'))
        self.paused = False
        self.frozen = False
        self.manual_mode = False
        self.adventure_seed = seeds.adventure_seed(store)
        self.policy = make_policy(config.POLICY, self.adventure_seed)
        store.attach(self.policy, 1)
        self.lock = threading.Lock()
        self.frame_cond = threading.Condition()
        self.frame_image: bytes = b""
        self.frame_seq = 0
        self.audio = AudioFeed()
        self.frame = 0
        self.executed_frames = 0
        self.play_clock = PlayClock(store.get("play_clock", {}))
        # A reset replaces the clock, so the store asks for the current one each time.
        store.clock = lambda: self.play_clock.frames
        self.goal_watch = store.goal_watch = self.policy.goal_watch = progress_events.GoalWatch()
        self.snapshot: Snapshot | None = None
        self.prev_snapshot: Snapshot | None = None
        # The newest autosave's manifest replaces this, and the policy's state, when start() loads it.
        self.mem = RunMemory()
        self.legendary_recovery = LegendaryRecovery()
        achievements = store.events(limit=1, types=('badge', 'catch', 'evolve', 'obtain', 'champion', 'item', 'trainer', 'level', 'map', 'trade'))
        self.last_achievement = achievements[0] if achievements else None
        self.stall = StallWatch(config.STALL_ALERT_GAME_MINUTES, config.STALL_ALERT_REAL_MINUTES,
                                config.STALL_ALERT_REPEAT_HOURS)
        self.loop_guard = LoopGuard(lambda: self.play_clock.frames)
        self.supervisor = Supervisor(store)
        self.commands: queue.Queue = queue.Queue()
        self.manual: queue.Queue = queue.Queue(maxsize=2)
        self.started_at = time.time()
        self.last_activity = time.monotonic()
        self.fatal_error = None
        self.stopping = False
        self.consecutive_errors = 0
        # The guards count emulator frames, which a reload rewinds with the save, so they fire on the
        # same frames in a replay at any pace. ``last_reload`` is wall time for the status page only.
        self.stuck_frame = 0
        self.last_pos = None
        self.last_reload = 0.0
        self.last_reload_frame = -10 ** 9
        self.invalid_frame: int | None = None
        self.battle_frame: int | None = None
        self.reloads = 0
        self.pending: list = []      # events waiting for confirmation on the next snapshot
        self.rom_note = self._check_rom()
        if isolated_ram and config.POLICY == 'strategic':
            from .tm_shop import cartridge_data
            self.policy.tm_moves, self.policy.tm_compatible = cartridge_data(self.rom.read_bytes())
        from .catches import CatchTracker
        fresh = (not store.autosaves() and not store.events(limit=1)
                 and (isolated_ram or not Path(str(self.rom) + '.ram').exists()))
        self.catch_tracker = CatchTracker(store, self.rom_sha1, fresh=fresh)
        from .shiny import ShinyTracker
        self.shiny_tracker = ShinyTracker(store, self.rom_sha1)
        from .legendary_returns import StepTracker
        self.step_tracker = StepTracker(store, self.rom_sha1)
        from .activity_ledger import ActivityLedger
        self.activity_ledger = ActivityLedger(store, self.rom_sha1)
        if hasattr(self.policy, "collection"):
            self.policy.collection.version = ("yellow" if "Yellow" in self.rom_note
                                              else "blue" if "Blue" in self.rom_note else "red")
            # The cartridge's own encounter odds, with a randomized run's overrides, read once.
            from .planning.cost import wild_odds
            self.policy.collection.wild = wild_odds(self.rom, self.policy.collection.version)
        if hasattr(self.policy, "nav"):
            self.policy.nav.use_world = not self.rom_note.startswith("unverified")
        self.input_epoch = 0
        if hasattr(self.policy, 'nav'):
            # Pay optional compilation cost during startup, before gameplay begins.
            from .policies.navigation_numba import kernel
            kernel()
        self.tracer = trace.for_store(store, 1)
        self.pb = self._boot(tracer=self.tracer)
        self._audio_enabled = False
        self.thread = threading.Thread(target=self._run, name="emulator", daemon=True)

    # ---------------- lifecycle ----------------
    def _check_rom(self) -> str:
        sha = hashlib.sha1(self.rom.read_bytes()).hexdigest()
        self.rom_sha1 = sha
        known = config.GEN1_ROM_SHA1.get(sha)
        if known:
            log.info("ROM verified: %s", known)
            return known
        log.warning("ROM sha1 %s is not a known clean Red, Blue or Yellow dump, so RAM addresses may be off", sha)
        return f"unverified ROM (sha1 {sha[:12]})"

    def _boot(self, *, sound=True, tracer=None) -> CoreEmulator:
        """A new emulator. The game's own boots pass the ``tracer``, and a clone for a gift passes none."""
        options = {'color_palette': PALETTES['original']}
        if getattr(self, 'isolated_ram', False):
            import io
            options['ram_file'] = io.BytesIO(bytes(32768))
        from .randomized import rom_stream
        pb = open_emulator(rom_stream(self.rom), default=CoreEmulator, window="null", sound_emulated=sound,
                           yellow=self.rom_sha1 == YELLOW_SHA1, **options)
        if tracer is not None:
            # Before the trackers register their hooks, so the trace knows every hook.
            tracer.attach(pb)
        pb.set_emulation_speed(0)
        if getattr(self, 'activity_ledger', None) is not None:
            self.activity_ledger.attach(pb)
        shiny_tracker = getattr(self, 'shiny_tracker', None)
        if shiny_tracker is not None:
            shiny_tracker.attach(pb)
        tracker = getattr(self, 'catch_tracker', None)
        if tracker is not None:
            tracker.attach(pb)
        if getattr(self, 'step_tracker', None) is not None:
            self.step_tracker.attach(pb)
        return pb

    def start(self):
        from .league_history import recover
        recover(self.store, self.rom)
        saves = self.store.autosaves()
        if saves:
            self._restore_first_valid(reversed(saves))
        rewards.initialize(self.store, self.mem.championships)
        self.paused = bool(self.store.get("trade_hold"))
        if self.isolated_ram:
            from .runtime.preparation import restore
            restore(self)
        self.thread.start()

    def freeze(self):
        """Show the newest save of a stopped adventure without running it."""
        saves = self.store.autosaves()
        if not saves:
            raise RuntimeError('This adventure has no save to show yet')
        self._restore_first_valid(reversed(saves))
        self.frozen = self.paused = True
        self._publish_frame()

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

    def goals(self, query=None):
        """The goals a manager can set as the next activity, named like ``query`` if given. Runs on the
        game thread."""
        goals, reason = self.policy.goals(self.snapshot, query)
        return pin.listing(goals, self.policy.pin, reason)

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
            self._handle_events([Event(**pin.gave_up(label, reason))], self.snapshot)

    def press(self, button: str):
        if button in BUTTONS:
            self.command("press", button)

    def held_back(self, name):
        """Why the game drops this command now, or None when it runs it."""
        if not getattr(self, 'store', None) or name in ('stop', 'speed', 'pause'):
            return None
        if (self.store.get('interaction_preparation') or {}).get('phase') in PREPARING:
            return 'The adventure is getting ready for an exchange'
        if self.store.get('trade_hold'):
            return 'An exchange is holding this adventure'
        return None

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

    def status(self) -> dict:
        from .investment import rating_problem
        from .randomized import status as randomizer_status
        snap = self.snapshot
        strategy = self.policy.details()
        preparation = getattr(self, 'preparation', None)
        if preparation:
            strategy = preparation.details(strategy)
        return {
            "version": __version__, "viewer_only": config.VIEWER_ONLY,
            "build": build_info(), "stopped": self.frozen,
            "health": self.health(),
            "paused": self.paused, "speed": self.speed, "policy": self.policy.describe(),
            # Yellow renders its own Game Boy Color palettes, so like Generation II it reports none.
            "palette": None if self._color_cartridge() else getattr(self, 'palette', 'original'),
            "fair_wild_dvs": getattr(config, 'FAIR_WILD_DVS', False) is True,
            "manual_mode": self.manual_mode,
            "help_request": stall_truth.observe_help(self, self.help_request(strategy)),
            # Why the PC cannot rate or release, for the library watchdog (investment.rating_problem).
            "rating_problem": rating_problem(),
            "play_clock": self.play_clock.status(),
            "performance": {"frames": self.executed_frames, "sampled_at": time.monotonic()},
            "frame": self.frame, "uptime": int(time.time() - self.started_at),
            "stuck_seconds": max(0, self.frame - self.stuck_frame) // FRAMES_PER_SECOND, "rom": self.rom_note,
            "game": snap.to_dict() if snap else None,
            "areas_discovered": len(self.mem.seen_maps), "reloads": self.reloads,
            "glitched": self.invalid_frame is not None,
            "strategy": strategy,
            "progress": self.progress_status(),
            "league_rewards": rewards.status(self.store),
            "legendary_recovery": self.legendary_recovery.state_dict(),
            "randomizer": randomizer_status(),
        }

    def help_request(self, strategy):
        """Ask the owner for a hand when live play has stopped making game progress."""
        stall = getattr(self, 'stall', None)
        if self.paused or self.manual_mode:
            return None
        # The answer of the last scan. Only the guard check scans, on the emulator thread, so the
        # status page cannot move a scan to a frame a replay would not reach.
        guard = getattr(self, 'loop_guard', None)
        if loop := guard and guard.reason:
            return {'reason': f'The run is caught in a loop. {loop}', 'action': strategy.get('action', '')}
        if not stall or not stall.stalled(self.play_clock.frames):
            # A missing entry left uncaught for want of a slot, with nothing in the PC that may go.
            from .pcvalue import BOXES_FULL, boxes_full
            from .policies.collection import catch_room
            snap = getattr(self, 'snapshot', None)
            if boxes_full(getattr(getattr(self, 'policy', None), 'boxes_full', False), catch_room(snap) if snap else None):
                return {'reason': BOXES_FULL, 'action': strategy.get('action', '')}
            return None
        return {'reason': 'The policy has stopped making game progress', 'action': strategy.get('action', '')}

    def progress_status(self):
        achievement = getattr(self, 'last_achievement', None)
        age = max(0, int(time.time() - achievement['ts'])) if achievement else None
        mode = self.policy.details().get('action', '')
        state = 'recovering' if (self.invalid_frame is not None or time.time() - self.last_reload < 30
                                 or mode == 'finding another approach') else 'making_progress' if age is not None and age < 120 else 'exploring'
        stall, frames = getattr(self, 'stall', None), self.play_clock.frames
        if stall and stall.stalled(frames) or self.supervisor.stalled:
            state = 'stalled'
        return {'state': state, 'quiet_game_minutes': stall.game_minutes(frames) if stall else 0,
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
        errors = {}
        for path in paths:
            try:
                self._load_state_file(path)
                log.info("resumed from %s", path.name)
                return
            except Exception as error:
                reason = str(error).rstrip('.') or type(error).__name__
                errors.setdefault(f"{type(error).__name__}: {reason}"[:200], []).append(path.name)
                log.warning("cannot restore %s: %s", path.name, reason, exc_info=not isinstance(error, ValueError))
                self.pb.stop(save=False)
                self.pb = self._boot(tracer=getattr(self, 'tracer', None))
                self._audio_enabled = False
        # The reasons travel to the Library and the server log, where the adventure's own log is out of reach.
        tried = sum(map(len, errors.values()))
        reasons = ''.join(f" {reason} ({len(names)} {'save' if len(names) == 1 else 'saves'}, first {names[0]})."
                          for reason, names in list(errors.items())[:3])
        raise RuntimeError(f"No compatible autosave could be restored ({tried} tried).{reasons} "
                           "Restore a backup or use a new data directory.")

    def _load_state_file(self, path: Path):
        metadata = self.store.checkpoint_metadata(path)
        barrier = self.store.get("trade_barrier")
        if barrier and (metadata or {}).get("trade_id") != barrier:
            raise ValueError("Checkpoint predates the latest completed trade")
        reward_barrier = self.store.get('custom-reward-barrier-v1')
        if reward_barrier and (metadata or {}).get('reward_id') != reward_barrier:
            raise ValueError('Checkpoint predates the latest custom reward or purchase')
        if metadata:
            if metadata.get("rom_sha1") != self.rom_sha1:
                raise ValueError("Checkpoint was created with a different ROM")
            validate_runtime(metadata)
            if metadata.get("policy") != config.POLICY:
                raise ValueError("Checkpoint requires a different policy")
        with open_state(path) as f:
            raw = f.read()
            self.pb.load_state(io.BytesIO(enable_checkpoint_sound(raw)))
        if getattr(self, "audio", None) is not None:
            self.audio.clear()
        # A checkpoint can be captured while a direction is held. The next
        # policy action must not inherit that button from the saved joypad.
        for button in BUTTONS:
            self.pb.button_release(button)
        # A pin belongs to the moment it was set, so it never outlives a load.
        self.policy.unpin_goal()
        if metadata:
            self.policy.load_state_dict(metadata["policy_state"])
            announced = getattr(self, 'mem', RunMemory()).playtime_milestones.copy()
            announced.update(self.store.get(PLAYTIME_MILESTONES, []))
            self.mem = RunMemory.from_dict(metadata["run_memory"])
            with self.store.reading() as db:
                self.mem.championships = max(self.mem.championships, rewards.championship_count(rewards.ledger(db)))
            self.mem.playtime_milestones.update(announced)
            self.frame = metadata.get("frame", self.frame)
        else:
            # A save from before checkpoint manifests rewinds the cartridge alone. Its policy takes the last kv
            # copy, the one case docs/design/adventure-state-store.md section 3.5 keeps that copy readable for.
            self.policy.load_state_dict(self.store.get('policy_state', {}))
        self._reset_transient(clear_observation=True)
        self.legendary_recovery = LegendaryRecovery((metadata or {}).get('legendary_recovery'))
        self.play_clock.restore(metadata.get("play_clock") if metadata else None)
        # A League gift or a legendary return delivered after this save is not in it, so its claim opens again.
        rewards.rewound(self.store, metadata)
        if repaired := repair_party_nicknames(self.pb.memory):
            log.warning('Ended the damaged nicknames of party slots %s at their first text command', repaired)
        self.snapshot = read_snapshot(self.pb.memory, self.frame)
        if self.snapshot.started:
            self.play_clock.seed(self.snapshot.playtime_seconds)
        # A restart empties the gift ledger. Loading a game from before it would otherwise count
        # every earlier League win as new on the next win, and pay each gift out again.
        rewards.initialize(self.store, getattr(self, 'mem', RunMemory()).championships)

    def _decline_returns(self):
        """Close the returned legendaries the battle refused to catch."""
        from .legendary_returns import decline
        collection = getattr(self.policy, 'collection', None)
        declined = getattr(collection, 'declined_returns', None)
        if isinstance(declined, set):
            for number in declined:
                decline(self.store, number)
            collection.declined_returns = set()

    def _reset_transient(self, *, clear_observation=False):
        """Discard queued input and recovery timers without erasing durable progress."""
        self.policy.on_restore()
        if hasattr(self.policy, 'collection') and hasattr(self, 'store'):
            from .legendary_returns import claims
            self._decline_returns()
            ready, closed = claims(self.store)
            self.policy.collection.returned_legendaries = ready
            self.policy.collection.closed_legendaries = closed
            from . import step_events
            self.policy.collection.returned_events = step_events.available(self.store)
        if hasattr(self, 'statistics'):
            self.statistics.reset_baseline()
        self.input_epoch = getattr(self, 'input_epoch', 0) + 1
        Emulator._reset_watch(self)
        self.last_pos = None
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

    def _color_cartridge(self):
        from .game_data import current_variant
        return current_variant() == 'yellow'

    def _image(self) -> Image.Image:
        image = self.pb.screen.image.convert("RGB")
        return image if self._color_cartridge() else recolor(image, getattr(self, 'palette', 'original'))

    def set_palette(self, value):
        """Called on the emulator thread, including while the game is paused."""
        self.palette = validate_palette(value)
        self._publish_frame()
        return {'palette': self.palette}

    def set_fair_wild_dvs(self, value):
        """Called on the emulator thread, so the next wild encounter already follows the new setting."""
        from . import fair_dvs
        config.FAIR_WILD_DVS = value is True
        tracker = self.shiny_tracker
        tracker.fair_key = fair_dvs.secret(tracker.store) if tracker.supported and config.FAIR_WILD_DVS else None
        return {'fair_wild_dvs': config.FAIR_WILD_DVS}

    def _shot_png(self, img=None) -> bytes:
        img = self._image() if img is None else img
        img = img.resize((img.width * SHOT_SCALE, img.height * SHOT_SCALE), Image.NEAREST)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue()

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

    def _report_uncatchable_shiny(self, snapshot):
        """Say once per battle why a shiny cannot be caught. The policy runs from it as usual.

        Balls cannot be bought and storage cannot be freed in battle, so pausing would only
        look like a stall. The supply and storage reserves are what keep a shiny catchable.
        """
        if not snapshot.enemy_shiny or snapshot.in_battle != 1:
            self._shiny_reported = False
            return False
        from .strategy_data import ITEMS
        balls = {ITEMS[name] for name in ('POKE_BALL', 'GREAT_BALL', 'ULTRA_BALL', 'MASTER_BALL')}
        if not snapshot.can_catch:
            why = 'no storage space'
        elif snapshot.battle_type == 0 and not any(item in balls and qty for item, qty in snapshot.items):
            why = 'no balls'
        else:
            return False
        if getattr(self, '_shiny_reported', False):
            return True
        self._shiny_reported = True
        species = SPECIES_NAMES.get(snapshot.enemy_species) or 'Pokémon'
        self._handle_events([Event('shiny_missed', f'Shiny {species} could not be caught: {why}',
                                   f'A shiny {species} appeared with {why}, so the adventure ran from it. '
                                   'The supply and storage reserves should prevent this.',
                                   priority=LOW, tags='star')], snapshot)
        return True

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
            now = time.monotonic()
            if publishing:
                self._last_publish = now
                self._publish_frame()
            if observing:
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
        with self.store.observation_reads():
            self._observe_snapshot()

    def _watch_boss(self, before, snap):
        """Hold back the progress of a boss attempt, which a loss drops (Supervisor.watch_boss).

        An attempt runs while the party is inside the League or on the map of the boss its goal challenges.
        """
        from .policies.strategic import BOSSES
        stall = getattr(self, 'stall', None)
        if stall is None or not snap.valid:
            return
        goal = getattr(self.policy, 'goal', None)
        boss = (snap.map in LEAGUE - {MAPS['HALL_OF_FAME']}
                or goal is not None and goal.key in BOSSES and goal.title.startswith('Challenge')
                and any(target[0] == snap.map for target in goal.targets))
        blackout = before is not None and before.valid and snap.all_fainted and not before.all_fainted
        self.supervisor.watch_boss(boss, blackout, stall, getattr(self, 'loop_guard', None))

    def _observe_snapshot(self):
        snap = read_snapshot(self.pb.memory, self.frame)
        if snap.started:
            self.play_clock.seed(snap.playtime_seconds)
            self._enforce_options()
        came_from = self.prev_snapshot.map if self.prev_snapshot else None
        Emulator._watch_boss(self, self.prev_snapshot, snap)
        if (self.prev_snapshot is not None and snap.valid and self.prev_snapshot.valid
                and advanced(self.prev_snapshot, snap) and getattr(self, 'stall', None)):
            # A long hunt catches plenty that the Pokédex already has, and training earns experience
            # between level milestones. Neither is a stall.
            self.stall.progress(self.play_clock.frames, time.time())
        new = diff(self.prev_snapshot, snap, self.mem)
        if snap.valid and snap.started:
            self.supervisor.progressed(snap, len(self.mem.seen_maps), self.mem.championships)
        if snap.valid and snap.started and (watch := getattr(self, 'goal_watch', None)):
            watch.story(self.store, snap.event_flags)
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
        self._release_journal(events, snap)
        restored_legendary = False
        if (self.rom_sha1 in config.GEN1_ROM_SHA1 and not self.manual_mode
                and not self.store.get('trade_hold')):
            from .legendary_returns import observe as returns_observe, claims
            if hasattr(self, 'step_tracker'):
                self.step_tracker.flush()
            from . import mew_returns
            mew_returns.observe(self.store, snap)
            from . import champion_shop
            champion_shop.observe(self.store, snap)
            if hasattr(self.policy, 'shop_offers'):
                self.policy.shop_offers = champion_shop.ready(self.store)
            return_events, restored_legendary = returns_observe(self.store, snap, self.pb.memory)
            events += return_events
            from . import step_events
            activity_events, activity_changed = step_events.observe(self.store, snap, self.pb.memory)
            events += activity_events
            restored_legendary |= activity_changed or bool(activity_events)
            if hasattr(self.policy, 'collection'):
                self.policy.collection.returned_events = step_events.available(self.store)
            if restored_legendary:
                snap = read_snapshot(self.pb.memory, self.frame)
            self._decline_returns()
            ready, closed = claims(self.store)
            if hasattr(self.policy, 'collection'):
                self.policy.collection.returned_legendaries = ready
                self.policy.collection.closed_legendaries = closed
            recovery_events, recovered = self.legendary_recovery.observe(
                snap, self.pb.memory, repeat=ready, blocked=closed)
            restored_legendary |= recovered
            events += recovery_events
            if restored_legendary:
                snap = read_snapshot(self.pb.memory, self.frame)
                self.prev_snapshot = snap
        if hasattr(self, 'milestones'):
            self.milestones.observe(snap)
            if hasattr(self.policy, 'collection'):
                from .milestones import status as milestone_status
                self.policy.collection.milestones = milestone_status(self.store)
        if hasattr(self, 'statistics'):
            self.statistics.observe(snap, self.pb.memory, clock=self.play_clock.status())
        if hasattr(self, 'goal_time') and snap.valid and snap.started:
            from .goal_time import gen1_view
            self.goal_time.observe(*gen1_view(self.policy), self.frame)
        with self.lock:
            self.snapshot = snap
        if snap.valid and snap.started:
            self.store.upgrade_trade_preferences(
                lambda: [dataclasses.asdict(mon) for mon in snap.party] + snap.storage_entries())
        pos = (snap.map, snap.x, snap.y)
        if pos != self.last_pos or snap.in_battle or not snap.started:
            self.last_pos = pos
            self.stuck_frame = self.frame
        if not snap.valid:
            self.invalid_frame = self.frame if self.invalid_frame is None else self.invalid_frame
        else:
            self.invalid_frame = None
        if snap.in_battle and snap.started:
            self.battle_frame = self.frame if self.battle_frame is None else self.battle_frame
        else:
            self.battle_frame = None
        if events:
            self._handle_events(events, snap)
            if any(event.type == 'playtime' for event in events):
                self.store.set(PLAYTIME_MILESTONES, sorted(self.mem.playtime_milestones))
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
            guard = getattr(self, 'loop_guard', None)
            # A gift in a gift and release loop is not progress.
            looped = ev.type == 'obtain' and guard and guard.looping(self.store)
            if ev.type in PROGRESS_EVENTS and getattr(self, 'stall', None) and not looped:
                self.stall.progress(self.play_clock.frames, time.time())
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
                           click=f"{config.PUBLIC_URL}/events/{eid}", event_type=ev.type)

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
        want = gen1_options(self.pb.memory[W_OPTIONS])
        if want != self.pb.memory[W_OPTIONS]:
            self.pb.memory[W_OPTIONS] = want

    def _manifest(self):
        return checkpoint_manifest(self.policy, rom_sha1=self.rom_sha1, frame=self.frame,
                                   run_memory=self.mem, play_clock=self.play_clock, store=self.store,
                                   legendary_recovery=self.legendary_recovery)

    def _autosave(self, trade_prepare=False):
        if self.store.get("trade_hold") and not trade_prepare:
            return
        self.store.set("play_clock", self.play_clock.state_dict())
        if hasattr(self, 'step_tracker'):
            self.step_tracker.flush(force=True)
        if hasattr(self, 'statistics'):
            self.statistics.flush()
        snap = self.snapshot
        battle_frame = getattr(self, 'battle_frame', None)
        if battle_frame is not None and not trade_prepare and (
                self.frame - battle_frame > config.BATTLE_TIMEOUT_SECONDS * FRAMES_PER_SECOND // 3
                or getattr(self.policy, 'hopeless_battle', False)):
            # A battle this long may never end, and the only way out is a save from before it began.
            # Rotating autosaves during it would push that save out before the timeout reloads it.
            return
        if snap is not None and not snap.valid:
            log.warning("skipping autosave: game state looks glitched")
            return
        manifest = self._manifest()
        state = self._state_bytes()
        path = self.store.write_checkpoint(state, manifest)
        tracer = getattr(self, 'tracer', None)
        if tracer is not None:
            tracer.begin(path.stem, state, manifest, kept=path)
        # The first save after an achievement is the last one known to be from before any stall.
        capture.keep_before(self, path, snap)
        self.store.prune_autosaves(config.KEEP_AUTOSAVES)
        capture.prune_trace(self)
        self.store.prune_events(config.EVENT_RETENTION_DAYS)
        self.store.prune_attachments(config.EVENT_ATTACHMENT_KEEP)
        self.store.prune_reward_results()

    def _checkpoint_before(self, name: str):
        """Keep the game as it is now under `name` before a rewind or restart replaces it."""
        if self.store.get("trade_hold"):
            return
        try:
            # A named checkpoint, not an autosave: as the newest autosave it would undo the rewind on the next start.
            self.store.write_checkpoint(self._state_bytes(), self._manifest(), name)
        except Exception:
            log.exception("cannot keep the save from before %s", name)

    def _reset_watch(self):
        """Restart the guard clocks from the current frame, which a reload has just rewound."""
        self.stuck_frame = self.last_reload_frame = self.frame
        self.last_reload = time.time()
        self.invalid_frame = self.battle_frame = None

    def _give_up(self, why):
        """Abandon the collection project that every reload left stuck, so the next goal runs instead.

        The project stands down in the director and comes back later, and the reloads start over for
        whatever runs next. A story goal has no project to abandon, so it stays flagged as stalled.
        """
        policy, snapshot = getattr(self, 'policy', None), getattr(self, 'snapshot', None)
        collection = getattr(policy, 'collection', None)
        if not getattr(collection, 'project', None) or not getattr(snapshot, 'started', False):
            return False
        goal = getattr(policy, 'goal', None)
        label = goal.title if goal is not None else 'the current project'
        capture.keep(self, 'give_up', why)
        reloads = self.supervisor.reloads
        collection.abandon(f'{why.capitalize()} and {reloads} reloads did not help')
        log.error('%s and %d reloads did not help, giving up on %s for now', why, reloads, label)
        self._handle_events([Event('stall', f'Gave up on “{label}” for now',
                                   f'{why.capitalize()} at {snapshot.map_name} and {reloads} reloads '
                                   'did not help, so it waits while other goals run.', priority=HIGH)], snapshot)
        policy.on_restore()
        Emulator._reset_watch(self)
        self.input_epoch += 1
        return True

    def _unstick(self, since_frame: int, why: str):
        """Go back to an autosave from before the trouble started (or power-cycle if there is none).

        ``since_frame`` is the frame the trouble started on. The target is picked by the frame each
        autosave records, not by file time, so a replay picks the same save at any pace.
        """
        Emulator._drop_pin(self, pin.STUCK)
        note = getattr(getattr(self, 'policy', None), 'note_boss_loss', None)
        snapshot = getattr(self, 'snapshot', None)
        if note is not None and snapshot is not None and (why == CANNOT_END or getattr(snapshot, 'in_battle', 0) == 2):
            # A boss battle the reload leaves is lost, though not everyone fainted, so the team trains
            # before it goes back in. note_boss_loss ignores trainers outside a boss gym.
            note(snapshot)
        guard = getattr(self, 'loop_guard', None)
        # A reload out of a boss attempt loses it, so the progress it made does not start the ladder again.
        self.supervisor.lost(getattr(self, 'stall', None), guard)
        rung = self.supervisor.climb(why, lambda: Emulator._give_up(self, why),
                                     looping=lambda: guard and guard.looping(self.store),
                                     in_league=lambda: snapshot is not None and snapshot.map in LEAGUE)
        if rung.kind == GIVE_UP:
            return
        if rung.kind == HOLD:
            # Reloading again would only replay the same trouble. Leave the run as it is, flagged as
            # stalled, and say so once rather than at every guard check.
            if rung.first:
                log.error('%s and %d reloads did not help, not reloading again', why, rung.reloads)
            Emulator._reset_watch(self)
            return
        saves = self.store.autosaves()
        target = reload_target(self.store, saves, since_frame)
        # A recent save inside the League can already be lost: one frozen partner left and an
        # opponent that never attacks. If going back a little did not help, restart the attempt.
        entry = self.store.state_path(LEAGUE_CHECKPOINT)
        if rung.league and entry:
            log.warning("%s inside the League, restarting the attempt", why)
            target, saves = entry, [entry] + saves
        if rung.report and snapshot is not None and snapshot.valid and snapshot.started:
            title, body = stuck_report(why, snapshot.map_name)
            self._handle_events([Event('stall', title, body, priority=HIGH)], snapshot)
        progress_events.reload(self.store, why)
        if target:
            log.warning("%s for %.1f game minutes, reloading %s", why,
                        max(0, self.frame - since_frame) / FRAMES_PER_SECOND / 60, target.name)
            if guard:
                guard.reloaded(target.name)
            candidates = [target] + [p for p in reversed(saves) if p != target]
            clock = self.play_clock.frames
            with trace.reason(self, 'reload'):
                self._restore_first_valid(candidates)
            # The emulator is deterministic, so the same save and the same choices would replay the
            # same trouble. Idling a moment drawn from the reload stream moves the game's random
            # numbers along, the same way in a replay.
            self._tick(seeds.reload_idle(self.adventure_seed, clock))
        else:
            log.warning("%s and no save state to go back to; power-cycling", why)
            self.pb.stop(save=False)
            self.pb = self._boot(tracer=getattr(self, 'tracer', None))
            self._audio_enabled = False
            self.prev_snapshot = None
            self.policy.on_restore()
            if hasattr(self, 'statistics'):
                self.statistics.reset_baseline()
            self.input_epoch += 1
        Emulator._reset_watch(self)
        self.reloads += 1

    def _check_guards(self):
        """Reload or replan a run that is stuck, glitched or in a battle that never ends.

        Every limit counts emulator frames, so a guard fires on the same frame in a replay and at
        any pace. The configured limits are in game seconds.
        """
        if guard := getattr(self, 'loop_guard', None):
            guard.looping(self.store)
            if why := guard.take_trip():
                capture.keep(self, 'loop', why)
        frame = self.frame
        if frame - self.last_reload_frame < RELOAD_QUIET_FRAMES:
            return
        invalid_grace = INVALID_GRACE_FRAMES
        if self.invalid_frame is not None:
            from pokecore.centers import CENTERS
            snapshot = self.snapshot
            if (snapshot is not None and snapshot.map in CENTERS and not snapshot.in_battle
                    and snapshot.hp_overflow_only and hasattr(self.policy, 'heal_latch')):
                # Give the normal healing trip time to finish. The state remains invalid for saving
                # and the grace is still bounded.
                invalid_grace = CENTER_GRACE_FRAMES
        if self.invalid_frame is not None and frame - self.invalid_frame > invalid_grace:
            self._unstick(self.invalid_frame, "game state glitched")
        elif config.STUCK_RELOAD_SECONDS and frame - self.stuck_frame > config.STUCK_RELOAD_SECONDS * FRAMES_PER_SECOND:
            recover = getattr(self.policy, 'recover_stall', None)
            if recover and self.snapshot and self.snapshot.valid and not self.snapshot.in_battle:
                self._drop_pin(pin.STUCK)
                recover(self.snapshot)
                self.stuck_frame = frame
                self.input_epoch += 1
                log.warning('stationary objective abandoned, replanning without a save reload')
            else:
                self._unstick(self.stuck_frame, "stuck")
        elif self.battle_frame is not None and frame - self.battle_frame > config.BATTLE_TIMEOUT_SECONDS * FRAMES_PER_SECOND:
            self._unstick(self.battle_frame, "battle never ended")
        elif self.battle_frame is not None and getattr(self.policy, 'hopeless_battle', False):
            # The player has worked out that neither side can finish, so the timeout has nothing to wait for.
            self._unstick(self.battle_frame, "battle cannot end")
        self._check_stall(time.time())

    def _check_stall(self, now):
        """Report a run that is healthy and moving but has achieved nothing for hours of game time."""
        snap = self.snapshot
        if snap is None or not snap.valid or not snap.started:
            return
        stall, frames = getattr(self, 'stall', None), self.play_clock.frames
        quiet = stall.check(frames, now) if stall else None
        if stall and stall.capture_due(frames):
            # Kept as soon as game time says it is a stall. The alert waits for real time as well.
            capture.keep(self, 'quiet', f'no progress for {stall.game_minutes(frames)} game minutes', now)
        if quiet is None:
            return
        details = self.policy.details() if hasattr(self.policy, 'details') else {}
        objective = (details.get('objective') or {}).get('title') or 'no objective'
        hours = quiet[0] / 60
        log.warning('no progress for %.1f game hours at %s: %s', hours, snap.map_name, objective)
        self._handle_events([Event('stall', f'Stuck? {hours:.0f} game hours without progress',
                                   f'Objective: {objective}. On {snap.map_name} after {quiet[1]} real minutes '
                                   f'and {details.get("recoveries", 0)} recoveries. The saved moment is attached '
                                   'to this journal entry.', priority=HIGH, tags='warning')], snap)

    def _release_journal(self, events, snap):
        """Quote the PC value of a spare the policy let go, and say once when the PC is full with nothing
        that may go, with the box counts and the objective waiting for room (pcvalue.full_alert)."""
        from .pcvalue import full_alert, full_notice
        from .policies.team import storage_headroom
        policy = getattr(self, 'policy', None)
        # The note of the release the policy started, not the next target's.
        note = getattr(policy, 'released_note', None)
        for ev in events:
            if ev.type == 'release' and note and ev.title == f"Said goodbye to a spare {SPECIES_NAMES.get(note[0], f'#{note[0]}')}":
                ev.body += f' PC value: {note[1]}.'
        blocked = bool(getattr(policy, 'pc_deadlock', False)) and storage_headroom(snap) <= 0
        if policy is not None and full_notice(self.store, blocked):
            details = policy.details() if hasattr(policy, 'details') else {}
            waiting = [(details.get('objective') or {}).get('title')]
            text = full_alert(getattr(snap, 'box_counts', ()), waiting)
            events.append(Event('pc_full', 'PC full', f'{text} Release or unlock one from the PC tab.',
                                priority=HIGH, tags='warning'))

    def pc_values(self):
        """Each boxed Pokémon's PC value by (box, position), and whether nothing may go (pcvalue.annotate)."""
        from .pcvalue import annotate, deadlocked
        from .policies.team import storage_headroom

        def view():
            snap = self.snapshot
            if snap is None or not hasattr(self.policy, 'pc_rated'):
                return {}, False
            rated = self.policy.pc_rated(snap)
            return annotate(rated, snap.active_box), deadlocked(rated, storage_headroom(snap))
        return self.call(view, timeout=5)

    def request_release(self, box, position, key, confirm=''):
        """Store the owner's Release for the boxed Pokémon at (box, position), or raise ValueError."""
        from .pcvalue import pc_request
        from .trade.preferences import identity

        def request():
            snap = self.snapshot
            if snap is None or not hasattr(self.policy, 'pc_rated'):
                raise ValueError('Wait for the adventure to be ready before releasing.')
            value = pc_request(self.policy.pc_rated(snap), (box, position), key, identity, confirm)
            self.store.set_release_request(key, value)
            return value
        return self.call(request)

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
        if hasattr(self, 'statistics'):
            self.statistics.reset_baseline()
        self.stuck_frame = self.frame
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
            if preparation.get('phase') in PREPARING and name == 'pause' and getattr(self, 'preparation', None):
                from .runtime.preparation import cancel
                cancel(self, preparation['id'])
        if self.held_back(name):
            return True
        if name == "stop":
            return False
        if name == "pause":
            self.paused = True
            self.manual_mode = False
        elif name in ("take_control", "press"):
            if name == "take_control":
                # A new holder of the control lease never inherits presses someone else queued.
                self.input_epoch += 1
                while not self.manual.empty():
                    self.manual.get_nowait()
            if not self.manual_mode:
                self.policy.on_restore()
                if hasattr(self, 'statistics'):
                    self.statistics.reset_baseline()
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
                # Undoing a rewind loads before-load itself, so it is held while the checkpoint replaces it.
                with self.store.held(p, BEFORE_LOAD_CHECKPOINT) as source:
                    self._checkpoint_before(BEFORE_LOAD_CHECKPOINT)
                    try:
                        with trace.reason(self, 'rewind'):
                            self._load_state_file(source)
                    except ValueError as error:
                        log.warning("Rewind to %s refused: %s", p.name, error)
                    else:
                        log.info("loaded %s", p.name)
        elif name == "restart":
            log.warning("restarting run from power-on")
            # The restart removes every autosave, so the game from before it stays as a named checkpoint.
            self._checkpoint_before(BEFORE_RESTART_CHECKPOINT)
            if hasattr(self, 'statistics'):
                self.statistics.flush()
            restart(self, 1, self._new_game(), self._start_new_game)
        return True

    def _new_game(self):
        """The rows the new game starts with, which the restart's transaction writes. The trade and
        reward barriers stay, so a named checkpoint from before a trade or a gift still cannot load."""
        from . import adventure_records, catches, milestones, shiny
        values = {'play_clock': PlayClock().state_dict(), milestones.KEY: milestones.empty(),
                  adventure_records.KEY: adventure_records.fresh()}
        if getattr(self, 'catch_tracker', None) is not None:
            values[catches.KEY] = self.catch_tracker.empty(True)
        if getattr(self, 'shiny_tracker', None) is not None:
            values[shiny.KEY] = shiny.fresh(self.shiny_tracker.supported)
        return values

    def _start_new_game(self):
        """Boot the committed new game, with trackers that hold nothing of the old one in memory."""
        from .goal_time import GoalTime
        self.pb.stop(save=False)
        self.loop_guard = LoopGuard(lambda: self.play_clock.frames)
        # The restart emptied the old run's reload streak from the store, so it cannot hold the new one stalled.
        self.supervisor = Supervisor(self.store)
        if watch := getattr(self, 'goal_watch', None):
            watch.restart()
        self.goal_time = GoalTime(self.store)
        if hasattr(self, 'milestones'):
            from .milestones import MilestoneTracker
            self.milestones = MilestoneTracker(self.store)
        if getattr(self, 'catch_tracker', None) is not None:
            from .catches import CatchTracker
            self.catch_tracker = CatchTracker(self.store, self.rom_sha1, fresh=True)
        if getattr(self, 'shiny_tracker', None) is not None:
            from .shiny import ShinyTracker
            self.shiny_tracker = ShinyTracker(self.store, self.rom_sha1)
        if hasattr(self, 'statistics'):
            from .statistics import StatisticsTracker
            self.statistics = StatisticsTracker(self.store)
            # The capture baseline moves to the new game's empty count.
            self.statistics.flush()
        self.mem = RunMemory()
        self.legendary_recovery = LegendaryRecovery()
        self.last_achievement = None
        self.play_clock = PlayClock()
        self.snapshot = None
        # The restart's transaction dropped the old seed, so the new game draws its own starter and choices.
        self.adventure_seed = self.policy.seed = seeds.adventure_seed(self.store)
        self.policy.reset()
        self.pb = self._boot(tracer=getattr(self, 'tracer', None))
        self._audio_enabled = False
        self.frame = 0
        self.paused = self.manual_mode = False
        self._reset_transient(clear_observation=True)

    def _guards(self):
        """The stuck, battle and glitch guards, which stand aside while a person or a trade has the game."""
        if not self.manual_mode and not self.paused and not getattr(self, 'preparation', None):
            self._check_guards()

    def _run(self):
        # The autosave counts game time, so a replay saves on the same frames at any pace. A reload
        # rewinds the frame and the cadence counts again from there.
        loop = GameLoop(self, Gen1(lambda: self.play_clock.frames), self._tick, guards=self._guards,
                        autosave=self._autosave)
        running = True
        self.consecutive_errors = 0
        input_epoch = self.input_epoch
        tracer = getattr(self, 'tracer', None)
        while running and not getattr(self, "stopping", False):
            try:
                if tracer is not None:
                    tracer.ensure(self._manifest)
                while running and not self.commands.empty():
                    name, arg = self.commands.get_nowait()
                    trace.note(self, 'command', trace.command(name, arg))
                    running = self._handle_command(name, arg)
                if not running:
                    break
                if input_epoch != self.input_epoch:
                    loop.pending.clear()
                    input_epoch = self.input_epoch
                    while not self.manual.empty():
                        self.manual.get_nowait()
                if not self.manual.empty():
                    loop.pending = [self.manual.get_nowait()]
                elif self.manual_mode:
                    loop.pending = [Action(None, 0, 4)]
                elif self.paused:
                    self.last_activity = time.monotonic()
                    self.consecutive_errors = 0
                    loop.pending.clear()
                    time.sleep(0.1)
                    continue
                if not loop.pending:
                    snap = read_snapshot(self.pb.memory, self.frame)
                    self._report_uncatchable_shiny(snap)
                    preparation = getattr(self, 'preparation', None)
                    loop.decide(snap, preparation)
                    if not preparation and hasattr(self.policy, 'collection'):
                        activity_events = progress_events.drain(
                            self.store, self.policy.collection.take_activity_events())
                        if watch := getattr(self, 'goal_watch', None):
                            collection = self.policy.collection
                            tier = 'RACE' if (collection.project or {}).get('method') == 'marathon' else ''
                            watch.observe(self.store, collection.project_key, tier, hunt=collection.hunt(snap))
                        if activity_events:
                            self._handle_events(activity_events, snap)
                    if self.paused:
                        continue
                act = loop.pending[0]
                nav = getattr(self.policy, "nav", None) if self.manual_mode else None
                if nav and act.button in ("up", "down", "left", "right") and not self.pb.memory[0xCFC5]:
                    before = read_snapshot(self.pb.memory, self.frame)
                    if not before.in_battle and not before.textbox and not before.start_menu:
                        nav.issued((before.map, before.x, before.y), act.button, self.frame)
                loop.act()
                if nav:
                    after = read_snapshot(self.pb.memory, self.frame)
                    nav.observe((after.map, after.x, after.y), self.frame, bool(self.pb.memory[0xCFC5]),
                                interrupted=bool(after.in_battle or after.textbox or after.start_menu))
                if getattr(self, 'isolated_ram', False) and getattr(self.policy, 'tm_plan', None):
                    from .runtime.tm_purchase import purchase
                    purchase(self)
                if getattr(self, 'isolated_ram', False):
                    from .runtime.reward_delivery import deliver, reward_due, schedule
                    if reward_due(self):
                        schedule(self, True)
                        delivered = deliver(self, league_rewards=config.LEAGUE_REWARDS,
                                            mew_event=config.MEW_EVENT)
                        schedule(self, delivered)
                self.last_activity = time.monotonic()
                self.consecutive_errors = 0
            except Exception:  # noqa: BLE001
                if loop_failed(self, log):
                    break
        try:
            if not getattr(self, "fatal_error", None):
                self._autosave()
        except Exception:
            self.fatal_error = 'The final save failed. Check disk space and the logs before relaunching.'
            log.exception('Final emulator save failed')
        finally:
            if tracer is not None:
                tracer.close()
            self.pb.stop(save=False)
