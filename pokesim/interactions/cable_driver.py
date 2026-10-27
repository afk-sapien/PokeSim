"""Input-only gameplay driver for a negotiated Cable Club exchange.

Core's driver presses the buttons. PokeSim supplies its own snapshots and walks each side to
the attendant with its own navigator.
"""
from __future__ import annotations

from pokecore.gen1_cable import CableDriver as CoreCableDriver
from pokecore.gen1_cable import CLUB_MAP, FACING_UP, PLAYER_FACING, WALK_COUNTER  # noqa: F401  (re-exported)


class CableDriver(CoreCableDriver):
    def __init__(self, sides, plan, progress=None, cancelled=None):
        super().__init__(sides, plan, progress, cancelled, walk=self.walk_to)
        self.navigators = {}

    def snapshot(self, side):
        from pokesim.ram import read_snapshot
        return read_snapshot(side.pb.memory, side.frame)

    def enter(self):
        self.navigators = {}
        return super().enter()

    def walk_to(self, side, snapshot, target):
        """The next button toward ``target``, from a navigator that belongs to ``side``."""
        from pokesim.policies.navigation import Navigator
        nav = self.navigators.setdefault(id(side), Navigator())
        nav.update_live(snapshot, side.pb.memory)
        return nav.route((snapshot.map, snapshot.x, snapshot.y), [target], side.frame)
