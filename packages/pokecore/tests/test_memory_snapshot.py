"""The per-step memory snapshot. Every cartridge here is synthetic."""
import io
import random
from types import SimpleNamespace

import pytest

from pokecore import memory_snapshot
from pokecore.emulator import Memory
from pokecore.gen2.ram import Memory as Gen2Memory
from pokecore.memory_snapshot import READ_ONLY, snapshot_emulator, snapshot_memory_class
from pokecore.storage import memory_bytes

# ld hl, $C000 / loop: inc (hl) / jr loop. Work RAM byte $C000 changes every frame.
PROGRAM = bytes((0x21, 0x00, 0xC0, 0x34, 0x18, 0xFD))


def cartridge():
    data = bytearray(32 * 16384)
    data[0x100:0x103] = bytes((0xC3, 0x50, 0x01))
    data[0x150:0x150 + len(PROGRAM)] = PROGRAM
    data[0x143] = 0x80
    data[0x147] = 0x13
    data[0x148] = 4
    data[0x149] = 3
    data[0x14D] = (-sum(data[0x134:0x14D]) - 25) & 255
    return bytes(data)


def boot(ram=None):
    pytest.importorskip('pyboy_rs')
    from pokecore.emulator import Emulator
    return snapshot_emulator(Emulator)(io.BytesIO(cartridge()), ram_file=io.BytesIO(ram or bytes(32768)),
                                       sound_emulated=False)


@pytest.fixture
def machine():
    pb = boot(random.Random(3).randbytes(32768))
    pb.tick(120)  # past the boot ROM, into the program loop
    rng = random.Random(9)
    for bank in range(8):
        for address in rng.sample(range(0xC000, 0xE000), 48):
            pb.memory[bank, address] = rng.randrange(256)
    yield pb
    pb.stop(save=False)


def live(pb, bank, address, size):
    """Byte-at-a-time banked reads, which never use a slice or the snapshot."""
    return bytes(pb.memory[bank, value] for value in range(address, address + size))


RANGES = [(0, 0xC000, 16), (0, 0xCFF8, 8), (0, 0xCFF8, 16), (1, 0xD000, 4096), (3, 0xD800, 32), (5, 0xC010, 4),
          (7, 0xDFFF, 1), (7, 0xDFF0, 32), (0, 0xA000, 8192), (2, 0xA123, 1102), (3, 0xBFFF, 1), (3, 0xBFF0, 32),
          (1, 0x8000, 16), (0, 0x9FF8, 16), (8, 0xD000, 4), (4, 0xA000, 4), (-1, 0xC000, 2)]


def test_snapshot_reads_equal_live_banked_reads(machine):
    mem = Gen2Memory(machine.memory, None)
    for bank, address, size in RANGES:
        try:
            expected = bytes(machine.memory[bank, address:address + size])
        except ValueError:
            with pytest.raises(ValueError):
                mem.raw(bank, address, size)
            continue
        assert mem.raw(bank, address, size) == expected == live(machine, bank, address, size), (bank, hex(address))


def test_snapshot_is_reused_until_the_machine_changes(machine):
    memory = machine.memory
    first = memory.snapshot_window(1, 0xD000, 16)
    block = memory._banks[1][(memory_snapshot.WRAM, 1)]
    assert memory.snapshot_window(1, 0xD000, 16) == first
    assert memory._banks[1][(memory_snapshot.WRAM, 1)] is block
    generation = machine._generation
    memory.snapshot_window(2, 0xA000, 16)
    machine.screenshot()
    assert machine._generation == generation


def test_ticks_invalidate_the_snapshot(machine):
    memory = machine.memory
    before = memory.snapshot_window(0, 0xC000, 1)
    machine.tick()
    after = memory.snapshot_window(0, 0xC000, 1)
    assert after == live(machine, 0, 0xC000, 1) != before


def test_writes_and_loads_invalidate_the_snapshot(machine):
    memory = machine.memory
    state = machine.save()
    original = memory.snapshot_window(3, 0xD100, 4)
    memory[3, 0xD100] = original[0] ^ 0xFF
    assert memory.snapshot_window(3, 0xD100, 4) == live(machine, 3, 0xD100, 4) != original
    sram = memory.snapshot_window(2, 0xA010, 1)
    memory[2, 0xA010] = sram[0] ^ 0x55
    assert memory.snapshot_window(2, 0xA010, 1) == bytes((sram[0] ^ 0x55,))
    machine.load(state)
    assert memory.snapshot_window(3, 0xD100, 4) == original
    assert memory.snapshot_window(2, 0xA010, 1) == sram
    checkpoint = machine.checkpoint()
    memory[3, 0xD100] = 7
    assert memory.snapshot_window(3, 0xD100, 1) == b'\x07'
    machine.restore_checkpoint(checkpoint)
    assert memory.snapshot_window(3, 0xD100, 4) == original


