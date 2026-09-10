from __future__ import annotations

from dataclasses import dataclass

from ..ram import Snapshot

BUTTONS = ("up", "down", "left", "right", "a", "b", "start", "select")


@dataclass(frozen=True)
class Action:
    """Press `button` for `hold` frames, then release and wait `gap` frames."""
    button: str | None
    hold: int = 8
    gap: int = 2


@dataclass
class PolicyContext:
    snapshot: Snapshot
    stuck_seconds: float        # real seconds since (map, x, y) last changed
    real_time: float
    mem: object = None          # live memory view (pyboy.memory) for policies that read the screen


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
