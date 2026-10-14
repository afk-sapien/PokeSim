"""Bounded serial transport for two isolated Generation II cartridges.

The transport is Core's. PokeSim's side still builds and checks its own emulator from a session spec.
"""
from pokesim_core.gen2.cable import CableSide as CoreSide
from pokesim_core.gen2.ram import Memory

from ..interactions.cable import CableSide as BaseSide
from .cable_metadata import BUILDS


class CableSide(BaseSide):
    def __init__(self, spec, data):
        super().__init__(spec, builds=BUILDS)
        self.data = data
        self.memory = Memory(self.pb.memory, data)

    get = CoreSide.get
    put_transport = CoreSide.put_transport
    attach = CoreSide.attach
    exchange = CoreSide.exchange
