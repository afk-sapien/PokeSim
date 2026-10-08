"""Yellow memory exposes Red addresses so one snapshot reader serves every Gen 1 cartridge."""
import pytest

from pokesim import yellow


class Raw:
    def __init__(self):
        self.data = bytearray(65536)

    def __getitem__(self, key):
        if isinstance(key, tuple):
            return ('raw', key)
        return self.data[key]

    def __setitem__(self, key, value):
        if isinstance(key, tuple):
            self.banked = (key, value)
            return
        self.data[key] = value

    def read_bytes(self, start, stop):
        return bytes(self.data[start:stop])


class Owner:
    def __init__(self):
        self.raw_memory = Raw()


@pytest.fixture
def memory():
    return yellow.YellowMemory(Owner())


def test_shifted_wram_reads_one_byte_lower(memory):
    memory.raw.data[0xD162] = 3   # Yellow wPartyCount
    memory.raw.data[0xD35D] = 0x26   # Yellow wCurMap
    assert memory[0xD163] == 3
    assert memory[0xD35E] == 0x26
    assert yellow.address(0xCF1A) == 0xCF1A
    assert yellow.address(0xCF1B) == 0xCF1A
    assert yellow.address(0xDEE1) == 0xDEE0


def test_stack_and_low_wram_stay_raw(memory):
    memory.raw.data[0xC109] = 4
    memory.raw.data[0xDF00] = 9
    assert memory[0xC109] == 4
    assert memory[0xDF00] == 9


def test_hram_fields_move(memory):
    for red, raw in {0xFFF4: 0xFFF9, 0xFFF6: 0xFFFA, 0xFFF7: 0xFFFB, 0xFFF8: 0xFFF5, 0xFFF9: 0xFFF8}.items():
        memory.raw.data[raw] = red & 0xFF
        assert memory[red] == red & 0xFF
    assert memory[0xFF80] == 0


def test_ranges_match_single_reads(memory):
    for offset in range(0xCF00, 0xCF40):
        memory.raw.data[offset] = offset & 0xFF
    for offset in range(0xFFF0, 0x10000):
        memory.raw.data[offset] = offset & 0x7F
    span = memory[0xCF10:0xCF30]
    assert span == [memory[i] for i in range(0xCF10, 0xCF30)]
    assert span[0xCF1B - 0xCF10] == 0x1A
    assert memory.read_bytes(0xFFF0, 0x10000) == bytes(memory[i] for i in range(0xFFF0, 0x10000))


def test_writes_land_on_yellow_addresses(memory):
    memory[0xD163] = 2
    assert memory.raw.data[0xD162] == 2
    memory[0xD16B:0xD16D] = [7, 8]
    assert memory.raw.data[0xD16A:0xD16C] == bytearray([7, 8])
    memory[0xFFF8] = 5
    assert memory.raw.data[0xFFF5] == 5


def test_banked_rom_and_cartridge_ram_pass_through(memory):
    assert memory[0, 0x3FF0] == ('raw', (0, 0x3FF0))
    assert memory[1, 0xA598] == ('raw', (1, 0xA598))
    memory.raw.data[0xD162] = 6
    assert memory[0, 0xD163] == 6
    memory[1, 0xA000] = 1
    assert memory.raw.banked == ((1, 0xA000), 1)


def test_snapshot_reads_pikachu_happiness(memory):
    from pokesim.ram import read_snapshot
    memory.raw.data[yellow.PIKACHU_HAPPINESS] = 147
    assert read_snapshot(memory, 0).pikachu_happiness == 147


def test_open_emulator_keeps_core_class_for_other_cartridges(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(yellow, 'YellowEmulator', lambda rom, **kw: seen.append('yellow'))
    rom = tmp_path / 'other.gb'
    rom.write_bytes(b'\0' * 32)
    yellow.open_emulator(rom, default=lambda rom, **kw: seen.append('core'), window='null')
    assert seen == ['core']
    assert not yellow.is_yellow(rom)
