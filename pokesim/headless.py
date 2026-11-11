"""Play a cartridge with the strategic policy and no application around it.

The stall finder and the stuck scenarios share this, so a checkpoint one of them writes replays
in the other and in the application.
"""
from __future__ import annotations

import hashlib
import io
from pokecore.emulator_state import validate_runtime

from pokecore.emulator import Emulator as CoreEmulator

from .yellow import YELLOW_SHA1, open_emulator

from .checkpoints import CheckpointStore, open_state
from .events import RunMemory
from .game_data import VARIANT_ENV
from .policies.base import BUTTONS
from .policies.progression import YELLOW
from .policies.strategic import StrategicPolicy
from .runtime import trace as runtime_trace
from .runtime.game_loop import GameLoop, Gen1
from .runtime.manifest import checkpoint_manifest
from .runtime.supervision import Tables
from .seeds import RELOAD_IDLE, reload_idle

BLUE_SHA1 = 'd7037c83e1ae5b39bde3c30787637ba1d4c48ce2'


def fair_key(seed):
    """A fair wild DV key for a run with no adventure, the same for every run with this seed."""
    return hashlib.sha256(f'fair-wild-dvs {seed}'.encode()).digest()


class HeadlessRun:
    generation = 1
    # A tool that saves screenshots renders every frame.
    render = False
    tracer = None

    def __init__(self, rom, checkpoint=None, seed=7, rng=None, reseed=False, fair_wild_dvs=None, trace=None):
        """``trace`` is a folder to record the run in, one segment from the start, as an adventure's
        trace folder keeps them. None records nothing."""
        self.rom_sha1 = hashlib.sha1(rom.read_bytes()).hexdigest()
        # The policy reads its game data once at import, from POKESIM_GEN1_VARIANT. Yellow under
        # Red data reads menus at Red's addresses, so every battle shortcut times out.
        if (self.rom_sha1 == YELLOW_SHA1) != YELLOW:
            variant = 'yellow' if self.rom_sha1 == YELLOW_SHA1 else 'red'
            raise ValueError(f'This cartridge needs {VARIANT_ENV}={variant} before pokesim is imported')
        # A randomized run (RANDOMIZER set) plays the patched cartridge, as the managed worker does.
        from .randomized import rom_stream
        self.pb = open_emulator(rom_stream(rom), default=CoreEmulator, yellow=self.rom_sha1 == YELLOW_SHA1,
                                window='null', sound_emulated=False)
        # Before fair DVs register their hook, so the trace knows it.
        self.tracer = runtime_trace.for_run(trace, 1, self.pb, seed)
        self.pb.set_emulation_speed(0)
        # Fair wild DVs, as an adventure with the setting on plays them. True keys the rerolls from
        # the seed, and bytes are a live adventure's own key.
        if fair_wild_dvs:
            from . import fair_dvs
            key = fair_wild_dvs if isinstance(fair_wild_dvs, bytes) else fair_key(seed)
            fair_dvs.attach(self.pb, self.rom_sha1, key)
        self.policy = StrategicPolicy(seed)
        # The goals' stand-downs count on the run's frames, which a reload keeps, as the PlayClock does live.
        self.policy.monitor_tables = Tables(clock=lambda: self.frame)
        self.policy.collection.version = ('yellow' if self.rom_sha1 == YELLOW_SHA1
                                          else 'blue' if self.rom_sha1 == BLUE_SHA1 else 'red')
        from .planning.cost import wild_odds
        self.policy.collection.wild = wild_odds(rom, self.policy.collection.version)
        self.memory = RunMemory()
        self.frame = 0
        self.loop = GameLoop(self, Gen1(lambda: self.frame), self.tick)
        # A scenario passes its own generator so that a failure replays the same way.
        self.rng = rng
        self.seed = seed
        if checkpoint:
            # A checkpoint carries the policy's own random state, so every run of one checkpoint
            # makes the same choices whatever seed is asked for. Exploring needs the seed to matter;
            # replaying a saved stall needs the original choices, so this is the caller's decision.
            self._load(checkpoint, reseed=reseed, first=True)
        if self.tracer is not None:
            self.tracer.ensure(self.manifest)

    def _load(self, path, reseed=False, first=False):
        metadata = CheckpointStore(path.parent).checkpoint_metadata(path)
        if not metadata:
            raise ValueError('A checkpoint manifest is required for a faithful replay')
        validate_runtime(metadata)
        if metadata['rom_sha1'] != self.rom_sha1:
            raise ValueError('ROM or emulator version does not match the checkpoint')
        if first:
            # The run counts its frames on from the save's, before the policy reads a wait timed on them.
            # A reload keeps counting, so the frames never go back.
            self.frame = metadata.get('frame', 0)
        self.policy.load_state_dict(metadata['policy_state'])
        self.memory = RunMemory.from_dict(metadata['run_memory'])
        if reseed:
            self.policy.rng.seed(self.seed)
        with open_state(path) as stream:
            self.pb.load_state(stream)
        for button in BUTTONS:
            self.pb.button_release(button)
        return metadata

    def reload(self, path):
        """Go back to a checkpoint as the application does after a battle that never ends."""
        frame = self.frame
        with runtime_trace.reason(self, 'reload'):
            self._load(path)
        # The same save and the same choices would replay the same trouble. A scenario's own
        # generator picks the idle, and otherwise the reload stream does, so a rerun idles the same.
        idle = 1 + self.rng.randrange(RELOAD_IDLE) if self.rng else reload_idle(self.seed, frame)
        self.pb.tick(idle, render=False)

    def manifest(self):
        """The manifest a checkpoint of this moment carries."""
        return checkpoint_manifest(self.policy, rom_sha1=self.rom_sha1, frame=self.frame,
                                   policy_name='strategic', run_memory=self.memory)

    def state(self):
        """The save state of this moment."""
        stream = io.BytesIO()
        self.pb.save_state(stream)
        return stream.getvalue()

    def save(self, path, compress=False):
        """Write a checkpoint the application and the replay tools both accept. ``compress`` writes
        the state and its manifest gzipped, as the library keeps journal saves."""
        return CheckpointStore(path.parent).write_checkpoint(self.state(), self.manifest(), name=path.name,
                                                             compress=compress)

    def tick(self, frames):
        if frames > 0:
            self.pb.tick(frames, render=self.render)
            self.frame += frames

    def step(self, snapshot):
        """One decision and its actions, through the loop the application plays."""
        self.loop.step(snapshot)

    def stop(self):
        if self.tracer is not None:
            self.tracer.close()
        self.pb.stop(save=False)
