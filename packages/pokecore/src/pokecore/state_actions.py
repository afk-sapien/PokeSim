"""Observed controller actions with explicit frame budgets.

All inputs use ControllerPort.send so consumers retain locking and recording.
Selection confirms once, then waits for the caller's observed postcondition.
"""

from copy import deepcopy

from .controls import normalize
from .gen1_ui import read_screen
from .menus import menu_options


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value


class _Budget:
    def __init__(self, port, max_frames):
        self.port = port
        self.start = _integer(port.frame(), 'frame')
        self.limit = _integer(max_frames, 'max_frames')
        self.actions = 0
        self.confirmed = False
        self.last = self.start

    def elapsed(self):
        now = _integer(self.port.frame(), 'frame')
        if now < self.last or now - self.start > self.limit:
            raise RuntimeError('Controller violated the frame budget or moved time backwards')
        self.last = now
        return now - self.start

    @property
    def remaining(self):
        return self.limit - self.elapsed()

    def send(self, button, hold, gap):
        count = hold + gap
        if count > self.remaining:
            return 'timeout'
        before = self.elapsed()
        accepted = self.port.send(button, hold, gap)
        self.actions += 1
        advanced = self.elapsed() - before
        if advanced > count:
            raise RuntimeError('Controller advanced beyond the requested action')
        if not accepted:
            return 'consumer_budget'
        if advanced == 0:
            return 'stalled'
        if advanced != count:
            return 'interrupted'
        return None

    def result(self, status, observation):
        return {'status': status, 'completed': status == 'success', 'frames': self.elapsed(),
                'actions': self.actions, 'confirmed': self.confirmed, 'observation': deepcopy(observation)}


def _wait(budget, predicate, poll_frames, allowed_kinds=None):
    while True:
        ui = budget.port.observe()
        if budget.port.stopped():
            return budget.result('stopped', ui)
        if predicate(ui):
            return budget.result('success', ui)
        if allowed_kinds is not None and ui.get('kind') not in allowed_kinds:
            return budget.result('unexpected_state', ui)
        if budget.remaining == 0:
            return budget.result('timeout', ui)
        reason = budget.send(None, min(poll_frames, budget.remaining), 0)
        if reason:
            ui = budget.port.observe()
            return budget.result('success' if predicate(ui) else reason, ui)


def wait_until(port, predicate, *, max_frames, poll_frames=4, allowed_kinds=None):
    """Wait without pressing buttons and succeed only on an observed predicate."""
    if not callable(predicate):
        raise TypeError('predicate must be callable')
    _integer(poll_frames, 'poll_frames', 1)
    return _wait(_Budget(port, max_frames), predicate, poll_frames, allowed_kinds)


def open_menu(port, *, max_frames, menu_kind='menu', held_frames=8, released_frames=24, poll_frames=4):
    """Press Start once from the overworld and verify that a menu appears."""
    _integer(held_frames, 'held_frames', 1)
    _integer(released_frames, 'released_frames')
    _integer(poll_frames, 'poll_frames', 1)
    budget = _Budget(port, max_frames)
    ready = lambda ui: ui.get('kind') == menu_kind
    result = _wait(budget, lambda ui: ready(ui) or ui.get('kind') == 'overworld',
                   poll_frames, {'transition', 'overworld', menu_kind})
    if not result['completed'] or ready(result['observation']):
        return result
    reason = budget.send('start', held_frames, released_frames)
    if reason:
        ui = port.observe()
        return budget.result('success' if ready(ui) else reason, ui)
    return _wait(budget, ready, poll_frames, {'transition', 'overworld', menu_kind})


def select_visible_option(port, label, *, verify, max_frames, held_frames=8, released_frames=24,
                          poll_frames=4, allowed_kinds=('menu', 'battle_menu', 'move_menu'),
                          result_kinds=None):
    """Navigate observed menu coordinates, confirm once and verify the effect.

    Supply ControllerPort.menu_rows for custom layouts. Otherwise use Core's
    observed Red/Blue menu rows. Duplicate labels and unrecognized cursors stop.
    After a timeout with confirmed=True, use wait_until rather than selecting
    again. verify owns the game-specific success condition.
    """
    if not isinstance(label, str) or not normalize(label):
        raise ValueError('label must name a visible option')
    if not callable(verify):
        raise TypeError('verify must be callable')
    _integer(held_frames, 'held_frames', 1)
    _integer(released_frames, 'released_frames')
    _integer(poll_frames, 'poll_frames', 1)
    budget = _Budget(port, max_frames)
    while True:
        ui = port.observe()
        if port.stopped():
            return budget.result('stopped', ui)
        if ui.get('kind') not in allowed_kinds:
            return budget.result('unexpected_state', ui)
        rows = (port.menu_rows() if port.menu_rows is not None else
                menu_options(port.memory, read_screen(port.memory), ui.get('kind')))
        matches = [row for row in rows if normalize(row['text']) == normalize(label)]
        cursor = tuple(ui.get('cursor_tile') or ())
        if len(matches) != 1 or not any(tuple(row['cursor']) == cursor for row in rows):
            return budget.result('unexpected_state', ui)
        target = tuple(matches[0]['cursor'])
        if len(cursor) != 2 or len(target) != 2:
            return budget.result('unexpected_state', ui)
        if cursor == target:
            if normalize(ui.get('selected_text') or '') != normalize(label):
                return budget.result('unexpected_state', ui)
            if held_frames + released_frames > budget.remaining:
                return budget.result('timeout', ui)
            budget.confirmed = True
            reason = budget.send('a', held_frames, released_frames)
            if reason:
                ui = port.observe()
                return budget.result('success' if verify(ui) else reason, ui)
            return _wait(budget, verify, poll_frames, result_kinds)
        button = ('down' if cursor[1] < target[1] else 'up') if cursor[1] != target[1] else (
            'right' if cursor[0] < target[0] else 'left')
        reason = budget.send(button, held_frames, released_frames)
        if reason:
            return budget.result(reason, port.observe())
