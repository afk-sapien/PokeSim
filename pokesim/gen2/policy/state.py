"""Goals and the saved state of the Generation II policy."""
from __future__ import annotations

from dataclasses import dataclass, field, fields

from ...planning.stance import STORY

STUCK_WAITS = 40  # consecutive 24-frame waits (about 16 seconds of game time) before reporting a blocked objective


@dataclass(frozen=True)
class Goal:
    key: str
    label: str
    map_name: str
    x: int
    y: int
    face: str | None = None
    # The goal kind the battle stance follows (planning/stance.py): story, travel, train or hunt.
    kind: str = STORY


# The version Policy.state_dict writes. Version 1 kept the heal and shop errands in flat keys.
SAVE_VERSION = 2


@dataclass
class Saved:
    """The policy state a save keeps, written under ``SAVE_VERSION``.

    Each errand keeps its own state under ``errands`` by its key. A save from before the version was
    written is version 1, whose flat ``healing_map``, ``shopping`` and ``shop_location`` keys read as
    the heal and shop errands' state. A version this build does not know reads as nothing. Other
    readers find the ``menu`` (runtime/reload.py) and the ``collection`` (trade/pair.py) at the top.
    """
    starter: str | None = None
    rng: object = None
    completed: dict = field(default_factory=dict)
    collection: dict = field(default_factory=lambda: {'target': None})
    demand: dict = field(default_factory=dict)
    decisions: int = 0
    naming: dict = field(default_factory=dict)
    learning: bool = False
    partner_move: object = None
    menu: dict | None = None
    errands: dict = field(default_factory=dict)
    interaction: object = None
    resetting_puzzle: object = None
    objects: dict = field(default_factory=dict)

    def to_dict(self):
        return {'version': SAVE_VERSION, **{entry.name: getattr(self, entry.name) for entry in fields(self)}}

    @classmethod
    def read(cls, state):
        version = state.get('version', 1)
        if version == 1:
            errands = {'heal': {'map': state.get('healing_map')},
                       'shop': {'purchase': state.get('shopping'), 'location': state.get('shop_location')}}
        elif version == SAVE_VERSION:
            errands = state.get('errands', {})
        else:
            return None
        return cls(errands=errands, **{entry.name: state[entry.name] for entry in fields(cls)
                                       if entry.name != 'errands' and entry.name in state})
