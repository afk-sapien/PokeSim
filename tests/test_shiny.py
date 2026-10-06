import io
from contextlib import closing
from pathlib import Path

import pytest

from pokesim.shiny import is_shiny, shiny_bytes, ShinyTracker, record, status
from pokesim.store import Store
from pokesim.duplicates import spare_entries


def test_every_dv_combination_matches_gen2_rule():
    for first in range(256):
        for second in range(256):
            attack, defense, speed, special = first >> 4, first & 15, second >> 4, second & 15
            expected = defense == speed == special == 10 and attack in (2,3,6,7,10,11,14,15)
            assert shiny_bytes(bytes((first, second))) == expected
            assert is_shiny({'dvs': (0,attack,defense,speed,special)}) == expected
    for dvs in (None, [], [0,True,10,10,10], [0,18,10,10,10], ['0',2,10,10,10]):
        assert not is_shiny({'dvs': dvs})


def test_shinies_are_not_release_candidates():
    shiny = dict(species=165, level=5, dvs=(0,2,10,10,10), stat_exp=(0,)*5, moves=(1,), box=1, position=1)
    better = {**shiny, 'level': 50, 'dvs': (15,)*5, 'position': 2}
    assert spare_entries([], [shiny,better]) == []


def test_receipts_survive_reopen_without_double_counting(tmp_path):
    with closing(Store(tmp_path)) as store:
        tracker = ShinyTracker(store, 'ea9bcae617fdf159b045185467ae58b2e4a48b9a')
        for _ in range(2):
            with store.lock, store.db:
                record(store.db, 'seen', 'encounter', 25)
                record(store.db, 'acquired', 'capture', 25)
        assert status(store)['seen'] == status(store)['acquired'] == 1
    with closing(Store(tmp_path)) as store:
        tracker = ShinyTracker(store, 'ea9bcae617fdf159b045185467ae58b2e4a48b9a')
        with store.lock, store.db:
            record(store.db, 'seen', 'encounter', 25)
            record(store.db, 'acquired', 'capture', 25)
        assert status(store)['seen'] == status(store)['acquired'] == 1
        tracker.reset()
        assert status(store)['seen'] == 0


def test_verified_cartridge_hook_attaches_without_changing_game_ram(tmp_path):
    rom = Path('roms/pokered.gb')
    if not rom.is_file():
        pytest.skip('Private ROM unavailable')
    from pokesim_core.emulator import Emulator as PyBoy
    store = Store(tmp_path)
    pb = PyBoy(str(rom), window='null', ram_file=io.BytesIO(bytes(32768)))
    try:
        before = bytes(pb.memory[0xc000:0xe000])
        ShinyTracker(store, 'ea9bcae617fdf159b045185467ae58b2e4a48b9a').attach(pb)
        assert bytes(pb.memory[0xc000:0xe000]) == before
    finally:
        pb.stop(save=False)
        store.close()


def test_verified_encounter_receipts_ignore_trainers_transform_and_replays(tmp_path):
    from types import SimpleNamespace
    with closing(Store(tmp_path)) as store:
        tracker = ShinyTracker(store, 'ea9bcae617fdf159b045185467ae58b2e4a48b9a')
        memory = bytearray(65536)
        pb = SimpleNamespace(memory=memory)
        memory[0xcfe5] = 153
        memory[0xcff1:0xcff3] = bytes((0x2a, 0xaa))
        memory[0xd057] = 2
        tracker.encounter(pb)
        assert status(store)['seen'] == 0
        memory[0xd057], memory[0xd069] = 1, 8
        tracker.encounter(pb)
        assert status(store)['seen'] == 0
        memory[0xd069] = 0
        tracker.encounter(pb)
        tracker.encounter(pb)
        assert status(store)['seen'] == 1
        assert status(store)['seen_species'] == [1]
        memory[0xc000] = 1
        tracker.encounter(pb)
        assert status(store)['seen'] == 2


