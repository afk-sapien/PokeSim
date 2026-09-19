"""Bounded virtual cable transport for two isolated, verified cartridge instances."""
from __future__ import annotations

from collections import Counter, deque
import hashlib
from importlib.metadata import version
import io
from pathlib import Path

from .cable_metadata import ADAPTER_ID, BUILDS


class CableError(RuntimeError):
    """A speculative session failed and must never be adopted."""


def checked(condition, message):
    if not condition:
        raise CableError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class CableSide:
    """Own an emulator, independent cartridge RAM, and one bounded cable endpoint."""

    def __init__(self, spec, max_queue=4):
        from pyboy import PyBoy
        checked(version('pyboy') == '2.7.0', 'Cable adapter requires PyBoy 2.7.0')
        self.spec = spec
        self.rom_bytes = Path(spec.rom_path).read_bytes()
        self.rom_sha1 = hashlib.sha1(self.rom_bytes).hexdigest()
        checked(self.rom_sha1 in BUILDS, 'Unsupported ROM for cable adapter')
        self.build = BUILDS[self.rom_sha1]
        self.sym = self.build['symbols']
        for name, expected in self.build['signatures'].items():
            bank, address = self.sym[name]
            offset = bank * 0x4000 + address % 0x4000
            checked(self.rom_bytes[offset:offset + 8].hex() == expected,
                    f'Unsupported instruction signature: {name}')
        state = Path(spec.checkpoint_path).read_bytes()
        save = Path(spec.cartridge_save_path).read_bytes() if spec.cartridge_save_path else b''
        self.input_hashes = {'checkpoint_sha256': sha256(state),
                             'cartridge_sha256': sha256(save) if save else None,
                             'rom_sha256': sha256(self.rom_bytes)}
        for field in ('checkpoint_sha256', 'cartridge_sha256'):
            expected = getattr(spec, field, None)
            checked(expected is None or expected == self.input_hashes[field],
                    f'Source digest mismatch: {field}')
        self.ram_stream = io.BytesIO(save or bytes(32768))
        self.pb = PyBoy(io.BytesIO(self.rom_bytes), ram_file=self.ram_stream,
                        window='null', sound_emulated=False, log_level='ERROR')
        try:
            self.pb.set_emulation_speed(0)
            self.pb.load_state(io.BytesIO(state))
        except BaseException:
            self.pb.stop(save=False)
            raise
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
