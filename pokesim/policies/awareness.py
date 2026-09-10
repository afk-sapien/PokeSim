"""Bounded action verification and cycle detection, independent of UI controls."""
from collections import deque


def progress_token(s):
    return (s.map, s.badges, s.items, s.event_flags,
            tuple((p.species, p.hp, p.status, p.level, p.moves, p.pp) for p in s.party))


class ActionWatch:
    def __init__(self):
        self.samples = deque(maxlen=12)
        self.last_progress = None
        self.last_sample = None
        self.expected = None
        self.last_failure = -10000

    def begin(self, kind, label, s, value):
        if self.expected and self.expected['kind'] == kind and self.expected['value'] == value:
            return
        self.expected = {'kind': kind, 'label': label, 'frame': s.frame,
                         'position': (s.map, s.x, s.y), 'value': value}

    def observe(self, s, kind, cursor, walk_state, training=False):
        if s.in_battle:
            self.expected = None
        expected = self.expected
        if expected:
            value = self.value(expected['kind'], s, kind, walk_state)
            if value != expected['value']:
                self.expected = None
            elif s.frame - expected['frame'] > (1500 if expected['kind'] == 'item' else 480):
                self.expected = None
                return 'No result from: ' + expected['label']
        progress = progress_token(s)
        if progress != self.last_progress or s.in_battle or training:
            self.samples.clear()
            self.last_progress = progress
            self.last_sample = None
        if s.in_battle or training or s.frame - self.last_failure < 600:
            return None
        sample = ((s.map, s.x, s.y), kind, cursor)
        if sample != self.last_sample:
            self.samples.append(sample)
            self.last_sample = sample
        history = list(self.samples)
        for size in (2, 3, 4):
            if len(history) >= size * 3 and history[-size:] == history[-2 * size:-size] == history[-3 * size:-2 * size]:
                self.samples.clear()
                self.last_failure = s.frame
                return 'Repeated movement or menu cycle without progress'
        return None

    @staticmethod
    def value(kind, s, screen_kind, walk_state):
        if kind == 'move':
            return (s.map, s.x, s.y)
        if kind == 'field':
            return ((s.map, s.x, s.y), walk_state)
        if kind == 'item':
            return (s.items, tuple((p.hp, p.status, p.moves, p.pp) for p in s.party))
        return screen_kind
