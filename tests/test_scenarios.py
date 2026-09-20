"""Stuck scenarios: checkpoint edits, and a replay of every private scenario when there are any."""
import json
import os
from pathlib import Path

import pytest

from pokesim.ram import PARTY_STRUCT, W_BAG_ITEMS, W_IS_IN_BATTLE, W_MONEY, W_NUM_BAG_ITEMS, W_PARTY_COUNT, W_PARTY_MONS, read_snapshot
from pokesim.scenarios import (W_BATTLE_MON_HP, W_BATTLE_MON_STATUS, W_PLAYER_MON_NUMBER, Scenario, apply_edits,
                               discover, play)
from pokesim.strategy_data import ITEMS

ROOT = Path(__file__).resolve().parents[1]
ROM = Path(os.environ.get('ROM_PATH', ROOT / 'roms' / 'pokered.gb'))
SCENARIOS = discover(os.environ.get('POKESIM_SCENARIOS', ROOT / 'data' / 'scenarios')) if ROM.exists() else []


def cartridge(party=2, bag=((ITEMS['FULL_RESTORE'], 10), (ITEMS['REVIVE'], 5))):
    mem = bytearray(0x10000)
    mem[W_PARTY_COUNT] = party
    for slot in range(party):
        base = W_PARTY_MONS + slot * PARTY_STRUCT
        mem[base], mem[base + 2], mem[base + 0x21], mem[base + 0x23] = 0x99, 200, 50, 200    # 200/200 HP
        mem[base + 8:base + 12] = bytes((33, 45, 0, 0))                                        # two moves
        mem[base + 29:base + 33] = bytes((0x40 | 35, 40, 0, 0))                                # one PP Up on the first
    mem[W_NUM_BAG_ITEMS] = len(bag)
    for index, (item, quantity) in enumerate(bag):
        mem[W_BAG_ITEMS + index * 2:W_BAG_ITEMS + index * 2 + 2] = bytes((item, quantity))
    mem[W_BAG_ITEMS + len(bag) * 2] = 0xFF
    return mem


def test_party_edits_reach_the_snapshot_the_policy_reads():
    mem = cartridge()
    apply_edits(mem, {'party': [{'slot': 0, 'status': 'frozen', 'hp': 12}, {'slot': 1, 'hp': 0.25, 'pp': 0}]})
    lead, partner = read_snapshot(mem, 0).party
    assert (lead.status, lead.hp, lead.pp) == (32, 12, (35, 40, 0, 0))
    assert (partner.status, partner.hp, partner.pp) == (0, 50, (0, 0, 0, 0))
    assert mem[W_PARTY_MONS + PARTY_STRUCT + 29] == 0x40           # the PP Up survives an empty move
    apply_edits(mem, {'party': [{'slot': 'all', 'status': 'asleep', 'hp': 999}]})
    assert [(mon.status, mon.hp) for mon in read_snapshot(mem, 0).party] == [(3, 200), (3, 200)]


def test_an_edit_during_battle_also_changes_the_active_battler():
    mem = cartridge()
    mem[W_IS_IN_BATTLE], mem[W_PLAYER_MON_NUMBER] = 2, 1
    apply_edits(mem, {'party': [{'slot': 'all', 'status': 'frozen', 'hp': 7}]})
    assert mem[W_BATTLE_MON_STATUS] == 32 and mem[W_BATTLE_MON_HP + 1] == 7
    mem = cartridge()
    apply_edits(mem, {'party': [{'slot': 0, 'status': 'frozen'}]})
    assert mem[W_BATTLE_MON_STATUS] == 0                           # nobody is fighting, so only the party changes


def test_bag_and_money_edits():
    mem = cartridge()
    apply_edits(mem, {'items': {'FULL_RESTORE': 0, 'ICE_HEAL': 3, 'REVIVE': 120}, 'money': 1234})
    snapshot = read_snapshot(mem, 0)
    assert snapshot.items == ((ITEMS['ICE_HEAL'], 3), (ITEMS['REVIVE'], 99)) and snapshot.money == 1234
    assert mem[W_BAG_ITEMS + 4] == 0xFF and bytes(mem[W_MONEY:W_MONEY + 3]) == b'\x00\x12\x34'
    with pytest.raises(ValueError):
        apply_edits(cartridge(bag=tuple((n, 1) for n in range(101, 121))), {'items': {'ICE_HEAL': 1}})


def test_scenarios_are_found_with_their_settings(tmp_path):
    folder = tmp_path / 'league' / 'frozen'
    folder.mkdir(parents=True)
    (folder / 'scenario.json').write_text(json.dumps({'name': 'frozen', 'checkpoint': '../door.state', 'until': 'champion',
                                                      'edits': {'money': 0}, 'budget_game_minutes': 30}))
    scenario, = discover(tmp_path)
    assert scenario.checkpoint == tmp_path / 'league' / 'door.state' and scenario.until == 'champion'
    assert scenario.budget_game_minutes == 30 and scenario.max_quiet_game_minutes == 90 and discover(tmp_path / 'none') == []
    assert Scenario.load(folder).edits == {'money': 0}


@pytest.mark.skipif(os.environ.get('POKESIM_SCENARIO_TESTS') != '1', reason='set POKESIM_SCENARIO_TESTS=1 to replay private scenarios')
@pytest.mark.parametrize('scenario', SCENARIOS, ids=[scenario.name for scenario in SCENARIOS])
def test_the_player_gets_going_again(scenario):
    result = play(scenario, ROM)
    assert result['passed'], f'{result["failure"]} on {result["final_map"]}: {result["objective"]} ({result["reason"]})'
