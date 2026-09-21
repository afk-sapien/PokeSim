"""Play a cartridge with the strategic policy and no application around it.

The stall finder and the stuck scenarios share this, so a checkpoint one of them writes replays
in the other and in the application.
"""
from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
import secrets

from pyboy import PyBoy

from .checkpoints import CheckpointStore
from .events import RunMemory
from .policies.base import PolicyContext
from .policies.strategic import StrategicPolicy
from .screen import W_OPTIONS

BLUE_SHA1 = 'd7037c83e1ae5b39bde3c30787637ba1d4c48ce2'


class HeadlessRun:
    def __init__(self, rom, checkpoint=None, seed=7, rng=None, reseed=False):
        self.rom_sha1 = hashlib.sha1(rom.read_bytes()).hexdigest()
        self.pb = PyBoy(str(rom), window='null', sound_emulated=False)
        self.pb.set_emulation_speed(0)
        self.policy = StrategicPolicy(seed)
        self.policy.collection.version = 'blue' if self.rom_sha1 == BLUE_SHA1 else 'red'
        self.memory = RunMemory()
        self.frame = 0
        # A scenario passes its own generator so that a failure replays the same way.
        self.rng = rng
        self.seed = seed
        if checkpoint:
            # A checkpoint carries the policy's own random state, so every run of one checkpoint
            # makes the same choices whatever seed is asked for. Exploring needs the seed to matter;
            # replaying a saved stall needs the original choices, so this is the caller's decision.
            self.frame = self._load(checkpoint, reseed=reseed).get('frame', 0)

    def _load(self, path, reseed=False):
        metadata = CheckpointStore(path.parent).checkpoint_metadata(path)
        if not metadata:
            raise ValueError('A checkpoint manifest is required for a faithful replay')
        if metadata['rom_sha1'] != self.rom_sha1 or metadata['pyboy_version'] != version('pyboy'):
            raise ValueError('ROM or emulator version does not match the checkpoint')
        self.policy.load_state_dict(metadata['policy_state'])
        self.memory = RunMemory.from_dict(metadata['run_memory'])
        if reseed:
            self.policy.rng.seed(self.seed)
        with path.open('rb') as stream:
            self.pb.load_state(stream)
        return metadata

    def reload(self, path):
        """Go back to a checkpoint as the application does after a battle that never ends."""
        self._load(path)
        # The same save and the same choices would replay the same trouble.
        self.pb.tick(1 + (self.rng.randrange(180) if self.rng else secrets.randbelow(180)), render=False)

    def save(self, path):
        """Write a checkpoint the application and the replay tools both accept."""
        with path.open('wb') as stream:
            self.pb.save_state(stream)
        manifest = {'format': 1, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'pyboy_version': version('pyboy'), 'rom_sha1': self.rom_sha1, 'policy': 'strategic',
                    'policy_state': self.policy.state_dict(), 'run_memory': self.memory.to_dict(),
                    'frame': self.frame}
        path.with_suffix('.json').write_text(json.dumps(manifest))

    def step(self, snapshot):
        self.pb.memory[W_OPTIONS] = (self.pb.memory[W_OPTIONS] & ~7) | 1
        for action in self.policy.step(PolicyContext(snapshot, 0, 0, self.pb.memory)):
            if action.button:
                self.pb.button_press(action.button)
            if action.hold:
                self.pb.tick(action.hold, render=False)
            if action.button:
                self.pb.button_release(action.button)
            if action.gap:
                self.pb.tick(action.gap, render=False)
            self.frame += action.hold + action.gap

    def stop(self):
        self.pb.stop(save=False)
