"""Bounded serial transport and Cable Club drivers for Gold, Silver and Crystal.

``CableSide`` runs the Gen 1 ``CableEndpoint`` transport over the Gen 2 link routines
in ``gen2_link_metadata``. ``TimeCapsuleSide`` adds the Time Capsule routine, so a Gen 2
side can trade with a Gen 1 ``CableEndpoint``. ``CableDriver`` and ``MixedDriver`` press
the controller buttons of one trade. Route finding stays with the caller, who passes
``walk(side, snapshot, target)``: the next button toward ``target`` (map, x, y), or None.
Building the emulators, checking the cartridges and adopting the result also stay there.
"""
from copy import deepcopy
import time

from ..centers import screen
from ..gen1 import W_CUR_MAP
from ..gen1_cable import CableEndpoint, CableError as CableError, checked
from ..textmatch import has_word
from ..timecapsule import COMMUNICATION, COMMUNICATION_BANK, communication_ok
from .ram import Memory, read_snapshot

# Raised when Gold, Silver or Crystal reports the incoming Pokémon "appears to be abnormal".
ABNORMAL = 'The Gold, Silver or Crystal game rejected the incoming Pokémon as abnormal'
CLUB_MAP = 239
FACING = {'up': 4, 'left': 8, 'right': 12}
TRADE_ROOMS = frozenset({'TRADE_CENTER', 'TIME_CAPSULE'})


class CableSide(CableEndpoint):
    """One Gen 2 cartridge on the virtual cable.

    ``symbols`` are a ``gen2_link_metadata`` build's symbols, ``data`` the game tables
    (``gen2.GameTables`` or the same shape). Check the build's signatures first.
    """

    def __init__(self, emulator, symbols, data, max_queue=4):
        super().__init__(emulator, symbols, max_queue)
        self.data = data
        self.memory = Memory(emulator.memory, data)

    def get(self, key):
        bank, address = self.sym[key] if key in self.sym else self.data.symbols[key]
        return self.memory.raw(bank, address, 1)[0]

    def put_transport(self, key, value):
        bank, address = self.sym[key]
        if 0xC000 <= address < 0xE000:
            self.pb.memory[bank, address] = value
        else:
            self.pb.memory[address] = value

    def attach(self, role, enabled=True):
        checked(not self.attached and self.peer is not None, 'Invalid cable attachment')
        checked(role in (1, 2), 'Invalid clock role')
        self.attached = True
        self.pb.memory[0, 0x3ff0] = 0x18
        self.pb.memory[0, 0x3ff1] = 0xfe
        if enabled:
            def connect(_):
                self.counts['connect'] += 1
                self.put_transport('hSerialConnectionStatus', role)
            self.hook('WaitForLinkedFriend.loop', connect)
            self.hook('Serial_ExchangeByte', lambda _: self.exchange('byte', 'hSerialSend'))
            self.hook('WaitLinkTransfer', lambda _: self.exchange('nybble', 'wPlayerLinkAction'))
        for key in ('Gen2ToGen2LinkComms', 'LinkTrade', 'LinkTrade.save', 'SaveAfterLinkTrade', 'CloseLink',
                    'ExitLinkCommunications'):
            self.hook(key, lambda _, key=key: self.counts.update([key]))

    def exchange(self, kind, source):
        checked(self.peer is not None, 'Missing cable peer')
        self.counts[kind + '_calls'] += 1
        if self.pending is None:
            queue = self.peer.inbox[kind]
            checked(len(queue) < self.max_queue, 'Cable message queue overflow')
            queue.append(self.get(source))
            self.pending = kind
        checked(self.pending == kind, 'Cable exchange ordering mismatch')
        rf = self.pb.register_file
        checked(0xc000 <= rf.SP < 0xfffe, 'Invalid cable return stack')
        if not self.inbox[kind]:
            self.parked = (rf.PC, rf.SP, self.pb.memory[0xffff])
            self.pb.memory[0xffff] = 0
            rf.PC = 0x3ff0
            return
        value = self.inbox[kind].popleft()
        self.pending = None
        self.counts[kind + '_exchanged'] += 1
        if kind == 'nybble':
            self.put_transport('wOtherPlayerLinkAction', value)
            self.put_transport('wOtherPlayerLinkMode', value)
        else:
            self.put_transport('hSerialReceive', value)
            self.put_transport('hSerialReceivedNewData', 0)
        target = self.pb.memory[rf.SP] | self.pb.memory[rf.SP + 1] << 8
        checked(0 < target < 0x8000 and target != 0x3ff0, 'Invalid cable return address')
        rf.A = value
        rf.PC = target
        rf.SP += 2


