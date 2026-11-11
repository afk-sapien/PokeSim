"""Play a cartridge of either generation with its policy and no application around it.

The stall finder, the stuck scenarios, the ladder and the replay tools share this, so a checkpoint one of
them writes replays in the others and in the application. The cartridge picks its generation's adapter
(runtime/adapter.py), and only that generation's code is imported.

A Gen II run keeps the parts of the runtime that decide where the run goes: the clock locked to game
time, the League count past the cartridge's cap, the Mart stock and the recovery the guards start when
the screen stops changing. Rewards, statistics, trades and notifications stay out, since they need an
adventure store.
"""
from __future__ import annotations

import io
from pathlib import Path

from ..checkpoints import CheckpointStore, open_state
from ..seeds import RELOAD_IDLE, reload_idle
from . import trace as runtime_trace
from .adapter import adapter_for
from .game_loop import Decider, GameLoop
from .manifest import checkpoint_manifest
from .policy import BUTTONS
from .supervision import Tables


class HeadlessRun(runtime_trace.HeadlessPins):
    # A tool that saves screenshots renders every frame.
    render = False
    tracer = None

    def __init__(self, rom, checkpoint=None, seed=7, rng=None, trace=None, pins=None, reseed=False,
                 fair_wild_dvs=None, data_root=None):
        """``trace`` is a folder to record the run in, one segment from the start, as an adventure's
        trace folder keeps them. None records nothing. ``pins`` is a trace segment's ``pin_script``, the
        pins a replay of it sets. ``reseed`` gives a loaded checkpoint's policy ``seed`` in place of the
        random state it saved. ``fair_wild_dvs`` rerolls wild DVs in Red, Blue and Yellow, keyed from the
        seed when True or by the bytes given. ``data_root`` is where Gen II reads its game data."""
        rom = Path(rom)
        self.adapter = adapter_for(rom.read_bytes(), data_root)
        self.generation, self.rom_sha1 = self.adapter.generation, self.adapter.sha1
        # A scenario passes its own generator so that a failure replays the same way.
        self.rng, self.seed = rng, seed
        self.frame = 0
        self.adapter.boot(self, rom, trace=trace, fair_wild_dvs=fair_wild_dvs)
        self.policy = self.adapter.new_policy(self, seed)
        # The goals' stand-downs count on the run's frames, which a reload keeps, as the PlayClock does live.
        self.policy.monitor_tables = Tables(clock=lambda: self.frame)
        settings = self.adapter.settings
        options = self.adapter.options if settings.options_each_decision else None
        self.loop = GameLoop(self, Decider(lambda: self.frame, options, wait=settings.wait), self.tick)
        if checkpoint:
            # A checkpoint carries the policy's own random state, so every run of one checkpoint
            # makes the same choices whatever seed is asked for. Exploring needs the seed to matter;
            # replaying a saved stall needs the original choices, so this is the caller's decision.
            self._load(Path(checkpoint), reseed=reseed, first=True)
        else:
            self.adapter.start_fresh(self)
        self.take_pins(pins)
        if self.tracer is not None:
            self.tracer.ensure(self.manifest, self.policy)

    def _load(self, path, reseed=False, first=False):
        metadata = CheckpointStore(path.parent).checkpoint_metadata(path)
        if not metadata:
            raise ValueError('A checkpoint manifest is required for a faithful replay')
        self.adapter.check(metadata)
        self.adapter.before_load(self, first)
        if first:
            # The run counts its frames on from the save's, before the policy reads a wait timed on them.
            # A reload keeps counting, so the frames never go back.
            self.frame = metadata.get('frame', 0)
        with open_state(path) as stream:
            self.pb.load_state(stream)
        for button in BUTTONS:
            self.pb.button_release(button)
        # The load clears the pin and discards in-flight actions, as in the application.
        self.policy.load_state_dict(metadata.get('policy_state', {}))
        if reseed:
            self.policy.rng.seed(self.seed)
        self.adapter.after_load(self, metadata, first)
        return metadata

    def reload(self, path):
        """Go back to a checkpoint as the application's guards do, idling a moment so the trouble differs."""
        frame = self.frame
        with runtime_trace.reason(self, 'reload'):
            self._load(Path(path))
        # The same save and the same choices would replay the same trouble. A scenario's own
        # generator picks the idle, and otherwise the reload stream does, so a rerun idles the same.
        self.tick(1 + self.rng.randrange(RELOAD_IDLE) if self.rng else reload_idle(self.seed, frame))

    def manifest(self):
        """The manifest a checkpoint of this moment carries."""
        return checkpoint_manifest(self.policy, rom_sha1=self.rom_sha1, frame=self.frame,
                                   **self.adapter.manifest_fields(self))

    def state(self):
        """The save state of this moment."""
        self.adapter.before_save(self.pb)
        stream = io.BytesIO()
        self.pb.save_state(stream)
        return stream.getvalue()

    def save(self, path, compress=False):
        """Write a checkpoint the application and the replay tools both accept. ``compress`` writes
        the state and its manifest gzipped, as the library keeps journal saves."""
        return CheckpointStore(path.parent).write_checkpoint(self.state(), self.manifest(), name=path.name,
                                                             compress=compress)

    def read(self):
        """The snapshot of the game as it is now."""
        return self.adapter.read(self)

    def tick(self, frames):
        if frames > 0:
            self.pb.tick(frames, render=self.render)
            self.frame += frames

    def step(self, snapshot):
        """One decision and its actions, through the loop the application plays."""
        self.feed_pins(snapshot)
        self.loop.step(snapshot)
        self.adapter.after_step(self, snapshot)

    def waiting(self, snapshot):
        """Whether the run is waiting on purpose, which the stall watch does not count."""
        return self.adapter.waiting(self, snapshot)

    def stop(self):
        if self.tracer is not None:
            self.tracer.close()
        self.pb.stop(save=False)
