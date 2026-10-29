"""Missed encounters return safely without refunding the cost of failed attempts."""
from dataclasses import replace

import pytest

from pokesim.legendary import ENCOUNTERS, LegendaryRecovery
from pokesim.planning.monitor import LEGENDARY_RETRY
from pokesim.policies.battle import choose_battle
from pokesim.policies.ledger import LEGENDARY_THROWS, catch_spent, legendary_retreat
from pokesim.policies.navigation import Navigator
from pokesim.ram import W_EVENT_FLAGS, W_TOGGLE_OBJECT_FLAGS
from pokesim.strategy_data import DATA, EVENTS, MAPS, normalize_toggle_objects
from test_collection import sid, state
from test_strategy import mon

RETRY_FRAMES = LEGENDARY_RETRY.base


def test_retry_wait_matches_the_old_timers():
    # Both generations waited min(180000, 36000 * misses) before reopening a missed encounter.
    assert [LEGENDARY_RETRY.wait(count) for count in range(1, 7)] == [min(180000, 36000 * count) for count in range(1, 7)]
    assert [LEGENDARY_RETRY.wait(count) for count in range(1, 7)] == [36000, 72000, 108000, 144000, 180000, 180000]


@pytest.mark.parametrize('misses', range(1, 7))
def test_each_miss_in_a_row_waits_as_before(misses):
    s, memory = failed()
    recovery = LegendaryRecovery({'attempts': {'150': misses - 1}})
    recovery.observe(s, memory)
    assert recovery.pending == {'150': min(180000, 36000 * misses)}
    assert recovery.attempts == {'150': misses}


def test_an_older_save_keeps_its_wait_and_misses():
    s, memory = failed()
    saved = {'pending': {'150': 5000, '144': 0}, 'attempts': {'150': 3, '144': 1, '146': 2}}
    recovery = LegendaryRecovery(saved)
    assert recovery.state_dict() == saved
    recovery.observe(s, memory)
    recovery.observe(replace(s, frame=120), memory)
    assert recovery.pending['150'] == 5000 - 120
    assert recovery.attempts == saved['attempts']


def test_the_retreat_is_a_ledger_rule():
    s = state(party=(mon(),), in_battle=1)
    assert not catch_spent(s, 0, LEGENDARY_THROWS)
    assert catch_spent(s, LEGENDARY_THROWS, LEGENDARY_THROWS)
    assert catch_spent(replace(s, items=()), 0, LEGENDARY_THROWS)
    assert not catch_spent(replace(s, items=((1, 1),)), 0, LEGENDARY_THROWS)
    assert legendary_retreat(replace(s, items=()), 0, True)
    assert not legendary_retreat(replace(s, items=()), 0, False)
    assert not legendary_retreat(replace(s, items=(), enemy_shiny=True), 0, True)
    assert not legendary_retreat(replace(s, items=(), battle_type=1), 0, True)