class TimeCapsuleSide(CableSide):
    """A Gen 2 side that also counts Gen2ToGen1LinkComms, after checking its instructions in ``rom``."""
    time_capsule = True

    def __init__(self, emulator, symbols, data, rom, max_queue=4):
        super().__init__(emulator, symbols, data, max_queue)
        self.sym = deepcopy(self.sym)
        address, _ = COMMUNICATION[data.game]
        self.sym['Gen2ToGen1LinkComms'] = (COMMUNICATION_BANK, address)
        checked(communication_ok(rom, data.game), 'Unsupported Time Capsule instruction signature')

    def attach(self, role, enabled=True):
        super().attach(role, enabled)
        self.hook('Gen2ToGen1LinkComms', lambda _: self.counts.update(['Gen2ToGen1LinkComms']))


def _pace(started, step, speed, cancelled, message, deadline=None):
    delay = (step + 1) * 40 / (60 * speed) - (time.monotonic() - started)
    while delay > 0:
        checked(cancelled is None or not cancelled.is_set(), message)
        if deadline is not None:
            checked(time.monotonic() - started < deadline[0], deadline[1])
        time.sleep(min(delay, 0.1))
        delay = (step + 1) * 40 / (60 * speed) - (time.monotonic() - started)


class CableDriver:
    """Drive the retail Cable Club with ordinary controller input until both sides leave.

    ``plan`` needs ``max_steps``, ``timeout_seconds`` and ``speed`` (0 runs unpaced).
    Each side offers ``side.party_slot``. ``data.map_ids`` must name ``POKECENTER_2F``
    and ``data.maps`` must give each map's ``constant``.
    """

    def __init__(self, sides, plan, progress=None, cancelled=None, *, walk=None):
        self.sides, self.plan = sides, plan
        self.progress, self.cancelled = progress, cancelled
        self.walk = walk
        self.started = time.monotonic()

    def button(self, side):
        """The next button for ``side``, or None to wait."""
        s = read_snapshot(side.pb.memory, side.data, side.frame)
        m = side.memory
        link = 'Gen2ToGen1LinkComms' if getattr(side, 'time_capsule', False) else 'Gen2ToGen2LinkComms'
        name = side.data.maps.get(s.map, {}).get('constant')
        if side.counts['ExitLinkCommunications']:
            return None
        if side.counts['SaveAfterLinkTrade'] and side.counts[link] >= 2:
            return 'a' if any('▶' in row and 'CANCEL' in row for row in s.tiles) else 'down'
        if side.counts[link]:
            # The game cancels the trade by itself after this message and goes back to the
            # party menu, so pressing on would only repeat it until the step budget ran out.
            checked('appears' not in s.text or 'abnormal' not in s.text, ABNORMAL)
            if 'STATS' in s.text and 'TRADE' in s.text:
                row = next(r for r in s.tiles if 'STATS' in r and 'TRADE' in r)
                cursor = max(row.find('▶'), row.find('▷'))
                return 'right' if cursor < 10 else 'a'
            if 'EXP POINTS' in s.text:
                return 'b'
            if 'CANCEL' in s.text and 'TRADE' in s.text:
                return _choose(s.tiles, 'TRADE') or 'a'
            if any(mon.name.upper() in s.text.upper() for mon in s.party) and 'CANCEL' in s.text:
                cursor = m.byte('wMenuCursorY') - 1
                target = side.party_slot
                return 'a' if cursor == target else 'down' if cursor < target else 'up'
            return 'a'
        if 'TURN OFF' in s.text:
            return (_choose(s.tiles, 'TURN OFF') or 'b') if 'whose PC' in s.text else 'b'
        if 'CHANGE BOX' in s.text or 'Choose a' in s.text or 'STATS' in s.text:
            return 'b'
        if '┌' in s.tiles[12] or m.byte('wScriptRunning') and name not in TRADE_ROOMS:
            return 'a'
        if name in TRADE_ROOMS:
            occupied = {(x, y) for _, x, y in s.objects}
            point, face = ((6, 4), 'left') if (3, 4) in occupied else ((3, 4), 'right')
            target = (s.map, *point)
        else:
            point = (13, 4) if getattr(side, 'time_capsule', False) else (5, 3)
            target = (side.data.map_ids['POKECENTER_2F'], *point)
            face = 'up'
        if (s.map, s.x, s.y) == target:
            return face if m.byte('wPlayerDirection') & 12 != FACING[face] else 'a'
        checked(self.walk is not None, 'The Cable Club driver needs a walk callable')
        return self.walk(side, s, target) or None

    def run(self):
        for step in range(self.plan.max_steps):
            checked(self.cancelled is None or not self.cancelled.is_set(), 'Cable session cancelled')
            checked(time.monotonic() - self.started < self.plan.timeout_seconds, 'Cable session deadline exceeded')
            if all(side.counts['ExitLinkCommunications'] for side in self.sides):
                for _ in range(120):
                    for side in self.sides:
                        side.tick()
                for side in self.sides:
                    side.detach()
                return
            for side in self.sides:
                button = self.button(side)
                if button:
                    side.pb.button_press(button)
            for frame in range(40):
                if frame == 8:
                    for side in self.sides:
                        side.release_buttons()
                moved = [side.tick() for side in self.sides]
                checked(any(moved), 'Both cable endpoints are parked')
            if self.progress and step % 25 == 0:
                self.progress({'phase': 'exchanging', 'steps': step,
                               'sides': {side.label: {'frame': side.frame, 'transport': dict(side.counts)}
                                         for side in self.sides}})
            if self.plan.speed:
                _pace(self.started, step, self.plan.speed, self.cancelled, 'Cable session cancelled')
        raise ValueError('Cable session exhausted its controller step budget')


