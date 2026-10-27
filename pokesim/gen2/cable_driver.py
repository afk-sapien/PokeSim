"""Drive the retail Cable Club with ordinary controller input.

Core's driver presses the buttons. PokeSim walks each side with its own navigator.
"""
from pokecore.gen2.cable import TRADE_ROOMS
from pokecore.gen2.cable import CableDriver as CoreDriver
from pokecore.gen2.ram import read_snapshot

from .navigation import Navigator


class CableDriver(CoreDriver):
    def __init__(self, sides, plan, progress=None, cancelled=None):
        super().__init__(sides, plan, progress, cancelled, walk=walk)
        for side in sides:
            side.nav = Navigator(side.data)

    def button(self, side):
        # The navigator sees every frame the driver acts on, not only the walking ones.
        side.nav.observe(read_snapshot(side.pb.memory, side.data, side.frame))
        return super().button(side)


def walk(side, snapshot, target):
    """The next button toward ``target`` (map, x, y), from the navigator that belongs to ``side``."""
    map_id, x, y = target
    if map_id == snapshot.map and side.data.maps[snapshot.map]['constant'] in TRADE_ROOMS:
        path = side.nav.local(snapshot, [(x, y)], side.pb.memory)
    else:
        path = side.nav.toward(snapshot, map_id, [(x, y)], side.pb.memory)
    return path[0] if path else None
