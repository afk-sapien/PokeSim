"""Bounded serial transport for two isolated Generation II cartridges."""
from ..interactions.cable import CableSide as BaseSide, checked
from .cable_metadata import BUILDS
from .ram import Memory


class CableSide(BaseSide):
    def __init__(self, spec, data):
        super().__init__(spec, builds=BUILDS)
        self.data = data
        self.memory = Memory(self.pb.memory, data)

    def get(self, key):
        return self.memory.byte(key)

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
        for key in ('Gen2ToGen2LinkComms', 'LinkTrade', 'LinkTrade.save', 'SaveAfterLinkTrade', 'CloseLink', 'ExitLinkCommunications'):
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