def failed(dex=150, **changes):
    _, room, obj, flag = next(row for row in ENCOUNTERS if row[0] == dex)
    memory = bytearray(65536)
    for base, bit in ((W_EVENT_FLAGS, EVENTS[flag]),
                      (W_TOGGLE_OBJECT_FLAGS, DATA['toggle_objects'].index([room, obj]))):
        memory[base + bit // 8] = 1 << (bit % 8)
    snapshot = state(map=room, event_flags=bytes(memory[W_EVENT_FLAGS:W_EVENT_FLAGS + 320]),
                     hidden_objects=bytes(memory[W_TOGGLE_OBJECT_FLAGS:W_TOGGLE_OBJECT_FLAGS + 32]))
    return replace(snapshot, **changes), memory


@pytest.mark.parametrize('dex', [144, 145, 146, 150])
def test_recovery_changes_only_encounter_bits_after_leaving_and_waiting(dex):
    s, memory = failed(dex)
    _, room, obj, flag = next(row for row in ENCOUNTERS if row[0] == dex)
    bits = ((W_EVENT_FLAGS, EVENTS[flag]),
            (W_TOGGLE_OBJECT_FLAGS, DATA['toggle_objects'].index([room, obj])))
    memory[0xD31D:0xD340] = bytes(range(35))
    for base, bit in bits:
        memory[base + bit // 8] = 255
    recovery = LegendaryRecovery()
    original = bytes(memory)
    expected = bytearray(original)
    for base, bit in bits:
        expected[base + bit // 8] &= ~(1 << (bit % 8))
    events, changed = recovery.observe(s, memory)
    assert len(events) == 1 and not changed
    for frame in range(120, RETRY_FRAMES + 121, 120):
        assert not recovery.observe(replace(s, frame=frame), memory)[1]
    assert bytes(memory) == original
    events, changed = recovery.observe(replace(s, map=MAPS['PALLET_TOWN'], frame=RETRY_FRAMES + 240), memory)
    assert changed and len(events) == 1
    assert memory == expected
    assert sum(a != b for a, b in zip(original, memory)) == 2
    fresh = replace(s, map=MAPS['PALLET_TOWN'], frame=RETRY_FRAMES + 360,
                    event_flags=bytes(320), hidden_objects=bytes(32))
    assert recovery.observe(fresh, memory) == ([], False)


@pytest.mark.parametrize('changes', [dict(in_battle=1), dict(textbox=True), dict(start_menu=True)])
def test_never_restores_during_a_battle_or_menu(changes):
    s, memory = failed(map=MAPS['PALLET_TOWN'], **changes)
    original = bytes(memory)
    recovery = LegendaryRecovery({'pending': {'150': 0}, 'attempts': {'150': 1}})
    assert not recovery.observe(s, memory)[1]
    assert bytes(memory) == original


def test_a_caught_or_traded_legendary_is_never_respawned():
    s, memory = failed(owned=frozenset({1, 150}))
    original = bytes(memory)
    recovery = LegendaryRecovery({'pending': {'150': 0}, 'attempts': {'150': 1}})
    assert recovery.observe(s, memory) == ([], False)
    assert not recovery.pending
    assert bytes(memory) == original


def test_hidden_only_legacy_encounter_and_retry_delay_survive_restart():
    s, memory = failed(event_flags=bytes(320))
    recovery = LegendaryRecovery()
    recovery.observe(s, memory)
    recovery.observe(replace(s, frame=120), memory)
    saved = recovery.state_dict()
    restored = LegendaryRecovery(saved)
    assert restored.pending == {'150': RETRY_FRAMES - 120}
    restored.observe(replace(s, frame=500000), memory)
    assert restored.pending == saved['pending']
    restored.pending['150'] = 0
    restored.observe(replace(s, map=MAPS['PALLET_TOWN'], frame=500120), memory)
    restored.observe(replace(s, frame=500240), memory)
    assert restored.pending['150'] == RETRY_FRAMES * 2
    assert saved['pending']['150'] == RETRY_FRAMES - 120


def test_unavailable_encounter_without_any_flags_does_not_get_created():
    recovery = LegendaryRecovery()
    memory = bytearray(65536)
    assert recovery.observe(state(event_flags=bytes(320), hidden_objects=bytes(32)), memory) == ([], False)
    assert not recovery.pending and not recovery.attempts


def test_original_toggle_offsets_and_legacy_bundle_normalization():
    rows = DATA['toggle_objects']
    assert rows[186] == [MAPS['UNUSED_MAP_F4'], 1]
    assert rows[209] == [MAPS['CERULEAN_CAVE_B1F'], 0]
    assert rows[227] == [MAPS['SEAFOAM_ISLANDS_B4F'], 2]
    assert len(rows) == 228
    legacy = rows[:186] + rows[187:]
    assert normalize_toggle_objects(legacy) == rows
    assert normalize_toggle_objects(rows) == rows
    nav = Navigator()
    nav.update_story(state(hidden_objects=bytes([255] * 32)))


@pytest.mark.parametrize('condition', ['no_balls', 'full_storage', 'budget'])
def test_exhausted_capture_returns_run_instead_of_fight_menu_loop(condition):
    me = mon(level=100, hp=300, max_hp=300, moves=(33,), pp=(35,))
    enemy = mon(species=sid(150), level=70)
    s = state(party=(me,), in_battle=1)
    attempts = 50 if condition == 'budget' else 0
    if condition == 'no_balls':
        s = replace(s, items=())
    if condition == 'full_storage':
        s = replace(s, party=(me,) * 6, boxed_pokemon=((sid(16), 2),) * 20)
    decision = choose_battle(s, me, enemy, 0, catch_attempts=attempts)
    assert decision.kind == 'run'


def test_incidental_legendary_is_protected_without_a_collection_project():
    me = mon(level=100, hp=300, max_hp=300, moves=(89,), pp=(10,))
    enemy = mon(species=sid(144), level=50, hp=100, max_hp=100)
    s = state(party=(me,), in_battle=1)
    assert choose_battle(s, me, enemy, 0, collect_missing=False).kind == 'item'
