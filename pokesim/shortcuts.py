"""Run pokecore menu shortcuts one policy decision at a time.

Core shortcut machines return one button, a wait or a ``Done`` per ``step``. The
policies call ``ShortcutRunner.step`` once per decision, so a shortcut shares the
policy loop instead of blocking it. A request that failed is not retried for a
while, which keeps a refused menu from looping. The wait is ``REFUSED_SHORTCUT``
on the caller's clock, which the policy passes as the PlayClock frame.
"""
from pokecore.shortcuts import Done

from .runtime.policy import Action
from .runtime.supervision import REFUSED_SHORTCUT

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

    def blocked(self, key, clock):
        return self.failures.get(key, -1) > clock

    def start(self, machine, key, clock, memory, ui=None, purpose='', on_done=None):
        """Begin ``machine`` and return its first actions, or None when it refuses or failed recently."""
        if self.blocked(key, clock):
            return None
        self.machine, self.key, self.purpose, self.on_done = machine, key, purpose, on_done
        return self.step(memory, ui, clock)

    def step(self, memory, ui, clock):
        """Actions for the next input, or None once the machine is done."""
        machine = self.machine
        result = machine.step(memory, ui)
        if isinstance(result, Done):
            callback = self.on_done
            self.cancel()
            self.last = result
            if not result.completed:
                self.failures[self.key] = REFUSED_SHORTCUT.until(clock)
                self.failures = dict(list(self.failures.items())[-64:])
            if callback is not None:
                callback(result, machine)
            return None
        if result is None:
            return [Action(None, 0, WAIT)]
        return [Action(result, PRESS, SETTLE)]


def gen1_ui(sp):
    """Observation hints for a Gen 1 machine: the stack pointer, which Core's text-wait check reads.

    Core 0.9.5 reads Yellow's stack too, so every Gen 1 game passes it. With no stack pointer
    Core falls back to its stable-text rule, and pc_list guards the slots that rule cannot reach.
    """
    return {'sp': sp} if sp is not None else None
