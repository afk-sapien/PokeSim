"""The boss check: heal before a boss when a Pokémon is under half HP or strong PP (planning/boss.py)."""
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pokesim.planning import boss
from pokesim.policies import ledger as gen1_ledger
from pokesim.ram import PartyMon

FLAMETHROWER, STRENGTH, CUT, SWIFT = 53, 70, 15, 129
MOVES = (FLAMETHROWER, STRENGTH, CUT, SWIFT)
MAX_PP = (15, 15, 30, 20)
# Charizard's internal species number in Red and Blue, and its Pokédex number in Gold.
GEN1_CHARIZARD, GEN2_CHARIZARD = 180, 6

# Equivalent party states, as (HP, PP of each move), for a level 60 Charizard with 180 HP.
STATES = {
    'full': (180, (15, 15, 30, 20)),
    'low hp': (80, (15, 15, 30, 20)),
    'half hp': (90, (15, 15, 30, 20)),
    'strong pp spent, cut full': (180, (0, 0, 30, 20)),
    # Pooled, 16 of 30 strong PP looks ready. Weighted by strength, the spent Flamethrower counts.
    'flamethrower spent, strength full': (180, (2, 14, 30, 20)),
    'both strong attacks at two thirds': (180, (10, 10, 30, 20)),
}


@pytest.fixture(scope='module')
def gen2():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, 'gold')


def gen1_mon(hp, pp):
    return PartyMon(GEN1_CHARIZARD, hp, 180, 60, 'CHARIZARD', moves=MOVES, pp=pp, max_pp=MAX_PP)


def gen2_mon(hp, pp, name='CHARIZARD'):
    return SimpleNamespace(egg=False, species=GEN2_CHARIZARD, level=60, hp=hp, max_hp=180, status=0, name=name,
                           moves=MOVES, pp=pp, max_pp=MAX_PP)


def test_both_generations_read_the_same_party_and_decide_the_same(gen2):
    from pokesim.gen2 import ledger as gen2_ledger
    verdicts = {}
    for name, (hp, pp) in STATES.items():
        first = gen1_ledger.fighters((gen1_mon(hp, pp),))
        second = gen2_ledger.fighters(gen2, SimpleNamespace(party=(gen2_mon(hp, pp),)))
        assert first == second, name
        for reachable in (True, False):
            answers = [boss.Gate().decide('boss', party, lambda: reachable) for party in (first, second)]
            assert answers[0] == answers[1], (name, reachable)
            verdicts[name, reachable] = answers[0]
    assert verdicts['full', True] == verdicts['half hp', True] == boss.READY
    assert verdicts['both strong attacks at two thirds', True] == boss.READY
    for name in ('low hp', 'strong pp spent, cut full', 'flamethrower spent, strength full'):
        assert verdicts[name, True] == boss.HEAL
        assert verdicts[name, False] == boss.UNREADY


def fighters(hp=180, pp=(15, 15, 30, 20)):
    return gen1_ledger.fighters((gen1_mon(hp, pp),))


def test_a_ready_party_goes_straight_in_and_never_searches_for_a_center():
    gate = boss.Gate()
    assert gate.decide('brock', fighters(), lambda: pytest.fail('searched')) == boss.READY
    assert gate.decide(None, fighters(hp=10), lambda: pytest.fail('searched')) == boss.READY


def test_low_hp_heals_and_the_trip_holds_until_the_party_is_ready():
    gate = boss.Gate()
    assert gate.decide('brock', fighters(hp=60), lambda: True) == boss.HEAL
    # The walk to the nurse keeps healing without searching again.
    assert gate.decide('brock', fighters(hp=55), lambda: pytest.fail('searched')) == boss.HEAL
    assert gate.decide('brock', fighters(), lambda: True) == boss.READY
    assert gate.trips == 1


def test_spent_strong_pp_heals_though_weak_attacks_are_full():
    assert boss.Gate().decide('misty', fighters(pp=(3, 4, 30, 20)), lambda: True) == boss.HEAL


def test_an_approach_takes_at_most_its_trips_then_goes_in():
    gate = boss.Gate()
    for _ in range(boss.TRIPS):
        assert gate.decide('red', fighters(hp=60), lambda: True) == boss.HEAL
        assert gate.decide('red', fighters(), lambda: True) == boss.READY
    assert gate.decide('red', fighters(hp=60), lambda: True) == boss.UNREADY
    # A new boss is a new approach.
    assert gate.decide('lance', fighters(hp=60), lambda: True) == boss.HEAL


