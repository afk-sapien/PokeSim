"""Explicit Gen1 virtual-cable transport over verified ROM hook locations.

Applications own participant selection, scheduling, files, and transaction commit.
The caller supplies a Core emulator and verified build symbols. ``CableDriver`` presses
the controller buttons of one Cable Club trade on two endpoints. Route finding stays
with the caller, who passes a ``walk`` callable.
"""
from collections import Counter, deque
import time

from .centers import CENTERS, location, safe_center, screen


class CableError(RuntimeError):
    """A speculative link session cannot be adopted."""


def checked(condition, message):
    if not condition:
        raise CableError(message)


class CableEndpoint:
    # The party slot this side offers, and the name its counters are reported under.
    party_slot = 0
    label = None

    def __init__(self, emulator, symbols, max_queue=4):
        if type(max_queue) is not int or max_queue < 1:
            raise ValueError("max_queue must be positive")
        self.pb = emulator
        self.sym = symbols
        self.peer = None
        self.parked = None
        self.pending = None
        self.inbox = {'byte': deque(), 'nybble': deque()}
        self.max_queue = max_queue
        self.counts = Counter()
        self.frame = 0
        self.hooks = []
        self.attached = False
        self.stopped = False
        self.park_original = bytes(self.pb.memory[0, 0x3ff0:0x3ff2])
        checked(self.park_original == bytes(2), 'Parking address is not verified padding')

    def get(self, key):
        return self.pb.memory[self.sym[key][1]]

    def put_transport(self, key, value):
        self.pb.memory[self.sym[key][1]] = value

    def hook(self, name, callback):
        bank, addr = self.sym[name]
        self.pb.hook_register(bank, addr, callback, None)
        self.hooks.append((bank, addr))

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
            self.hook('CableClubNPC.establishConnectionLoop', connect)
            self.hook('Serial_ExchangeByte', lambda _: self.exchange('byte', 'hSerialSendData'))
            self.hook('Serial_SyncAndExchangeNybble',
                      lambda _: self.exchange('nybble', 'wSerialExchangeNybbleSendData'))
        for key in ('CableClub_DoBattleOrTrade', 'TradeCenter_SelectMon', 'TradeCenter_Trade',
                    'TradeCenter_Trade.tradeCompleted', 'SavePartyAndDexData', 'ReturnToCableClubRoom'):
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
        if not self.inbox[kind]:
            rf = self.pb.register_file
            checked(0xc000 <= rf.SP < 0xfffe, 'Invalid cable return stack')
            self.parked = (rf.PC, rf.SP, self.pb.memory[0xffff])
            self.pb.memory[0xffff] = 0
            rf.PC = 0x3ff0
            return
        value = self.inbox[kind].popleft()
        self.pending = None
        self.counts[kind + '_exchanged'] += 1
        if kind == 'nybble':
            self.put_transport('wSerialSyncAndExchangeNybbleReceiveData', value)
            self.put_transport('wSerialExchangeNybbleReceiveData', value)
        else:
            self.put_transport('hSerialReceiveData', value)
            self.put_transport('hSerialReceivedNewData', 0)
        rf = self.pb.register_file
        checked(0xc000 <= rf.SP < 0xfffe, 'Invalid cable return stack')
        target = self.pb.memory[rf.SP] | self.pb.memory[rf.SP + 1] << 8
        checked(0 < target < 0x8000 and target != 0x3ff0, 'Invalid cable return address')
        rf.A = value
        rf.PC = target
        rf.SP += 2

    def tick(self):
        if self.parked is not None:
            if not self.inbox[self.pending]:
                return False
            pc, sp, interrupt_mask = self.parked
            checked(self.pb.register_file.SP == sp, 'Parked CPU stack changed')
            checked(self.pb.memory[0xffff] == 0, 'Parked interrupt mask changed')
            self.pb.register_file.PC = pc
            self.pb.memory[0xffff] = interrupt_mask
            self.parked = None
        checked(self.pb.tick(1, True), 'Emulator stopped unexpectedly')
        self.frame += 1
        return True

    def release_buttons(self):
        for button in ('a', 'b', 'start', 'select', 'up', 'down', 'left', 'right'):
            self.pb.button_release(button)

    def detach(self):
        checked(self.parked is None and self.pending is None,
                'Cannot export a pending cable exchange')
        checked(all(not queue for queue in self.inbox.values()), 'Undrained cable messages')
        for bank, addr in self.hooks:
            self.pb.hook_deregister(bank, addr)
        self.hooks.clear()
        self.pb.memory[0, 0x3ff0] = self.park_original[0]
        self.pb.memory[0, 0x3ff1] = self.park_original[1]
        self.attached = False
        self.release_buttons()

    def stop(self):
        if not self.stopped:
            self.pb.stop(save=False)
            self.stopped = True


