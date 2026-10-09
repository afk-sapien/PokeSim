"""Run pokesim-core menu shortcuts one policy decision at a time.

Core shortcut machines return one button, a wait or a ``Done`` per ``step``. The
policies call ``ShortcutRunner.step`` once per decision, so a shortcut shares the
policy loop instead of blocking it. A request that failed is not retried for a
while, which keeps a refused menu from looping.
"""
from pokesim_core.shortcuts import Done

from .policies.base import Action

RETRY_FRAMES = 3600
# Core's own runner holds a button for 8 frames, then waits 36 before the next observation.
PRESS, SETTLE, WAIT = 8, 36, 30


class ShortcutRunner:
    def __init__(self):
        self.machine = None
        self.key = None
        self.purpose = None
        self.on_done = None
        self.last = None
        self.failures = {}

    @property
    def active(self):
        return self.machine is not None

    def cancel(self):
        self.machine = self.on_done = None

    def blocked(self, key, frame):
        return self.failures.get(key, -1) > frame

    def start(self, machine, key, frame, memory, ui=None, purpose='', on_done=None):
        """Begin ``machine`` and return its first actions, or None when it refuses or failed recently."""
        if self.blocked(key, frame):
            return None
        self.machine, self.key, self.purpose, self.on_done = machine, key, purpose, on_done
        return self.step(memory, ui, frame)

    def step(self, memory, ui, frame):
        """Actions for the next input, or None once the machine is done."""
        machine = self.machine
        result = machine.step(memory, ui)
        if isinstance(result, Done):
            callback = self.on_done
            self.cancel()
            self.last = result
            if not result.completed:
                self.failures[self.key] = frame + RETRY_FRAMES
                self.failures = dict(list(self.failures.items())[-64:])
            if callback is not None:
                callback(result, machine)
            return None
        if result is None:
            return [Action(None, 0, WAIT)]
        return [Action(result, PRESS, SETTLE)]


def gen1_ui(sp, yellow):
    """Observation hints for a Gen 1 machine.

    The text-wait check reads the stack, which sits at Yellow addresses that the
    Red-layout view shifts, so Yellow falls back to Core's stable-text rule.
    """
    return {'sp': sp} if sp is not None and not yellow else None