def _choose(rows, label):
    """The button that moves the ▶ cursor to the row naming ``label``, or None."""
    target = next((i for i, row in enumerate(rows) if has_word(row.casefold(), label.casefold())), None)
    cursor = next((i for i, row in enumerate(rows) if '▶' in row), None)
    if target is None or cursor is None:
        return None
    return 'a' if target == cursor else 'down' if target > cursor else 'up'


class MixedDriver:
    """Drive a Time Capsule trade between a Gen 1 ``CableEndpoint`` and a ``TimeCapsuleSide``.

    The Gen 1 side starts in the Cable Club, the Gen 2 side anywhere ``walk`` reaches
    the Pokémon Center 2F from. The Gen 1 side's memory must be Red-layout.
    """

    def __init__(self, gen1, gen2, plan, progress=None, cancelled=None, *, walk=None):
        self.gen1, self.gen2, self.plan = gen1, gen2, plan
        self.progress, self.cancelled = progress, cancelled
        self.gen2_driver = CableDriver([gen2], plan, walk=walk)
        self.started = time.monotonic()

    def gen1_button(self, step):
        side = self.gen1
        if side.counts['ReturnToCableClubRoom']:
            return None
        view = screen(side.pb.memory)
        if side.counts['TradeCenter_SelectMon'] >= 2:
            if view.cursor and 'CANCEL' in view.text:
                return 'a' if side.get('wCurrentMenuItem') == side.get('wPartyCount') else 'down'
            return None
        if 'STATS     TRADE' in view.text:
            return 'right' if view.top_x == 1 else 'a'
        if (side.counts['TradeCenter_SelectMon'] == 1 and not side.counts['TradeCenter_Trade']
                and view.cursor and view.top_y == 1 and view.top_x == 1 and 'CANCEL' in view.text):
            current, target = side.get('wCurrentMenuItem'), side.party_slot
            return 'a' if current == target else 'down' if current < target else 'up'
        if side.counts['TradeCenter_SelectMon'] == 1 and not side.counts['TradeCenter_Trade'] and not view.cursor:
            # Yellow draws the party menu fast enough to take a held A as a choice of the first slot.
            return None
        if side.pb.memory[W_CUR_MAP] == CLUB_MAP and not side.counts['CableClub_DoBattleOrTrade'] and step % 3 == 0:
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
                               'sides': {side.label: dict(side.counts) for side in sides}})
            if self.plan.speed:
                _pace(self.started, step, self.plan.speed, self.cancelled, 'Time Capsule session cancelled',
                      (self.plan.timeout_seconds, 'Time Capsule deadline exceeded'))
        raise ValueError('Time Capsule exhausted its controller step budget')


__all__ = ['ABNORMAL', 'CableDriver', 'CableError', 'CableSide', 'MixedDriver', 'TimeCapsuleSide']
