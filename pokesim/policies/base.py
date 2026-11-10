from __future__ import annotations

from dataclasses import dataclass

from ..ram import Snapshot

BUTTONS = ("up", "down", "left", "right", "a", "b", "start", "select")


def stack_pointer(emulator):
    """The CPU stack pointer of a running emulator, or None when it is not exposed."""
    return getattr(getattr(emulator, 'register_file', None), 'SP', None)


@dataclass(frozen=True)
class Action:
    """Press `button` for `hold` frames, then release and wait `gap` frames."""
    button: str | None
    hold: int = 8
    gap: int = 2


@dataclass
class PolicyContext:
    snapshot: Snapshot
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


class Policy:
    name = "base"

    def __init__(self, seed=None):
        pass

    def step(self, ctx: PolicyContext) -> list[Action]:
        """Return one or more actions to execute in sequence before being asked again."""
        raise NotImplementedError

    def describe(self) -> str:
        return self.name

    def state_dict(self) -> dict:
        return {}

    def load_state_dict(self, d: dict):
        pass

    def reset(self):
        pass

    def on_restore(self):
        """Discard in-flight actions after a rewind or manual intervention."""
        pass

    def details(self) -> dict:
        return {}

    def goals(self, snapshot, query=None) -> tuple[list[dict], str | None]:
        """The goals a manager can set as the next activity, those named like ``query`` when it is given,
        and why the list is empty."""
        return [], 'This policy has no goal list'

    def pin_goal(self, snapshot, key):
        """Set ``key`` as the next activity. A ValueError says why it cannot be."""
        raise ValueError('This policy has no goal list')

    @property
    def pin(self):
        """The next activity a manager set, or None."""
        return None

    def unpin_goal(self):
        pass

    def drop_pin(self):
        """Drop the pin. Returns the label dropped, or None with no pin."""
        return None