def trip(gate, key, cave, center):
    """One boss heal trip from ``cave`` to the Center ``center``, and the verdict once it is done."""
    assert gate.decide(key, fighters(hp=60), lambda: True, where=cave) == boss.HEAL
    assert gate.decide(key, fighters(hp=60), lambda: pytest.fail('searched'), where=center, center=True) == boss.HEAL
    return gate.decide(key, fighters(), lambda: True, where=center, center=True)


def test_victory_road_trips_used_up_still_heal_at_the_indigo_center():
    from pokesim.policies.progression import MAPS
    road, viridian, lobby = MAPS['VICTORY_ROAD_2F'], MAPS['VIRIDIAN_POKECENTER'], MAPS['INDIGO_PLATEAU_LOBBY']
    gate = boss.Gate()
    for _ in range(boss.TRIPS):
        assert trip(gate, 'league_lorelei', road, viridian) == boss.READY
    assert gate.decide('league_lorelei', fighters(hp=60), lambda: True, where=road) == boss.UNREADY
    assert gate.note()
    # The Indigo Plateau lobby is a Center the walk to Lorelei crosses, so it starts a new leg.
    assert gate.decide('league_lorelei', fighters(hp=60), lambda: True, where=lobby, center=True) == boss.HEAL
    assert gate.decide('league_lorelei', fighters(), lambda: True, where=lobby, center=True) == boss.READY
    assert gate.trips == 1


def test_the_trip_cap_still_stops_a_heal_loop_within_one_leg():
    gate = boss.Gate()
    for _ in range(boss.TRIPS):
        assert trip(gate, 'league_lorelei', 'cave', 'center') == boss.READY
    assert gate.trips == boss.TRIPS
    # Back at the same Center the leg goes on, so the cave cannot send the party there again.
    assert gate.decide('league_lorelei', fighters(hp=60), lambda: True, where='cave') == boss.UNREADY
    assert gate.decide('league_lorelei', fighters(hp=60), lambda: True, where='center', center=True) == boss.UNREADY
    assert gate.decide('league_lorelei', fighters(hp=59), lambda: True, where='cave') == boss.UNREADY
    assert gate.note() and not gate.note()


def test_a_finished_boss_heal_trip_writes_one_quiet_journal_row():
    from pokesim.policies.strategic import StrategicPolicy
    from test_events import snap
    policy = StrategicPolicy(7)
    policy.nav.distance_lookup = lambda pos, frame: (lambda targets: 12)
    goal = SimpleNamespace(key='league_lorelei', title='Challenge Lorelei')
    assert policy._boss_check(snap(party=(gen1_mon(60, MAX_PP),)), goal, False) == boss.HEAL
    assert policy._boss_check(snap(party=(gen1_mon(180, MAX_PP),)), goal, False) == boss.READY
    policy._boss_check(snap(party=(gen1_mon(180, MAX_PP),), x=6), goal, False)
    rows = [row for row in policy.collection.activity_events if row['title'].startswith('Healed before')]
    assert len(rows) == 1 and rows[0]['title'] == 'Healed before Lorelei'
    assert rows[0]['type'] == 'plan' and rows[0]['priority'] == 1 and rows[0]['notable'] is False
    from pokesim.events import Event
    assert not Event(**rows[0]).notable


def test_gen1_logs_a_pp_heal_once_the_nurse_restores_spent_attacks():
    from pokesim.policies.progression import MAPS
    from pokesim.policies.strategic import StrategicPolicy
    from test_events import snap
    policy = StrategicPolicy(7)
    spent = (replace(gen1_mon(180, (0, 0, 0, 0)), max_pp=MAX_PP),)
    policy.heal.update(policy, snap(party=spent))
    assert policy.heal.latched and policy.heal.pp
    center = MAPS['CERULEAN_POKECENTER']
    policy.heal.update(policy, snap(party=(gen1_mon(180, MAX_PP),), map=center))
    rows = [row for row in policy.collection.activity_events if row['title'].startswith('PP heal')]
    assert len(rows) == 1 and rows[0]['title'] == f'PP heal at {snap(map=center).map_name}'
    assert rows[0]['priority'] == 1 and rows[0]['notable'] is False
    assert not policy.heal.latched and not policy.heal.pp
    # A heal for HP alone writes no PP row.
    policy.heal.update(policy, snap(party=(gen1_mon(30, MAX_PP),)))
    policy.heal.update(policy, snap(party=(gen1_mon(180, MAX_PP),), map=center))
    assert len([row for row in policy.collection.activity_events if row['title'].startswith('PP heal')]) == 1


