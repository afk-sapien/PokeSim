"""The one policy shape that Red, Blue and Yellow and Gold, Silver and Crystal play through
(docs/design/one-bot.md section 1).

A host asks ``step`` with a ``PolicyContext`` and plays the actions it returns, in both generations.
This module imports no game data, so a Gen II worker never loads Gen I code through it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

BUTTONS = ("up", "down", "left", "right", "a", "b", "start", "select")


def stack_pointer(emulator):
    """The CPU stack pointer of a running emulator, or None when it is not exposed."""
    return getattr(getattr(emulator, 'register_file', None), 'SP', None)


@dataclass(frozen=True)
class Action:
    """Press ``button`` for ``hold`` frames, then release and wait ``gap`` frames. No button waits
    without a press. An action with no ``gap`` waits the generation's own wait after a press, which the
    host plays it with: 2 frames in Gen I and 16 in Gen II."""
    button: str | None = None
    hold: int = 8
    gap: int | None = None

    def frames(self, wait):
        """The frames the action takes when the generation waits ``wait`` after a press."""
        return self.hold + (wait if self.gap is None else self.gap)


@dataclass
class PolicyContext:
    snapshot: object            # the generation's ram.Snapshot
    clock: int = 0              # game frames that never rewind: PlayClock frames, or the run's frame count
    mem: object = None          # live memory view (pyboy.memory) for policies that read the screen
    sp: int | None = None       # CPU stack pointer, for Core's continue-only text check

    def __post_init__(self):
        # The old form passed two numbers before the memory, which would land in mem and sp.
        if isinstance(self.mem, (int, float)):
            raise TypeError('PolicyContext takes (snapshot, clock, mem, sp). stuck_seconds and real_time are gone')


class Stillness:
    """Frames the player has stood on one tile outside battle, read on the context clock. Each
    policy keeps its own, so no decision reads the wall clock."""

    def __init__(self):
        self.pos = self.since = None

    def frames(self, ctx):
        s = ctx.snapshot
        pos = (s.map, s.x, s.y)
        if (self.since is None or ctx.clock < self.since or pos != self.pos
                or s.in_battle or not s.started):
            self.pos, self.since = pos, ctx.clock
        return ctx.clock - self.since


class Policy(Protocol):
    """What a host asks of a policy. The policies of both generations subclass it by name, which gives
    them the defaults below, so a policy with no goal list still answers every call."""

    name = 'base'
    # The next activity a manager set (planning/pin.py), or None. Never saved.
    pin = None

    def step(self, ctx: PolicyContext) -> list[Action]:
        """One or more actions to play in order before the policy is asked again."""
        raise NotImplementedError

    def describe(self) -> str:
        return self.name

    def state_dict(self) -> dict:
        """The policy's save. A policy with state saves it under a ``version`` its load checks."""
        return {}

    def load_state_dict(self, state: dict):
        """Take a save back. The load clears the pin, which belongs to the moment it was set, and calls
        ``on_restore`` itself, so a caller does neither."""

    def on_restore(self):
        """Discard in-flight actions after a rewind or manual intervention."""

    def reset(self):
        """Start over for a new game."""

    def details(self) -> dict:
        return {}

    def goal_record(self) -> dict | None:
        """The goal that runs now in the shape both generations share (docs/design/typed-goals.md
        section 4), or None."""
        return None

    def hopeless_battle(self, snapshot) -> bool:
        """Whether the battle under way can never end, so waiting out the battle timeout gains nothing."""
        return False

    def goals(self, snapshot, query=None) -> tuple[list[dict], str | None]:
        """The goals a manager can set as the next activity, those named like ``query`` when it is given,
        and why the list is empty."""
        return [], 'This policy has no goal list'

    def catalogue(self, snapshot, query=None, limit=None) -> dict:
        """The goal catalogue (planning/catalogue.py). A ValueError says why there is none."""
        raise ValueError('This policy has no goal list')

    def pin_goal(self, snapshot, key):
        """Set ``key`` as the next activity. A ValueError says why it cannot be."""
        raise ValueError('This policy has no goal list')

    def unpin_goal(self):
        """Clear the next activity."""

    def drop_pin(self):
        """Drop the pin. Returns the label dropped, or None with no pin."""
        return None

    def restore_pin(self, pin):
        """Put back the pin a replayed pin script set, as it was logged."""
        raise ValueError('This policy has no goal list')
