"""Enter configured names using the cartridge's naming keyboard."""
from __future__ import annotations

import random

from .. import config
from ..nicknames import TRAINER_NAMES, configured_pool


# Typing one name takes well under this many presses. Past it, accept what is on screen.
MAX_STEPS = 600


class Naming:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.target = None
        self.subject = None
        self.used = set()
        self.steps = 0

    def state_dict(self):
        return {'target': self.target, 'subject': self.subject, 'used': sorted(self.used)}

    def load_state_dict(self, state):
        self.target = state.get('target')
        self.subject = state.get('subject')
        self.used = set(state.get('used', []))

    def step(self, snapshot, mem):
        if 'DEL' not in snapshot.text or 'END' not in snapshot.text:
            self.target = self.subject = None
            self.steps = 0
            return None
        self.steps += 1
        if self.steps > MAX_STEPS:
            # START jumps to END and A accepts the name typed so far, so the screen always closes.
            return 'a' if self.steps % 2 else 'start'
        subject = mem.byte('wNamingScreenType') & 7
        if self.target is None or self.subject != subject:
            pool = configured_pool() if subject == 0 else TRAINER_NAMES
            preferred = getattr(config, 'TRAINER_NAME', '') if subject == 1 else getattr(config, 'RIVAL_NAME', '') if subject == 2 else ''
            occupied = self.used | {snapshot.player_name, snapshot.rival_name} | {mon.nick for mon in snapshot.party}
            self.target = preferred or self.rng.choice([name for name in pool if name not in occupied] or pool)
            self.target = self.target.upper()[:10 if subject == 0 else 7]
            self.subject = subject
            self.used.add(self.target)
        length = mem.byte('wNamingScreenCurNameLength')
        pointer = int.from_bytes(mem.read('wNamingScreenCursorObjectPointer', 2), 'little')
        if not 0xC000 <= pointer < 0xD000:
            return None
        cursor = mem.raw(0, pointer, 16)
        x, y = cursor[12], cursor[13]
        if length >= len(self.target):
            return 'a' if y == 4 and x >= 6 else 'start'
        letter = self.target[length]
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ -?!/.,'
        index = alphabet.find(letter)
        if index < 0:
            index = 26
        target_x, target_y = index % 9, index // 9
        if mem.byte('wNamingScreenLetterCase'):
            return 'select'
        if y != target_y:
            return 'down' if y < target_y else 'up'
        if x != target_x:
            return 'right' if x < target_x else 'left'
        return 'a'
