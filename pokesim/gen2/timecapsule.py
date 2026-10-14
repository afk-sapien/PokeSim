"""Mixed generation transport with retail Time Capsule conversion routines.

Core owns the Time Capsule rules, the instruction signature and the mixed driver. PokeSim keeps
its spec-built Gen 2 side, the unlock check and the snapshot form of ``compatible``.
"""
from copy import deepcopy

from pokesim_core.gen2.cable import MixedDriver as CoreMixedDriver
from pokesim_core.timecapsule import COMMUNICATION, COMMUNICATION_BANK, communication_ok
from pokesim_core.timecapsule import compatible as core_compatible

from ..interactions.cable import checked
from .cable import CableSide
from .cable_driver import CableDriver, walk

ADAPTER_ID = 'english-rbgsc-core-timecapsule-v1'


def compatible(mon, data):
    """Whether a party Pokémon may enter the Time Capsule. ``data`` is kept for callers."""
    return core_compatible(mon.species, mon.moves, mon.held_item, egg=mon.egg)


def unlocked(snapshot, mem):
    return bool(snapshot and snapshot.started and not snapshot.event('EVENT_MET_BILL')
                and not mem.byte('wDailyFlags1') & 8)


class TimeCapsuleSide(CableSide):
    time_capsule = True

    def __init__(self, spec, data):
        super().__init__(spec, data)
        self.sym = deepcopy(self.sym)
        address, _ = COMMUNICATION[data.game]
        self.sym['Gen2ToGen1LinkComms'] = (COMMUNICATION_BANK, address)
        checked(communication_ok(self.rom_bytes, data.game), 'Unsupported Time Capsule instruction signature')

    def attach(self, role, enabled=True):
        super().attach(role, enabled)
        self.hook('Gen2ToGen1LinkComms', lambda _: self.counts.update(['Gen2ToGen1LinkComms']))


class MixedDriver(CoreMixedDriver):
    def __init__(self, gen1, gen2, plan, progress=None, cancelled=None):
        super().__init__(gen1, gen2, plan, progress, cancelled, walk=walk)
        self.gen2_driver = CableDriver([gen2], plan)
