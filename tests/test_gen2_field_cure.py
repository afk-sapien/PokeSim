"""A status a cure in the bag clears is treated where the party stands in Gold, Silver and Crystal.

Any status leaves the walk no HP budget (ledger.battle_room), so a poison at 140 of 150 HP sent the run
to a Pokémon Center. Outside the League the run used no cure in the field, and the shop never stocked
one. Red, Blue and Yellow had the same gap in their own code (tests/test_field_cure.py).
"""
import os
import random
from dataclasses import replace

import pytest

from pokesim.gen2.data import GameData
from tests.test_step_budget import gen2_mon

POISON, PARALYSIS = 8, 64


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def snapshot(data, place, items, status=POISON, entries=0):
    from pokecore.gen2.ram import Snapshot
    rng = random.Random(7)
    lead = replace(gen2_mon(data, rng, 157, 40, (53, 15, 70, 98)), hp=140, status=status)
    party = (lead, gen2_mon(data, rng, 181, 38, (84, 86, 9, 113)))
    filler = tuple((item, 1) for item in sorted(data.item_attributes)
                   if item not in {data.items[name] for name, _ in items})[:entries]
    pocket = tuple((data.items[name], count) for name, count in items) + filler
    balls = ((data.items['POKE_BALL'], 10),)
    return Snapshot(
        frame=100, map=data.map_ids[place], x=3, y=5, player_name='GOLD', rival_name='SILVER', party=party,
        stored=(), box_counts=(0,) * 14, active_box=0, owned=frozenset({157, 181}), seen=frozenset({157, 181}),
        badges=0x3F, items=balls + pocket, pockets={'items': pocket, 'balls': balls, 'key': (), 'machines': ()},
        money=5000, coins=0, in_battle=0, enemy_species=0, enemy_level=0, enemy_hp=0, enemy_max_hp=0,
        trainer_class=0, battle_type=0, playtime=(10, 0, 0), hall_of_fame_count=0, event_flags=bytes([255] * 256),
        tiles=(' ' * 20,) * 18, objects=(), valid=True, data=data)


def policy_with_center(data, monkeypatch):
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(data, seed=1, starter='cyndaquil')
    policy.goal = Goal('route_34', 'Walk to Goldenrod City', 'ROUTE_34', 8, 6)
    mid = data.map_ids['GOLDENROD_POKECENTER_1F']
    nurse = next(obj for obj in data.maps[mid]['objects'] if obj['sprite'] == 'SPRITE_NURSE')
    monkeypatch.setattr(policy, 'center', lambda snapshot: (mid, nurse))
    return policy


def test_a_status_a_cure_in_the_bag_clears_sends_no_heal_walk(data, monkeypatch):
    policy = policy_with_center(data, monkeypatch)
    assert policy.healing(snapshot(data, 'ROUTE_34', [('ANTIDOTE', 1)])) is None
    # A Full Restore is kept for the HP it restores, and an Antidote does not wake a sleeper.
    assert policy.healing(snapshot(data, 'ROUTE_34', [('FULL_RESTORE', 3)])).key == 'heal'
    assert policy.healing(snapshot(data, 'ROUTE_34', [('ANTIDOTE', 1)], status=2)).key == 'heal'


def test_the_field_cure_is_the_cheapest_cure_and_keeps_full_restores(data, monkeypatch):
    from pokesim.gen2.menus import Remedy
    policy = policy_with_center(data, monkeypatch)
    bag = [('FULL_RESTORE', 3), ('FULL_HEAL', 1), ('ANTIDOTE', 2)]
    assert policy.field_cure(snapshot(data, 'ROUTE_34', bag))
    assert policy.menu == Remedy(data.items['ANTIDOTE'], 0, 2)
    assert policy.field_cure(snapshot(data, 'ROUTE_34', bag, status=PARALYSIS))
    assert policy.menu == Remedy(data.items['FULL_HEAL'], 0, 1)
    assert not policy.field_cure(snapshot(data, 'ROUTE_34', [('FULL_RESTORE', 3)]))


def test_a_mart_adds_cures_to_a_bag_without_any(data, monkeypatch):
    from pokesim.gen2 import ledger
    policy = policy_with_center(data, monkeypatch)
    mart = next(entry['constant'] for entry in data.maps.values()
                if any(data.items['ANTIDOTE'] in shop['items'] for shop in entry['shops']))

    def cures(place, items, entries=0):
        return [row for row in ledger.supplies(policy, snapshot(data, place, items, entries=entries))
                if row[0] == 'cures']
    assert cures(mart, [('POTION', 3)]) == [('cures', ('ANTIDOTE', 'FULL_HEAL'), 2)]
    # No trip is made for cures alone, a cure already in the bag is enough, and a full pocket takes none.
    assert cures('ROUTE_34', [('POTION', 3)]) == []
    assert cures(mart, [('BURN_HEAL', 1)]) == []
    assert cures(mart, [('POTION', 3)], entries=19) == []


def test_a_mart_counter_with_no_clerk_adds_no_cures(data, monkeypatch):
    # Mahogany Mart's second counter sells Antidotes, and its clerk is away until the hideout is cleared.
    # A Silver run walking through to the hideout went on a restock trip to Ecruteak for cures alone.
    from pokesim.gen2 import ledger
    policy = policy_with_center(data, monkeypatch)

    def cures(*events):
        flags = bytearray(256)
        for name in events:
            flags[data.events[name] // 8] |= 1 << data.events[name] % 8
        at = replace(snapshot(data, 'MAHOGANY_MART_1F', [('POTION', 3)]), event_flags=bytes(flags))
        return [row for row in ledger.supplies(policy, at) if row[0] == 'cures']
    assert cures('EVENT_MAHOGANY_MART_OWNERS') == []
    assert cures('EVENT_TEAM_ROCKET_BASE_POPULATION') == [('cures', ('ANTIDOTE', 'FULL_HEAL'), 2)]
