"""Play a Gen II cartridge with its policy and no application around it.

The stuck scenarios replay Gold, Silver and Crystal checkpoints with this. It keeps the parts of the
managed runtime that decide where the run goes: the clock locked to game time, the League count
past the cartridge's cap, the Mart stock, and the recovery the guards start when the screen stops
changing. Rewards, statistics, trades and notifications stay out, since they need an adventure store.
"""
from __future__ import annotations

from pathlib import Path
import secrets

from pokecore.emulator_state import validate_runtime
from pokecore.gen2.clock import boot, clock_elapsed, follow_game_time
from pokecore.gen2.ram import read_snapshot

from .. import config
from ..checkpoints import CheckpointStore, open_state
from ..experimental.gen2 import identify
from .data import GameData
from .emulator import BUTTONS, SCREEN_FRAMES, count_league
from .policy import Policy
from .store_stock import StoreStock


class HeadlessRun:
    generation = 2

    def __init__(self, rom, checkpoint, seed=7, rng=None, data_root=None):
        rom = Path(rom)
        profile = identify(rom.read_bytes())
        self.rom_sha1, self.game = profile.sha1, profile.game
        self.data = GameData.load(data_root, self.game)
        self.pb = boot(str(rom), sound=False)
        self.pb.set_emulation_speed(0)
        follow_game_time(self.pb)
        StoreStock(self.data).attach(self.pb)
        self.policy = Policy(self.data, seed=seed)
        self.history = {'maps': [], 'owned': [], 'badges': 0, 'league': 0}
        self.rng, self.seed = rng, seed
        self.frame = self.screen_frame = 0
        self.screen_key = None
        self.clock = None
        self._load(Path(checkpoint))

    def _load(self, path):
        metadata = CheckpointStore(path.parent).checkpoint_metadata(path)
        if not metadata:
            raise ValueError('A checkpoint manifest is required for a faithful replay')
        if metadata.get('rom_sha1') != self.rom_sha1 or metadata.get('generation') != 2:
            raise ValueError('This checkpoint belongs to a different cartridge')
        validate_runtime(metadata)
        with open_state(path) as stream:
            self.pb.load_state(stream)
        # Gen II reads a clock earlier than its saved time as a reset, so a reload resumes at the
        # furthest reading, as the managed runtime does.
        readings = [value for value in (metadata.get('rtc_elapsed'), self.clock) if isinstance(value, (int, float))]
        self.clock = follow_game_time(self.pb, max(readings) if readings else None)
        for button in BUTTONS:
            self.pb.button_release(button)
        self.frame = self.screen_frame = metadata.get('frame', 0)
        self.screen_key = None
        self.policy.load_state_dict(metadata.get('policy_state', {}))
        self.policy.on_restore()
        self.history = metadata.get('gen2_history') or self.history
        self._options()
        return metadata

    def _options(self):
        # The text speed and battle animations the managed runtime sets after every load.
        bank, address = self.data.symbols['wOptions']
        value = self.pb.memory[bank, address]
        if config.FAST_TEXT:
            value = value & ~7 | 1
        self.pb.memory[bank, address] = value & ~128 if config.BATTLE_ANIMATIONS else value | 128

    def reload(self, path):
        """Go back to a checkpoint as the guards do, idling a random moment so the trouble differs."""
        self.clock = clock_elapsed(self.pb)
        self._load(Path(path))
        self.policy.menu = None
        self.tick(1 + (self.rng.randrange(180) if self.rng else secrets.randbelow(180)))

    def read(self):
        return count_league(self.history, self.data, read_snapshot(self.pb.memory, self.data, self.frame), observe=True)

    def tick(self, frames):
        if frames > 0:
            self.pb.tick(frames, render=False)
            self.frame += frames

    def step(self, snapshot):
        action = self.policy.step(snapshot, self.pb.memory)
        if action.button:
            self.pb.button_press(action.button)
        try:
            self.tick(action.hold)
        finally:
            if action.button:
                self.pb.button_release(action.button)
        self.tick(action.gap)
        screen = hash((snapshot.tiles, snapshot.map, snapshot.x, snapshot.y, snapshot.in_battle))
        if screen != self.screen_key:
            self.screen_key, self.screen_frame = screen, self.frame
        elif self.frame - self.screen_frame >= SCREEN_FRAMES:
            # The guards back out of a screen that stopped changing, then mix in other buttons.
            self.policy.recover(1 if self.policy.recoveries % 3 == 0 else 2)
            self.screen_frame = self.frame

    def waiting(self, snapshot):
        """Waiting for the cartridge clock is the plan, so the stall watch does not count it."""
        return bool(self.policy.idle(snapshot) or self.policy.waiting(snapshot))

    def stop(self):
        self.pb.stop(save=False)
