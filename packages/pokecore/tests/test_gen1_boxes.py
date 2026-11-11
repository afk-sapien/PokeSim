"""Gen I box counts and raw records, from WRAM for the active box and cartridge RAM for the rest."""
from pokecore.gen1 import (BOX_DATA_SIZE, BOX_MONS_OFFSET, BOX_NICKS_OFFSET, S_BOXES,
                           W_BOX_COUNT, W_CURRENT_BOX)
from pokecore.storage import box_location, decode_box, read_box_counts, read_box_records


class Banked:
    """Flat WRAM plus cartridge RAM banks read as memory[bank, address]."""

    def __init__(self):
        self.wram = bytearray(65536)
        self.banks = {bank: bytearray(0x2000) for bank in range(4)}

    def __getitem__(self, key):
        if isinstance(key, tuple):
            bank, inner = key
            if isinstance(inner, slice):
                return self.banks[bank][inner.start - S_BOXES:inner.stop - S_BOXES]
            return self.banks[bank][inner - S_BOXES]
        return self.wram[key]


def test_box_location_names_wram_and_both_cartridge_banks():
    assert box_location(3, 3) == (None, W_BOX_COUNT)
    assert box_location(0, 3) == (2, S_BOXES)
    assert box_location(5, 3) == (2, S_BOXES + 5 * BOX_DATA_SIZE)
    assert box_location(6, 3) == (3, S_BOXES)
    assert box_location(11, 3) == (3, S_BOXES + 5 * BOX_DATA_SIZE)
    assert box_location(3, None) == (2, S_BOXES + 3 * BOX_DATA_SIZE)


def test_counts_before_a_box_is_selected_before_initialization_and_after():
    memory = Banked()
    memory.wram[W_CURRENT_BOX] = 12
    assert read_box_counts(memory) == ()
    memory.wram[W_CURRENT_BOX] = 1
    memory.wram[W_BOX_COUNT] = 25
    memory.banks[3][2 * BOX_DATA_SIZE] = 7
    assert read_box_counts(memory) == (0, 20) + (0,) * 10
    memory.wram[W_CURRENT_BOX] = 0x81
    memory.banks[2][0] = 30
    assert read_box_counts(memory) == (30, 20) + (0,) * 6 + (7,) + (0,) * 3


def test_flat_memory_reports_full_inactive_boxes_and_reads_only_the_active_one():
    memory = bytearray(65536)
    memory[W_CURRENT_BOX] = 0x82
    memory[W_BOX_COUNT] = 1
    memory[W_BOX_COUNT + BOX_MONS_OFFSET] = 177
    memory[W_BOX_COUNT + BOX_MONS_OFFSET + 3] = 9
    memory[W_BOX_COUNT + BOX_NICKS_OFFSET:W_BOX_COUNT + BOX_NICKS_OFFSET + 2] = bytes([0x80, 0x50])
    assert read_box_counts(memory) == (20, 20, 1) + (20,) * 9
    record, = read_box_records(memory)
    assert record.box == 2 and record.count == 1
    assert (record.mons[0].species, record.mons[0].level, record.mons[0].nick) == (177, 9, 'A')


def test_records_read_wram_and_banks_clamp_counts_and_skip_empty_boxes():
    memory = Banked()
    memory.wram[W_CURRENT_BOX] = 0x80
    memory.wram[W_BOX_COUNT] = 1
    memory.wram[W_BOX_COUNT + BOX_MONS_OFFSET] = 177
    base = 4 * BOX_DATA_SIZE
    memory.banks[3][base] = 2
    memory.banks[3][base + BOX_MONS_OFFSET + 33] = 21
    memory.banks[3][base + BOX_NICKS_OFFSET + 11:base + BOX_NICKS_OFFSET + 13] = bytes([0x81, 0x50])
    wram, banks = bytes(memory.wram), {bank: bytes(data) for bank, data in memory.banks.items()}
    records = read_box_records(memory)
    assert [(record.box, record.count) for record in records] == [(0, 1), (10, 2)]
    assert (records[1].mons[1].species, records[1].mons[1].nick) == (21, 'B')
    assert records[1].mons is decode_box(records[1].structs, records[1].names)
    clamped, = read_box_records(memory, (0,) * 10 + (99, 0))
    assert (clamped.box, clamped.count, len(clamped.names)) == (10, 20, 220)
    assert bytes(memory.wram) == wram
    assert {bank: bytes(data) for bank, data in memory.banks.items()} == banks


def test_yellow_reads_shifted_wram_and_the_same_cartridge_banks():
    memory = Banked()
    memory.wram[W_CURRENT_BOX - 1] = 0x81
    memory.wram[W_BOX_COUNT - 1] = 1
    memory.wram[W_BOX_COUNT - 1 + BOX_MONS_OFFSET] = 84
    memory.banks[2][0] = 1
    memory.banks[2][BOX_MONS_OFFSET] = 177
    assert read_box_counts(memory, version='yellow')[:2] == (1, 1)
    records = read_box_records(memory, version='yellow')
    assert [(record.box, record.mons[0].species) for record in records] == [(0, 177), (1, 84)]
