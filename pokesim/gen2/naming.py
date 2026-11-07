"""Enter configured names using the cartridge's naming keyboard."""
from __future__ import annotations

import random

from .. import config
from ..nicknames import TRAINER_NAMES, configured_pool


# Typing one name takes well under this many presses. Past it, accept what is on screen.
MAX_STEPS = 600


def decline(snapshot):
    """B answers NO at a nickname prompt when nicknames are off or the pool is empty."""
    from .menus import menu_label
    rows = snapshot.tiles
    yes = next((i for i, row in enumerate(rows[:12]) if menu_label(row) == 'YES'), None)
    if yes is None or yes + 1 >= 12 or menu_label(rows[yes + 1]) != 'NO' or '▶' not in rows[yes] + rows[yes + 1]:
        return None
    if 'NICKNAME' not in ''.join(' '.join(rows[12:]).upper().split()) or configured_pool():
        return None
    return 'b'


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
            return decline(snapshot)
        self.steps += 1
        if self.steps > MAX_STEPS:
            # START jumps to END and A accepts the name typed so far, so the screen always closes.
            return 'a' if self.steps % 2 else 'start'
        subject = mem.byte('wNamingScreenType') & 7
        if subject == 0 and not configured_pool():
            # The prompt was answered YES before nicknames went off. The game keeps the species
            # name when END accepts a blank name.
            self.target = ''
            self.subject = subject
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
        if not self.target and length:
            return 'b'   # B deletes a letter, so a half typed nickname is cleared first.
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