CLUB_MAP = 239
PLAYER_FACING = 0xC109
WALK_COUNTER = 0xCFC5
FACING_UP = 4


class CableDriver:
    """Input-only gameplay driver for a negotiated Cable Club exchange between two endpoints.

    ``plan`` needs ``max_steps``, ``timeout_seconds`` and ``speed`` (0 runs unpaced).
    ``walk(side, snapshot, target)`` returns the next button that moves ``side`` toward
    ``target`` (map, x, y), or None. ``snapshot(side)`` reads the fields ``safe_center``
    needs and defaults to ``centers.location``. Each side offers ``side.party_slot``.
    Endpoint memory must be Red-layout (``yellow.YellowEmulator`` on Yellow).
    """

    def __init__(self, sides, plan, progress=None, cancelled=None, *, walk=None, snapshot=None):
        self.sides = sides
        self.plan = plan
        self.progress = progress
        self.cancelled = cancelled
        self.walk = walk
        if snapshot is not None:
            self.snapshot = snapshot
        self.started = time.monotonic()
        self.steps = 0
        self.frames = 0
        self.phase = ''
        self.last_activity = 0
        self.last_signature = None
        self.preview = None
        self.last_preview = 0.0

    def report(self, phase):
        self.phase = phase
        if self.progress:
            self.progress({'phase': phase, 'steps': self.steps,
                           'sides': {side.label: dict(side.counts) for side in self.sides}})

    def tick(self, frames):
        for _ in range(frames):
            checked(self.cancelled is None or not self.cancelled.is_set(),
                    'Cable session cancelled because its parent disconnected')
            checked(time.monotonic() - self.started < self.plan.timeout_seconds,
                    f'Cable {self.phase} wall-clock deadline exceeded')
            moved = False
            for side in self.sides:
                moved = side.tick() or moved
            checked(moved, 'Cable transport deadlock')
            self.frames += 1
            now = time.monotonic()
            if self.preview and self.frames % 6 == 0 and now - self.last_preview >= 0.1:
                self.preview(self.phase, self.steps)
                self.last_preview = now
            if self.plan.speed > 0:
                delay = self.frames / (60 * self.plan.speed) - (time.monotonic() - self.started)
                if delay > 0:
                    time.sleep(min(delay, 0.05))

    def press(self, buttons, frames=8, after=24):
        self.steps += 1
        checked(self.steps <= self.plan.max_steps, f'Cable {self.phase} step budget exceeded')
        for side, button in zip(self.sides, buttons):
            if button:
                side.pb.button_press(button)
        self.tick(frames)
        for side in self.sides:
            side.release_buttons()
        self.tick(after)
        signature = tuple((side.get('wLinkState'), side.get('wCurrentMenuItem'),
                           side.get('wWhichTradeMonSelectionMenu'),
                           tuple(side.counts.items())) for side in self.sides)
        if signature != self.last_signature:
            self.last_signature = signature
            self.last_activity = self.steps
        checked(self.steps - self.last_activity < 400, f'Cable {self.phase} stalled')

    def snapshot(self, side):
        return location(side.pb.memory)

    def enter(self):
        """Walk both trainers from their prepared Centers to the attendant and face up."""
        self.report('preparing')
        for side in self.sides:
            source = self.snapshot(side)
            checked(safe_center(source, source.map, side.pb.memory),
                    'Cable input must be a prepared supported Center checkpoint')
            checked(side.get('wLinkState') == 0, 'Cable source has an active link state')
            previous = getattr(side, 'source_center_map', source.map)
            checked(previous == source.map, 'Cable source Center changed during preparation')
            side.source_center_map = source.map
        for _ in range(240):
            buttons = []
            for side in self.sides:
                s = self.snapshot(side)
                checked(safe_center(s, side.source_center_map, side.pb.memory),
                        'Cable preparation left its original supported Center')
                target = CENTERS[side.source_center_map]['rendezvous']
                pos = (s.map, s.x, s.y)
                if pos == target:
                    buttons.append(None)
                    continue
                checked(self.walk is not None, 'Cable preparation needs a walk callable')
                buttons.append(self.walk(side, s, target))
            if all((self.snapshot(s).map, self.snapshot(s).x, self.snapshot(s).y)
                   == CENTERS[s.source_center_map]['rendezvous'] for s in self.sides):
                if all(s.pb.memory[PLAYER_FACING] == FACING_UP and not s.pb.memory[WALK_COUNTER]
                       for s in self.sides):
                    return
                self.press([None if s.pb.memory[WALK_COUNTER] or s.pb.memory[PLAYER_FACING] == FACING_UP
                            else 'up' for s in self.sides], frames=8, after=24)
                continue
            self.press(buttons)
        raise CableError('Cannot reach Cable Club attendant within preparation budget')

    def exchange(self):
        """Talk to the attendant, enter the Trade Center and trade ``party_slot`` on each side."""
        self.report('connecting')
        for step in range(900):
            if all(side.counts['TradeCenter_SelectMon'] >= 2 for side in self.sides):
                self.report('saving')
                return
            buttons = []
            for side in self.sides:
                if side.counts['TradeCenter_SelectMon'] >= 2:
                    buttons.append(None)
                    continue
                view = screen(side.pb.memory)
                button = 'a'
                if 'STATS     TRADE' in view.text:
                    button = 'right' if view.top_x == 1 else 'a'
                elif (side.counts['TradeCenter_SelectMon'] == 1
                      and not side.counts['TradeCenter_Trade']
                      and view.cursor and view.top_y == 1 and view.top_x == 1
                      and 'CANCEL' in view.text):
                    target = side.party_slot
                    current = side.get('wCurrentMenuItem')
                    checked(current <= target, 'Trade selection cursor passed negotiated slot')
                    button = 'down' if current < target else 'a'
                elif (side.counts['TradeCenter_SelectMon'] == 1 and not side.counts['TradeCenter_Trade']
                      and not view.cursor):
                    # Yellow draws the party menu fast enough to take a held A as a choice of the first slot.
                    button = None
                elif self.snapshot(side).map == CLUB_MAP and not side.counts['CableClub_DoBattleOrTrade']:
                    if step % 3 == 0:
                        button = 'right' if side.get('hSerialConnectionStatus') == 2 else 'left'
                buttons.append(button)
            if self.phase == 'connecting' and any(s.counts['TradeCenter_Trade'] for s in self.sides):
                self.report('trading')
            self.press(buttons, after=22)
        raise CableError('No completed trade within exchange budget')

    def leave(self):
        """Choose CANCEL in the trade menu until both games are back in the Club room, then detach."""
        self.report('leaving')
        for _ in range(160):
            if all(side.counts['ReturnToCableClubRoom'] for side in self.sides):
                self.tick(120)
                for side in self.sides:
                    checked(side.get('wLinkState') == 1, 'Game did not return to Club room')
                    side.detach()
                return
            buttons = []
            for side in self.sides:
                if side.counts['ReturnToCableClubRoom']:
                    buttons.append(None)
                    continue
                view = screen(side.pb.memory)
                if view.cursor and 'CANCEL' in view.text:
                    buttons.append('a' if side.get('wCurrentMenuItem') == side.get('wPartyCount') else 'down')
                else:
                    buttons.append(None)
            self.press(buttons)
        raise CableError('Unable to leave trade menu through Cancel')

    def return_to_center(self):
        """Soft reset both detached games and Continue until each stands in its original Center."""
        self.report('resuming')
        # The original Club room has no exits. The game's supported return is
        # reset and Continue, using the cartridge save written by the trade.
        for side in self.sides:
            checked(not side.attached, 'Reset attempted while cable hooks remain')
            for button in ('a', 'b', 'start', 'select'):
                side.pb.button_press(button)
        self.tick(180)
        for side in self.sides:
            side.release_buttons()
        self.tick(180)
        entered = [False, False]
        for step in range(180):
            buttons = []
            for i, side in enumerate(self.sides):
                snap = self.snapshot(side)
                view = screen(side.pb.memory)
                if entered[i] and safe_center(snap, side.source_center_map, side.pb.memory):
                    buttons.append(None)
                elif 'CONTINUE' in view.text:
                    entered[i] = True
                    buttons.append('up' if view.menu_index > 0 else 'a')
                elif 'NEW GAME' in view.text:
                    raise CableError('Cartridge save has no Continue option')
                elif entered[i]:
                    buttons.append(None)
                else:
                    buttons.append('start' if step % 3 == 0 else 'a')
            if all(entered[i] and safe_center(self.snapshot(side), side.source_center_map, side.pb.memory)
                   and side.get('wLinkState') == 0 for i, side in enumerate(self.sides)):
                self.tick(120)
                checked(all(safe_center(self.snapshot(side), side.source_center_map, side.pb.memory)
                            for side in self.sides), 'Center was not stable after Continue')
                return
            self.press(buttons, after=60)
        raise CableError('Cartridge Continue did not return both games to the Center')