def test_hooks_during_a_tick_read_live_memory(machine):
    memory = machine.memory
    seen = []
    memory.snapshot_window(0, 0xC000, 1)
    memory[0xC000]

    def hook(context):
        seen.append((memory.snapshot_window(0, 0xC000, 1), Gen2Memory(memory, None).raw(0, 0xC000, 1),
                     live(machine, 0, 0xC000, 1), memory[0xC000]))

    machine.hook_register(0, 0x0153, hook, None)
    machine.tick()
    machine.hook_deregister(0, 0x0153)
    assert seen and all(window is None and value == current and plain == current[0]
                        for window, value, current, plain in seen)
    assert len({value for _, value, _, _ in seen}) > 1


def test_closed_machines_do_not_serve_a_snapshot():
    pb = boot()
    pb.tick()
    pb.memory.snapshot_window(0, 0xC000, 1)
    pb.memory[0xC000]
    pb.stop(save=False)
    assert pb.memory.snapshot_window(0, 0xC000, 1) is None
    with pytest.raises(RuntimeError):
        pb.memory[0xC000]


def test_unbanked_reads_come_from_one_snapshot_and_follow_the_machine(machine):
    memory = machine.memory
    plain = Memory(machine)
    assert memory.read_bytes(0xC000, 0xE000) == plain.read_bytes(0xC000, 0xE000)
    assert memory[0xC000:0xC010] == plain[0xC000:0xC010] and isinstance(memory[0xC000:0xC010], list)
    assert memory[0xD123] == plain[0xD123] and isinstance(memory[0xD123], int)
    assert memory[0xBFF0:0xC010] == plain[0xBFF0:0xC010]
    assert memory[0xFF80] == plain[0xFF80]
    before = memory[0xC000]
    machine.tick()
    assert memory[0xC000] == plain[0xC000] != before
    memory[0xD200] = memory[0xD200] ^ 0xAA
    assert memory[0xD200] == plain[0xD200]


def test_one_byte_reads_follow_ticks_writes_and_loads(machine):
    memory = machine.memory
    plain = Memory(machine)
    state = machine.save()
    # Copies the view, so the reads below take the one-byte path.
    memory.read_bytes(0xC000, 0xE000)
    before = memory[0xC000]
    assert memory[0xC000] == before == plain[0xC000]
    machine.tick()
    assert memory[0xC000] == plain[0xC000] != before
    memory[0xD200] = memory[0xD200] ^ 0x5A
    assert memory[0xD200] == plain[0xD200]
    machine.load(state)
    assert memory[0xC000] == plain[0xC000] == before


def test_kept_values_are_dropped_whenever_the_machine_changes(machine):
    memory = machine.memory
    computed = []

    def value():
        computed.append(memory[0xC000])
        return len(computed)
    state = machine.save()
    checkpoint = machine.checkpoint()
    assert memory.snapshot_memo('k', value) == memory.snapshot_memo('k', value) == 1
    machine.screenshot()
    assert memory.snapshot_memo('k', value) == 1
    assert memory.snapshot_memo('other', value) == 2
    changes = (machine.tick, lambda: memory.__setitem__(0xD300, 1), lambda: machine.load(state),
               lambda: machine.restore_checkpoint(checkpoint))
    for change in changes:
        count = len(computed)
        change()
        assert memory.snapshot_memo('k', value) == memory.snapshot_memo('k', value) == count + 1


def test_kept_values_are_not_kept_while_the_machine_runs_or_changes(machine):
    memory = machine.memory
    seen = []

    def hook(context):
        seen.append((memory.snapshot_memo('k', lambda: memory[0xC000]), Memory(machine)[0xC000]))

    machine.hook_register(0, 0x0153, hook, None)
    machine.tick()
    machine.hook_deregister(0, 0x0153)
    assert seen and all(kept == current for kept, current in seen)
    assert len({current for _, current in seen}) > 1
    calls = []

    def writing():
        calls.append(1)
        memory[0xD300] = len(calls)
        return len(calls)
    assert memory.snapshot_memo('w', writing) == 1
    assert memory.snapshot_memo('w', writing) == 2