def test_no_center_in_reach_goes_in_unready_and_says_so_once():
    gate = boss.Gate()
    party = fighters(hp=60)
    assert gate.decide('sabrina', party, lambda: False) == boss.UNREADY
    assert gate.note() and not gate.note()
    event = boss.unready_event('Challenge Sabrina', party, ['CHARIZARD'])
    assert event['type'] == 'plan' and event['title'] == 'Went in unready: Challenge Sabrina'
    assert 'CHARIZARD' in event['body']


def test_gen1_writes_the_unready_journal_row_when_no_nurse_is_in_reach():
    from pokesim.policies.strategic import StrategicPolicy
    from test_events import snap
    policy = StrategicPolicy(7)
    s = snap(party=(replace(gen1_mon(60, (15, 15, 30, 20)), nick='SPARKY'),))
    goal = SimpleNamespace(key='marsh', title='Challenge Sabrina')
    assert policy._boss_check(s, goal, in_league=True) == boss.UNREADY
    assert not policy.heal.before_boss
    policy._boss_check(s, goal, in_league=True)
    rows = [row for row in policy.collection.activity_events if row['title'].startswith('Went in unready')]
    assert len(rows) == 1 and rows[0]['title'] == 'Went in unready: Challenge Sabrina'
    assert 'SPARKY' in rows[0]['body']


def test_gen1_latches_the_heal_when_a_nurse_is_in_reach():
    from pokesim.policies.strategic import StrategicPolicy
    from test_events import snap
    policy = StrategicPolicy(7)
    policy.nav.distance_lookup = lambda pos, frame: (lambda targets: 12)
    s = snap(party=(gen1_mon(60, (15, 15, 30, 20)),))
    assert policy._boss_check(s, SimpleNamespace(key='marsh', title='Challenge Sabrina'), False) == boss.HEAL
    assert policy.heal.before_boss
    # A goal that is not a boss challenge never heals for the boss check.
    assert policy._boss_check(s, SimpleNamespace(key='marsh', title='Answer the quiz'), False) == boss.READY


def gen2_policy(data, monkeypatch, center):
    from pokesim.gen2 import ledger
    from pokesim.gen2.policy import Policy
    monkeypatch.setattr(ledger, 'walk_spent', lambda data, snapshot, goal='walk': False)
    policy = Policy(data, seed=1, starter='cyndaquil')
    policy.goal = SimpleNamespace(key='red', label='Battle Red')
    monkeypatch.setattr(policy, 'center', lambda snapshot: center)
    return policy


def gen2_snapshot(data, hp):
    return SimpleNamespace(map=data.map_ids['SILVER_CAVE_ROOM_3'], x=9, y=10, frame=0, badges=255,
                           party=(gen2_mon(hp, (15, 15, 30, 20)),), event=lambda name: True)


def test_gen2_heals_before_red_when_a_center_is_in_reach(gen2, monkeypatch):
    mid = gen2.map_ids['SILVER_CAVE_POKECENTER_1F']
    nurse = next(obj for obj in gen2.maps[mid]['objects'] if obj['sprite'] == 'SPRITE_NURSE')
    policy = gen2_policy(gen2, monkeypatch, (mid, nurse))
    goal = healing(policy, gen2_snapshot(gen2, 60))
    assert goal is not None and goal.map_name == 'SILVER_CAVE_POKECENTER_1F'
    assert healing(policy, gen2_snapshot(gen2, 180)) is None


def healing(policy, snapshot):
    """The heal goal Gold, Silver and Crystal offer now, or None."""
    goal, commit = policy.heal.offer(policy, snapshot)
    assert commit is None
    return goal


def test_gen2_writes_the_unready_journal_row_when_no_center_is_in_reach(gen2, monkeypatch):
    from pokesim.gen2.collection import pin_events
    policy = gen2_policy(gen2, monkeypatch, None)
    assert healing(policy, gen2_snapshot(gen2, 60)) is None
    assert healing(policy, gen2_snapshot(gen2, 59)) is None
    rows = [row for row in pin_events(policy) if row['title'].startswith('Went in unready')]
    assert len(rows) == 1 and rows[0]['title'] == 'Went in unready: Battle Red'


