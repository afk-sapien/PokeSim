from types import SimpleNamespace

import pytest

from pokesim.ram import BOX_DATA_SIZE, PartyMon, W_BOX_COUNT
from pokesim.trade import boxes
from pokesim.trade.preferences import identity
from tools.trim_duplicate_checkpoint import compact_boxes, plan_removals
from test_trade_save import MACHOKE, Memory, entry, populate


def inventory():
    copies = [dict(species=MACHOKE, level=30 + i, box=0, position=i,
                   moves=[2, 0, 0, 0], stat_exp=[0] * 5, dvs=[i] * 5,
                   trainer_id=5, experience=1000) for i in range(9)]
    return SimpleNamespace(party=[], storage_entries=lambda: copies), copies


def test_plan_preserves_quality_best_dvs_and_preferences():
    snapshot, copies = inventory()
    copies[0]['dvs'] = [15] * 5
    preferences = {identity(copies[1]): {'state': 'locked'},
                   identity(copies[2]): {'state': 'offered'}}
    removed = plan_removals(snapshot, preferences)
    assert [mon['position'] for mon in removed] == [3, 4, 5, 6]
    assert not plan_removals(snapshot, preferences, protected={MACHOKE})


def test_small_groups_are_untouched():
    snapshot, copies = inventory()
    del copies[5:]
    assert not plan_removals(snapshot, {})


def test_party_is_preserved_even_when_weaker_than_every_stored_copy():
    snapshot, copies = inventory()
    snapshot.party = [PartyMon(MACHOKE, 10, 10, 5, 'PARTY', dvs=(0,) * 5)]
    removed = plan_removals(snapshot, {})
    assert len(removed) == 6
    assert all(mon in copies for mon in removed)
    assert len(snapshot.party) == 1


@pytest.mark.parametrize('box', [1, 7])
def test_compaction_preserves_survivor_bytes_and_bank_checksums(box):
    memory = populate(Memory(), contents=())
    original = [entry(MACHOKE, 30 + i, nick=f'KEEP{i}', dvs=1234 + i) for i in range(5)]
    for position, slot in enumerate(original, 1):
        boxes.write_slot(memory, box, position, slot)
    compact_boxes(memory, [dict(box=box - 1, position=i, species=MACHOKE, level=30 + i)
                           for i in (0, 2, 4)])
    view = boxes.BoxView(memory, box)
    assert view.count == 2
    assert view.read(boxes.OFF_SPECIES_LIST, 3) == bytes([MACHOKE, MACHOKE, 255])
    for position, expected in enumerate((original[1], original[3]), 1):
        actual = boxes.read_slot(memory, box, position)
        assert (actual.struct, actual.nickname, actual.ot_name) == (
            expected.struct, expected.nickname, expected.ot_name)
    data = memory[view.bank, 0xA000:0xBA4C]
    assert memory[view.bank, boxes.SRAM_ALL_BOXES_CHECKSUM] == (~sum(data)) & 255
    if view.active:
        assert memory[view.bank, view.sram:view.sram + BOX_DATA_SIZE] == memory[
            W_BOX_COUNT:W_BOX_COUNT + BOX_DATA_SIZE]


def test_invalid_plan_fails_before_any_write():
    memory = populate(Memory())
    before = bytes(memory.flat)
    with pytest.raises(ValueError, match='does not match'):
        compact_boxes(memory, [dict(box=0, position=0, species=MACHOKE, level=30)])
    assert bytes(memory.flat) == before