def test_the_snapshot_yellow_emulator_keeps_the_red_layout():
    pytest.importorskip('pyboy_rs')
    from pokecore.emulator import Emulator
    from pokecore.yellow import RedLayoutMemory, open_emulator
    ram = random.Random(4).randbytes(32768)
    red = open_emulator(io.BytesIO(cartridge()), yellow=False, snapshot=True, ram_file=io.BytesIO(ram),
                        sound_emulated=False)
    red.stop(save=False)
    assert type(red) is snapshot_emulator(Emulator)
    pb = open_emulator(io.BytesIO(cartridge()), yellow=True, snapshot=True, ram_file=io.BytesIO(ram),
                       sound_emulated=False)
    try:
        pb.tick(120)
        memory = pb.memory
        assert isinstance(memory, RedLayoutMemory) and memory.raw is pb.raw_memory
        assert hasattr(pb.raw_memory, 'snapshot_window')
        live = RedLayoutMemory(Memory(pb))
        assert memory.read_bytes(0xC000, 0xE000) == live.read_bytes(0xC000, 0xE000)
        assert [memory[a] for a in range(0xCF00, 0xD200)] == [live[a] for a in range(0xCF00, 0xD200)]
        assert memory.snapshot_window(2, 0xA100, 64) == bytes(live[2, 0xA100:0xA140])
        assert memory.snapshot_window(1, 0xD000, 4) is None
        kept = memory.snapshot_memo('k', lambda: memory[0xD163])
        assert memory.snapshot_memo('k', lambda: -1) == kept == live[0xD163]
        memory[0xD163] = kept ^ 1
        assert memory.snapshot_memo('k', lambda: memory[0xD163]) == kept ^ 1 == live[0xD163]
        before = memory[0xC000]
        pb.tick()
        assert memory[0xC000] == live[0xC000] != before
    finally:
        pb.stop(save=False)


def test_memory_bytes_uses_the_snapshot_window(machine):
    memory = machine.memory
    assert memory_bytes(memory, 2, 0xA100, 300) == live(machine, 2, 0xA100, 300)
    assert memory_bytes(memory, None, 0xC100, 300) == bytes(Memory(machine)[0xC100:0xC100 + 300])


def test_gen1_fields_are_identical_through_the_snapshot(machine, monkeypatch):
    from pokecore.snapshot import read_fields
    monkeypatch.setenv('POKESIM_CORE_DECODER', 'python')
    assert read_fields(machine.memory) == read_fields(Memory(machine))


def test_snapshot_emulator_keeps_the_public_api():
    pytest.importorskip('pyboy_rs')
    from pokecore.emulator import Emulator
    cls = snapshot_emulator(Emulator)
    assert cls is snapshot_emulator(Emulator) and issubclass(cls, Emulator)
    public = {name for name in dir(Emulator) if not name.startswith('_')}
    assert public <= set(dir(cls))
    assert all(name in public for name in READ_ONLY - {'symbol_lookup'} if hasattr(Emulator, name))


class FakeBackend:
    """Banked memory without read_bank_bytes or read_bytes, like PyBoy RS 0.1.0."""

    def __init__(self):
        rng = random.Random(5)
        self.banks = {bank: bytearray(rng.randbytes(65536)) for bank in range(8)}
        self.calls = 0

    def __getitem__(self, key):
        self.calls += 1
        bank, key = key if isinstance(key, tuple) else (1, key)
        if not 0 <= bank < 8:
            raise ValueError('Invalid bank')
        return list(self.banks[bank][key]) if isinstance(key, slice) else self.banks[bank][key]

    def __setitem__(self, key, value):
        bank, address = key if isinstance(key, tuple) else (1, key)
        self.banks[bank][address] = value


def fake_owner():
    owner = SimpleNamespace(_backend=SimpleNamespace(memory=FakeBackend()), _generation=0, _busy=0, closed=False)

    def ensure_open():
        if owner.closed:
            raise RuntimeError('The emulator is closed')
    owner._ensure_open = ensure_open
    return owner


def test_older_bindings_fall_back_to_per_bank_reads():
    owner = fake_owner()
    memory = snapshot_memory_class(Memory)(owner)
    backend = owner._backend.memory
    assert memory.snapshot_window(3, 0xD010, 8) == bytes(backend.banks[3][0xD010:0xD018])
    calls = backend.calls
    assert memory.snapshot_window(3, 0xD800, 4) == bytes(backend.banks[3][0xD800:0xD804])
    assert backend.calls == calls
    assert memory.snapshot_window(9, 0xD000, 4) is None
    assert memory.read_bytes(0xC000, 0xC004) == bytes(backend.banks[1][0xC000:0xC004])
    memory[3, 0xD010] = backend.banks[3][0xD010] ^ 1
    assert memory.snapshot_window(3, 0xD010, 1) == bytes((backend.banks[3][0xD010],))
    owner._busy = 1
    assert memory.snapshot_window(3, 0xD010, 1) is None
    owner._busy = 0
    owner.closed = True
    owner._generation += 1  # what the wrapped stop() does
    assert memory.snapshot_window(3, 0xD010, 1) is None