def test_gen2_starts_a_leg_at_the_indigo_plateau_center(gen2, monkeypatch):
    from pokesim.gen2.collection import pin_events
    mid = gen2.map_ids['INDIGO_PLATEAU_POKECENTER_1F']
    nurse = next(obj for obj in gen2.maps[mid]['objects'] if obj['sprite'] == 'SPRITE_NURSE')
    policy = gen2_policy(gen2, monkeypatch, (mid, nurse))
    policy.goal = SimpleNamespace(key='league_will', label='Challenge Will')
    # The trips of this approach are spent in Victory Road.
    policy.boss_gate = boss.Gate()
    policy.boss_gate.key, policy.boss_gate.trips = 'league_will', boss.TRIPS
    road = replace_map(gen2_snapshot(gen2, 60), gen2.map_ids['VICTORY_ROAD'])
    assert healing(policy, road) is None
    lobby = replace_map(gen2_snapshot(gen2, 60), mid)
    assert healing(policy, lobby).map_name == 'INDIGO_PLATEAU_POKECENTER_1F'
    assert healing(policy, replace_map(gen2_snapshot(gen2, 180), mid)) is None
    rows = [row['title'] for row in pin_events(policy)]
    assert 'Healed before Will' in rows


def replace_map(snapshot, mid):
    snapshot.map = mid
    return snapshot


def test_gen2_logs_a_pp_heal_at_the_center(gen2, monkeypatch):
    from pokesim.gen2.collection import pin_events
    from pokesim.gen2.policy import Policy
    mid = gen2.map_ids['SILVER_CAVE_POKECENTER_1F']
    nurse = next(obj for obj in gen2.maps[mid]['objects'] if obj['sprite'] == 'SPRITE_NURSE')
    policy = Policy(gen2, seed=1, starter='cyndaquil')
    policy.goal = SimpleNamespace(key='walk', label='Walk on')
    monkeypatch.setattr(policy, 'center', lambda snapshot: (mid, nurse))
    spent = gen2_snapshot(gen2, 180)
    spent.party = (gen2_mon(180, (0, 0, 30, 20)),)
    assert healing(policy, spent).map_name == 'SILVER_CAVE_POKECENTER_1F'
    assert policy.heal.pp
    assert healing(policy, replace_map(gen2_snapshot(gen2, 180), mid)) is None
    rows = [row for row in pin_events(policy) if row['title'].startswith('PP heal')]
    assert len(rows) == 1 and rows[0]['title'] == f"PP heal at {gen2.maps[mid]['name']}"
    assert rows[0]['priority'] == 1 and rows[0]['notable'] is False


def test_the_league_kit_spends_half_the_spare_money():
    # 1431 spare at Hyper Potion prices buys nothing: half of it is under one potion.
    assert boss.kit(0, 0, 1431, 1200, 1500) == (0, 0)
    assert boss.kit(0, 0, 14856, 1200, 1500) == (5, 0)
    assert boss.kit(0, 0, 40000, 1200, 1500) == (5, 2)
    # Restores and Revives already in the bag count toward the kit.
    assert boss.kit(4, 1, 40000, 1200, 1500) == (1, 1)
    assert boss.kit(9, 3, 40000, 1200, 1500) == (0, 0)
    # Bought over several trips, the kit stops at the same share of the money.
    bag, money = 0, 6000
    while boss.kit(bag, 0, money, 1200, 1500)[0]:
        bag, money = bag + 1, money - 1200
    assert (bag, money) == (2, 3600)


HYPER = boss.Medicine(16, boss.RESTORE, 200)
SUPER = boss.Medicine(17, boss.RESTORE, 50)
FULL = boss.Medicine(14, boss.RESTORE)
REVIVE = boss.Medicine(39, boss.REVIVE, 50)
ETHER = boss.Medicine(63, boss.ETHER, 10)
ELIXIR = boss.Medicine(65, boss.ELIXIR, 10)
STRENGTHS = (90, 70, 0, 0)


def member(hp, pp=(15, 15, 30, 20), level=60):
    return boss.Member(level, hp, 180, STRENGTHS, pp, MAX_PP)


def test_league_items_revive_first_then_lift_past_the_bar():
    filler = boss.Member(7, 0, 25, (20, 0, 0, 0), (35, 0, 0, 0), (35, 0, 0, 0))
    party = (member(30), member(0), filler)
    assert boss.treatment(party, (SUPER, HYPER, REVIVE)) == (1, REVIVE, None)
    # The smallest restore that lifts 30 of 180 HP past half is a Hyper Potion. A Super Potion lifts 60.
    assert boss.treatment(party[:1], (FULL, SUPER, HYPER)) == (0, HYPER, None)
    assert boss.treatment((member(60),), (FULL, SUPER, HYPER)) == (0, SUPER, None)
    # With no restore that lifts it, the largest one goes in.
    assert boss.treatment((member(10),), (SUPER,)) == (0, SUPER, None)
    # A fainted level 7 filler is not worth a Revive.
    assert boss.treatment((member(180), filler), (REVIVE,)) is None
    assert boss.treatment((member(180),), (HYPER, REVIVE, ETHER)) is None


