"""Cached storage must follow live bytes across mutations, games, and restores."""
from dataclasses import replace

import pytest

from pokesim import ram
from pokesim.trade import boxes
from test_trade_save import Memory, entry, populate


def test_unchanged_boxes_reuse_immutable_decoded_records():
    memory = populate(Memory(), contents=((1, 148, 30), (7, 41, 41)))
    first = ram.read_snapshot(memory, 10)
    memory[ram.W_X] = 9
    second = ram.read_snapshot(memory, 11)
    assert second.x == 9 and second.frame == 11
    assert first.stored_details == second.stored_details
    assert all(a is b for a, b in zip(first.stored_details, second.stored_details))


@pytest.mark.parametrize('box', [1, 7])
@pytest.mark.parametrize('offset, value, field', [
    (0, 41, 'species'), (3, 99, 'level'), (8, 33, 'moves'),
    (12, 1, 'trainer_id'), (14, 1, 'experience'), (17, 42, 'stat_exp'), (27, 255, 'dvs'),
])
def test_changed_individual_bytes_invalidate_only_the_changed_box(box, offset, value, field):
    memory = populate(Memory(), contents=((1, 148, 30), (7, 148, 30)))
    before = ram.read_stored_details(memory)
    slot = boxes.read_slot(memory, box, 1)
    raw = bytearray(slot.struct)
    raw[offset] = value
    boxes.write_slot(memory, box, 1, replace(slot, struct=bytes(raw)))
    after = ram.read_stored_details(memory)
    index = 0 if box == 1 else 1
    assert getattr(after[index], field) != getattr(before[index], field)
    assert after[1 - index] is before[1 - index]
    boxes.write_slot(memory, box, 1, slot)
    assert ram.read_stored_details(memory) == before


def test_renames_counts_invalid_slots_and_other_games_do_not_reuse_stale_data():
    memory = populate(Memory(), contents=((1, 148, 30),))
    original = ram.read_stored_details(memory)
    boxes.write_slot(memory, 1, 1, entry(148, 30, nick='NEW'))
    assert ram.read_stored_details(memory)[0].nick == 'NEW'
    boxes.write_slot(memory, 1, 2, entry(41, 50))
    assert len(ram.read_stored_details(memory)) == 2
    memory[ram.W_BOX_COUNT + 22] = 255
    assert [mon.position for mon in ram.read_stored_details(memory)] == [1]
    memory[ram.W_BOX_COUNT] = 0
    assert ram.read_stored_details(memory) == ()
    other = populate(Memory(), contents=((1, 148, 30),))
    assert ram.read_stored_details(other) == original


def test_switching_active_box_uses_wram_instead_of_stale_bank_copy():
    memory = populate(Memory(), contents=((1, 148, 30), (7, 41, 41)))
    before = ram.read_stored_details(memory)
    memory[ram.W_CURRENT_BOX] = 0x80 | 6
    boxes.write_slot(memory, 7, 1, entry(148, 99))
    after = ram.read_stored_details(memory)
    assert after[0] == before[0]
    assert (after[1].species, after[1].level) == (148, 99)


def test_flat_memory_with_initialized_boxes_still_reads_active_box():
    memory = bytearray(65536)
    memory[ram.W_CURRENT_BOX] = 0x80
    memory[ram.W_BOX_COUNT] = 1
    memory[ram.W_BOX_COUNT + 22:ram.W_BOX_COUNT + 55] = entry(148, 30).struct
    assert [(mon.box, mon.species) for mon in ram.read_stored_details(memory)] == [(0, 148)]


def test_box_cache_is_bounded_during_long_running_training():
    ram._decode_box.cache_clear()
    memory = populate(Memory(), contents=((1, 148, 30),))
    for experience in range(200):
        memory[ram.W_BOX_COUNT + 22 + 16] = experience
        ram.read_stored_details(memory)
    info = ram._decode_box.cache_info()
    assert info.currsize == info.maxsize == 128


def test_storage_rows_are_independent_and_match_dataclass_serialization():
    from dataclasses import asdict
    memory = populate(Memory(), contents=((1, 148, 30),))
    snapshot = ram.read_snapshot(memory, 0)
    rows = snapshot.storage_entries()
    assert rows == [asdict(mon) for mon in snapshot.stored_details]
    rows[0]['level'] = 100
    rows.clear()
    assert snapshot.storage_entries()[0]['level'] == 30
    assert snapshot.stored_details[0].level == 30