def test_shiny_capture_priority_and_pause_without_supplies():
    from dataclasses import replace
    from unittest.mock import Mock
    from test_events import snap
    from test_strategy import mon
    from pokesim.emulator import Emulator
    from pokesim.policies.battle import choose_battle
    from pokesim.strategy_data import ITEMS
    me = mon(level=100, hp=300, max_hp=300, moves=(33,), pp=(35,))
    enemy = mon(level=5, hp=15, max_hp=15, moves=(), pp=())
    snapshot = snap(party=(me,), in_battle=1, enemy_shiny=True,
                    owned=frozenset({1}), items=((ITEMS['POKE_BALL'], 4),))
    choice = choose_battle(snapshot, me, enemy, 0, capture_species=1, catch_attempts=99)
    assert choice.kind == 'item' and choice.index == 0 and 'shiny' in choice.reason
    emu = Emulator.__new__(Emulator)
    emu.manual_mode, emu.paused, emu._autosave = False, False, Mock()
    assert not emu._protect_shiny(snapshot)
    assert emu._protect_shiny(replace(snapshot, items=()))
    assert emu.paused
    emu._autosave.assert_called_once()
    emu.manual_mode = True
    assert not emu._protect_shiny(replace(snapshot, items=()))


def test_shiny_catch_receipt_counts_once_and_preserves_held_badge(tmp_path):
    from pokesim.catches import record_receipt, initialize
    from pokesim.milestones import apply
    with closing(Store(tmp_path)) as store:
        ShinyTracker(store, 'ea9bcae617fdf159b045185467ae58b2e4a48b9a')
        with store.lock, store.db:
            initialize(store.db)
        for _ in range(2):
            with store.lock, store.db:
                record_receipt(store.db, 'catch', 1, shiny=True)
        payload = apply({'party': [{'dex': 1, 'dvs': (0,2,10,10,10)}]}, store)
        assert payload['party'][0]['shiny']
        assert payload['shiny']['acquired'] == payload['shiny']['held'] == 1


def test_shiny_cannot_be_offered_even_with_an_old_explicit_preference(tmp_path):
    from dataclasses import replace
    from pokesim.broker import inventory, routine
    from pokesim.trade import preferences
    from pokesim.web.pokedex import live_status
    from test_milestones import partner
    from test_events import snap
    with closing(Store(tmp_path)) as store:
        mon = replace(partner(25, 5), dvs=(0,2,10,10,10))
        payload = live_status(snap(party=(mon,)).to_dict())
        row = payload['party'][0]
        key = preferences.identity(row)
        with pytest.raises(ValueError, match='Shiny'):
            preferences.update(store, payload, key, 'offered')
        row.update(box=1, position=1, trade_preference='offered')
        payload['party'] = []
        payload['storage']['pokemon'] = [row, {**row, 'position': 2, 'dvs': (15,)*5}]
        inv = inventory.normalise('red', '', payload)
        assert not inv.tradeable
        listed = routine.listings(inv, allow_last_copies=True)
        shiny = next(mon for mon in listed if mon['shiny'])
        assert not shiny['listed'] and not shiny['can_offer'] and not shiny['perfect_dvs']
        assert 'Shiny' in shiny['reason']


def test_npc_trader_cannot_take_shiny_partner():
    from dataclasses import replace
    from pokesim.policies.strategic import StrategicPolicy
    from pokesim.policies.progression import Goal
    from pokesim.screen import Screen
    from test_duplicates import snapshot
    from test_strategy import menu, mon
    partner = mon(trainer_id=100, dvs=(0,2,10,10,10))
    state = snapshot([], party=(partner, mon(level=80)))
    policy = StrategicPolicy(7)
    policy.goal = Goal('collect_trade', 'Trade', 'Meet the trader')
    policy.collection.project = {'give': partner.species, 'map': state.map}
    memory = menu({1: '  BULBASAUR'}, (1, 1), top=(1, 1))
    assert policy._dispatch(state, Screen(memory), 'party', memory)[0].button == 'b'
    state = replace(state, party=(replace(partner, dvs=(8,)*5), mon(level=80)))
    assert policy._dispatch(state, Screen(memory), 'party', memory)[0].button == 'a'
