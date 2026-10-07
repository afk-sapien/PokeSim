"""Mixed generation transport with retail Time Capsule conversion routines."""
from copy import deepcopy
import time

from ..interactions.cable import checked
from .cable import CableSide
from .cable_driver import CableDriver

ADAPTER_ID = 'english-rbgsc-core-timecapsule-v1'
COMMUNICATION = {'gold': (16469, 'cdb443cd2744cdc2'), 'silver': (16469, 'cdb443cd2744cdc2'),
                 'crystal': (16477, 'cd2644cd9944cd34')}


def compatible(mon, data):
    return (not mon.egg and 1 <= mon.species <= 151 and all(move <= 165 for move in mon.moves)
            and 'MAIL' not in data.item_names.get(mon.held_item, '').upper())


def unlocked(snapshot, mem):
    return bool(snapshot and snapshot.started and not snapshot.event('EVENT_MET_BILL')
                and not mem.byte('wDailyFlags1') & 8)


class TimeCapsuleSide(CableSide):
    time_capsule = True

    def __init__(self, spec, data):
        super().__init__(spec, data)
        self.sym = deepcopy(self.sym)
        address, signature = COMMUNICATION[data.game]
        self.sym['Gen2ToGen1LinkComms'] = (10, address)
        offset = 10 * 16384 + address % 16384
        checked(self.rom_bytes[offset:offset + 8].hex() == signature, 'Unsupported Time Capsule instruction signature')

    def attach(self, role, enabled=True):
        super().attach(role, enabled)
        self.hook('Gen2ToGen1LinkComms', lambda _: self.counts.update(['Gen2ToGen1LinkComms']))


class MixedDriver:
    def __init__(self, gen1, gen2, plan, progress=None, cancelled=None):
        self.gen1, self.gen2, self.plan = gen1, gen2, plan
        self.progress, self.cancelled = progress, cancelled
        self.gen2_driver = CableDriver([gen2], plan)
        self.started = time.monotonic()

    def gen1_button(self, step):
        from ..screen import Screen
        from ..ram import read_snapshot
        side = self.gen1
        if side.counts['ReturnToCableClubRoom']:
            return None
        screen = Screen(side.pb.memory)
        if side.counts['TradeCenter_SelectMon'] >= 2:
            if screen.cursor and 'CANCEL' in screen.text:
                return 'a' if side.get('wCurrentMenuItem') == side.get('wPartyCount') else 'down'
            return None
        if 'STATS     TRADE' in screen.text:
            return 'right' if screen.top_x == 1 else 'a'
        if (side.counts['TradeCenter_SelectMon'] == 1 and not side.counts['TradeCenter_Trade']
                and screen.cursor and screen.top_y == 1 and screen.top_x == 1 and 'CANCEL' in screen.text):
            current, target = side.get('wCurrentMenuItem'), side.spec.party_slot
            return 'a' if current == target else 'down' if current < target else 'up'
        if read_snapshot(side.pb.memory, side.frame).map == 239 and not side.counts['CableClub_DoBattleOrTrade'] and step % 3 == 0:
            return 'right' if side.get('hSerialConnectionStatus') == 2 else 'left'
        return 'a'

    def run(self):
        sides = (self.gen1, self.gen2)
        for step in range(self.plan.max_steps):
            checked(self.cancelled is None or not self.cancelled.is_set(), 'Time Capsule session cancelled')
            checked(time.monotonic() - self.started < self.plan.timeout_seconds, 'Time Capsule deadline exceeded')
            if self.gen1.counts['ReturnToCableClubRoom'] and self.gen2.counts['ExitLinkCommunications']:
                for _ in range(120):
                    for side in sides:
                        side.tick()
                for side in sides:
                    side.detach()
                return
            for side, button in zip(sides, (self.gen1_button(step), self.gen2_driver.button(self.gen2))):
                if button:
                    side.pb.button_press(button)
            for frame in range(40):
                if frame == 8:
                    for side in sides:
                        side.release_buttons()
                moved = [side.tick() for side in sides]
                checked(any(moved), 'Time Capsule transport deadlock')
            if self.progress and step % 25 == 0:
                self.progress({'phase': 'exchanging', 'steps': step,
                    'sides': {side.spec.adventure_id: dict(side.counts) for side in sides}})
            if self.plan.speed:
                delay = (step + 1) * 40 / (60 * self.plan.speed) - (time.monotonic() - self.started)
                while delay > 0:
                    checked(self.cancelled is None or not self.cancelled.is_set(), 'Time Capsule session cancelled')
                    checked(time.monotonic() - self.started < self.plan.timeout_seconds, 'Time Capsule deadline exceeded')
                    time.sleep(min(0.1, delay))
                    delay = (step + 1) * 40 / (60 * self.plan.speed) - (time.monotonic() - self.started)
        raise ValueError('Time Capsule exhausted its controller step budget')