def test_league_items_restore_the_spent_strong_move():
    # Flamethrower is spent and Strength is full: an Ether on Flamethrower, not an Elixir.
    assert boss.treatment((member(180, (2, 14, 30, 20)),), (ETHER, ELIXIR)) == (0, ETHER, 0)
    # Both strong attacks spent takes the Elixir.
    assert boss.treatment((member(180, (1, 1, 30, 20)),), (ETHER, ELIXIR)) == (0, ELIXIR, None)
    assert boss.treatment((member(180, (1, 1, 30, 20)),), (ETHER,)) == (0, ETHER, 0)
    assert boss.treatment((member(180, (1, 1, 30, 20)),), (HYPER, REVIVE)) is None


def test_the_bag_heals_where_no_center_is_in_reach():
    gate = boss.Gate()
    low = (boss.fighter(60, 180, list(STRENGTHS), [15, 15, 30, 20], list(MAX_PP)),)
    for _ in range(boss.TRIPS + 2):
        assert gate.decide('league_will', low, lambda: False, where=1, supply=True) == boss.HEAL
    assert gate.trips == 0
    assert gate.decide('league_will', low, lambda: False, where=1) == boss.UNREADY


def league_policy(gen2, key='league_will'):
    from pokesim.gen2.policy import Policy
    policy = Policy(gen2, seed=1, starter='cyndaquil')
    policy.goal = SimpleNamespace(key=key, label='Challenge Will', map_name='WILLS_ROOM')
    return policy


def league_snapshot(gen2, party, items=(), money=0, room='WILLS_ROOM'):
    return SimpleNamespace(map=gen2.map_ids[room], x=5, y=5, frame=0, badges=255, party=party, items=tuple(items),
                           pockets={'items': tuple(items), 'balls': ()}, money=money, hall_of_fame_count=0,
                           can_catch=False, in_battle=0, owned=(), stored=(), event=lambda name: True)


def test_gen2_buys_the_league_kit_before_the_first_room(gen2):
    from pokesim.gen2 import ledger
    policy = league_policy(gen2)
    lobby = league_snapshot(gen2, (gen2_mon(180, (15, 15, 30, 20)),), money=14856, room='INDIGO_PLATEAU_POKECENTER_1F')
    assert ledger.supplies(policy, lobby) == [('potions', ('HYPER_POTION',), 5)]
    stocked = league_snapshot(gen2, lobby.party, items=((gen2.items['HYPER_POTION'], 5),), money=14856)
    assert ledger.supplies(policy, stocked) == [('revives', ('REVIVE',), 2)]
    # Back from a loss to Lance, a training goal shops by the same kit: half of 7133 buys two.
    training = league_policy(gen2, 'collection_train')
    back = league_snapshot(gen2, lobby.party, money=7133, room='INDIGO_PLATEAU_POKECENTER_1F')
    assert ledger.supplies(training, back) == [('potions', ('HYPER_POTION',), 2)]


def test_gen2_uses_league_items_between_rooms(gen2):
    from pokesim.gen2.menus import Remedy, UseOn
    policy = league_policy(gen2)
    hyper, ether = gen2.items['HYPER_POTION'], gen2.items['ETHER']
    hurt = league_snapshot(gen2, (gen2_mon(40, (15, 15, 30, 20)),), items=((hyper, 2), (ether, 1)))
    assert policy.league_items(hurt) and policy.menu == Remedy(hyper, 0, 2)
    spent = league_snapshot(gen2, (gen2_mon(180, (1, 15, 30, 20)),), items=((hyper, 2), (ether, 1)))
    found = policy.league_items(spent) and policy.menu
    assert isinstance(found, UseOn) and (found.item, found.slot, found.move) == (ether, 0, 0)
    assert not policy.league_items(league_snapshot(gen2, (gen2_mon(180, (15, 15, 30, 20)),), items=((hyper, 2),)))
    # A short fighter the bag can treat is healed in the room, not sent in unready.
    assert policy.boss_ready(hurt, True) == boss.HEAL
    assert policy.boss_ready(league_snapshot(gen2, (gen2_mon(40, (15, 15, 30, 20)),)), True) == boss.UNREADY
