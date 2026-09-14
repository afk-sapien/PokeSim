"""Individual stat decoding and conservative retention of incidental duplicates."""
from dataclasses import replace
import json

import pytest

from pokesim.broker.inventory import normalise
from pokesim.policies.team import release_target, spare_copies
from pokesim.ram import (StoredMon, W_BOX_COUNT, W_PARTY_COUNT, W_PARTY_MONS,
                         read_snapshot)
from pokesim.trade import boxes
from pokesim.web.pokedex import live_status
from test_events import snap
from test_strategy import mon
from test_trade_save import Memory, entry, populate


def stored(position, **changes):
    return replace(StoredMon(0, position, 0x99, 20, '', (33, 45, 0, 0), 8000,
                             (8,) * 5, (0,) * 5), **changes)


def snapshot(copies, party=()):
    return snap(party=party, stored_details=tuple(copies),
                stored_pokemon=tuple((p.box, p.species, p.level, p.nick) for p in copies))


def assert_spares(s, expected):
    assert spare_copies(s) == expected
    payload = json.loads(json.dumps(live_status(s.to_dict(), None)))
    broker = normalise('red', 'http://red', payload)
    assert [(p.box - 1, p.position - 1, p.level) for p in broker.spares] == expected


def test_party_and_both_storage_banks_decode_individual_stats():
    memory = populate(Memory(), active=2, contents=())
    raw = bytearray(entry(0x99, 20, dvs=0x9AD4).struct)
    raw[8:12] = bytes((33, 45, 73, 0))
    training = (1, 256, 4096, 32768, 65535)
    for offset, value in zip(range(17, 27, 2), training):
        raw[offset:offset + 2] = value.to_bytes(2, 'big')
    slot = replace(entry(0x99, 20), struct=bytes(raw))
    for box in (1, 2, 7):
        boxes.write_slot(memory, box, 1, slot)
    # Active WRAM wins over the stale SRAM copy.
    memory[W_BOX_COUNT + 22 + 27] = 0xFF
    memory[W_PARTY_COUNT] = 1
    memory[W_PARTY_MONS:W_PARTY_MONS + 33] = raw
    memory[W_PARTY_MONS + 33] = 20
    s = read_snapshot(memory, 1)
    assert s.party[0].dvs == (10, 9, 10, 13, 4)
    assert s.party[0].stat_exp == training
    assert s.party[0].experience == 8000
    assert [(p.box, p.dvs) for p in s.stored_details] == [
        (0, (10, 9, 10, 13, 4)), (1, (14, 15, 15, 13, 4)), (6, (10, 9, 10, 13, 4))]
    assert all(p.stat_exp == training and p.moves == (33, 45, 73, 0)
               for p in s.stored_details)


def test_dvs_choose_between_otherwise_equal_duplicates_across_boxes():
    s = snapshot([stored(0), stored(0, box=6, dvs=(15,) * 5)])
    assert_spares(s, [(0, 0, 20)])
    assert release_target(s) == (0, 0)


@pytest.mark.parametrize('investment', [
    {'level': 21}, {'stat_exp': (10000,) * 5}, {'experience': 8100},
    {'moves': (33, 45, 73, 0)}, {'moves': (33, 45, 22, 0)},
])
def test_practical_investment_beats_perfect_dvs(investment):
    keeper = stored(1, dvs=(0,) * 5, **investment)
    s = snapshot([stored(0, dvs=(15,) * 5), keeper])
    assert_spares(s, [(0, 0, 20)])


def test_better_boxed_copy_survives_without_displacing_party_member():
    partner = mon(level=20, moves=(33, 45, 0, 0), experience=8000,
                  dvs=(8,) * 5, stat_exp=(0,) * 5)
    s = snapshot([stored(0), stored(1, dvs=(15,) * 5)], party=(partner,))
    assert_spares(s, [(0, 0, 20)])
    assert s.party == (partner,)


def test_trained_party_member_remains_the_keeper_over_perfect_dvs():
    partner = mon(level=20, moves=(33, 45, 0, 0), experience=8000,
                  dvs=(0,) * 5, stat_exp=(10000,) * 5)
    assert_spares(snapshot([stored(0, dvs=(15,) * 5)], party=(partner,)), [(0, 0, 20)])


def test_exact_ties_keep_one_copy_and_protected_species_are_never_offered():
    s = snapshot([stored(0), stored(1)])
    assert_spares(s, [(0, 1, 20)])
    assert spare_copies(s, protected=(0x99,)) == []
    assert release_target(snapshot([stored(0)])) is None


def test_legacy_or_stale_details_use_level_only_without_guessing_dvs():
    s = snapshot([stored(0, dvs=(15,) * 5), stored(1, dvs=(0,) * 5)])
    s = replace(s, stored_pokemon=((0, 0x99, 20, ''), (0, 0x99, 21, '')))
    assert_spares(s, [(0, 0, 20)])
    assert_spares(replace(s, stored_details=()), [(0, 0, 20)])


def test_filtered_invalid_box_slot_does_not_shift_release_or_trade_address():
    memory = populate(Memory(), contents=())
    for position in (1, 2, 3):
        boxes.write_slot(memory, 1, position, entry(0x99, 20, dvs=0 if position == 3 else 0xFFFF))
    memory[W_BOX_COUNT + 22] = 0
    assert_spares(read_snapshot(memory, 1), [(0, 2, 20)])
