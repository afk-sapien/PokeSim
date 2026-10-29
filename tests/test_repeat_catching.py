from dataclasses import replace
import random
from types import SimpleNamespace

import pytest

from pokesim.planning import values
from pokesim.policies.collection import Collection, held_count
from pokesim.policies.director import AdventureDirector
from pokesim.policies.battle import choose_battle
from pokesim.policies.progression import Goal
from pokesim.runtime.participant import Participant
from test_collection import state, sid
from test_strategy import mon
from pokesim.strategy_data import ITEMS, MAPS


def test_repeat_project_requires_a_new_individual_and_survives_reload():
    target = sid(69)
    s = state(owned=frozenset({1, 69}), stored_pokemon=((0, target, 5, ''),))
    c = Collection()
    c.project = {'species': target, 'method': 'grass', 'map': MAPS['ROUTE_1'],
                 'repeat': True, 'initial_count': 1, 'key': 'repeat'}
    c.remaining = 36000
    c.observe(s)
    assert c.project is not None
    restored = Collection()
    restored.load(c.state_dict())
    restored.observe(replace(s, frame=120))
    assert restored.project is not None
    restored.observe(replace(s, frame=240, stored_pokemon=s.stored_pokemon * 2))
    assert restored.project is None
    assert restored.director.completed['collection'] == 1
    assert str(target) in restored.last_repeat


def test_repeat_catching_uses_normal_balls_with_a_bounded_attempt_budget():
    target = sid(69)
    me = mon(level=100, hp=200, max_hp=200, moves=(33,), pp=(35,))
    enemy = mon(species=target, level=5, hp=10, max_hp=10, moves=(), pp=())
    s = state(party=(me,), owned=frozenset({1, 69}), in_battle=1)
    assert choose_battle(s, me, enemy, 0, repeat_species=target).kind == 'item'
    assert choose_battle(s, me, enemy, 0, repeat_species=target, catch_attempts=5).kind != 'item'
    only_master = replace(s, items=((ITEMS['MASTER_BALL'], 1),))
    assert choose_battle(only_master, me, enemy, 0, repeat_species=target).kind != 'item'


def test_known_species_are_proposed_as_repeat_expeditions(monkeypatch):
    target = sid(69)
    c = Collection()
    c.completed_champion = True
    monkeypatch.setattr(c, 'sources', lambda: {target: [{'method': 'grass', 'map': MAPS['ROUTE_1'], 'level': 3}]})
    monkeypatch.setattr(c, 'available', lambda s, source: True)
    captured = []
    def select(options, projects):
        captured.extend((option, projects[option.key]) for option in options)
        return next(project for project in projects.values() if project.get('repeat'))
    monkeypatch.setattr(c.director, 'select', select)
    nav = SimpleNamespace(distance_lookup=lambda *args: lambda points: 10, can_surf=True, visits={}, path=[])
    s = state(map=MAPS['ROUTE_1'], owned=frozenset(range(1, 152)), money=50000)
    c.choose(s, nav, random.Random(1), Goal('collect_plan', '', ''))
    assert c.project['species'] == target and c.project['repeat']
    assert c.project['initial_count'] == 0
    assert any(option.value > 0 and project.get('repeat') for option, project in captured)


def test_compact_and_complete_box_views_do_not_double_count():
    target = sid(69)
    s = state(boxed_pokemon=((target, 5),), stored_pokemon=((0, target, 5, ''),))
    assert held_count(s, target) == 1
    assert held_count(replace(s, stored_pokemon=()), target) == 1


def test_peer_requests_expire_and_are_not_checkpoint_state(monkeypatch):
    c = Collection()
    c.set_demand({69: 2})
    assert c.demand() == {69: 2}
    restored = Collection()
    restored.load(c.state_dict())
    assert restored.demand() == {}
    monkeypatch.setattr('pokesim.policies.collection.time.monotonic', lambda: c.demand_until + 1)
    assert c.demand() == {}


def test_peer_requests_take_priority_over_routine_repeat_hunts(monkeypatch):
    c = Collection()
    c.completed_champion = True
    c.set_demand({69: 2})
    sources = {sid(dex): [{'method': 'grass', 'map': MAPS['ROUTE_1'], 'level': 3}]
               for dex in (16, 69)}
    monkeypatch.setattr(c, 'sources', lambda: sources)
    monkeypatch.setattr(c, 'available', lambda s, source: True)
    captured = []
    def select(options, projects):
        # Only the two hunts, so the rods and the rest of the plan take no part.
        hunts = [option for option in options if projects[option.key]['method'] == 'grass']
        captured.extend(hunts)
        return AdventureDirector.select(hunts, projects)
    monkeypatch.setattr(c.director, 'select', select)
    nav = SimpleNamespace(distance_lookup=lambda *args: lambda points: 10, can_surf=True, visits={}, path=[])
    c.choose(state(map=MAPS['ROUTE_1'], owned=frozenset(range(1, 152)), money=50000),
             nav, random.Random(1), Goal('collect_plan', '', ''))
    assert c.project['species'] == sid(69) and c.project['needed_capture']
    # The routine hunt is still offered, and a requested copy is worth a new entry to it.
    assert sorted(option.value for option in captured) == [values.SMALL, values.NEW_ENTRY]


def test_demand_keeps_needed_copies_without_blocking_all_duplicate_cleanup():
    from pokesim.policies.strategic import StrategicPolicy
    from test_duplicates import snapshot, stored
    policy = StrategicPolicy(1)
    copies = [stored(i, species=sid(69), level=10 + i) for i in range(3)]
    policy.collection.set_demand({69: 3})
    assert policy._release_target(snapshot(copies)) is None
    policy.collection.set_demand({69: 2})
    assert policy._release_target(snapshot(copies)) == (0, 0)


def test_a_hunt_stocks_thirty_balls_only_while_the_purse_stays_above_funds_needed():
    from pokesim.policies.shopping import ShoppingController
    from pokesim.policies.ledger import funds_needed
    hunt = {'method': 'grass', 'species': sid(16), 'map': MAPS['ROUTE_1'], 'repeat': True, 'key': 'hunt'}
    stock = [ITEMS['ULTRA_BALL']]
    rich = state(money=100000, items=((ITEMS['ULTRA_BALL'], 15), (ITEMS['POTION'], 3)))
    assert ShoppingController.item_for(rich, stock, 'collect_hunt', hunt) == ITEMS['ULTRA_BALL']
    assert ShoppingController.item_for(rich, stock, 'collect_hunt', None) is None
    full = replace(rich, items=((ITEMS['ULTRA_BALL'], 30), (ITEMS['POTION'], 3)))
    assert ShoppingController.item_for(full, stock, 'collect_hunt', hunt) is None
    tight = replace(rich, money=funds_needed(rich) + 1000)
    assert ShoppingController.item_for(tight, stock, 'collect_hunt', hunt) is None
    # Below the collecting 15 the cash reserve alone still decides.
    low = replace(tight, items=((ITEMS['ULTRA_BALL'], 9), (ITEMS['POTION'], 3)))
    assert ShoppingController.item_for(low, stock, 'collect_hunt', hunt) == ITEMS['ULTRA_BALL']


def test_a_hunt_does_not_start_a_mart_trip_its_purse_cannot_fund():
    from pokesim.policies.shopping import ShoppingController
    hunt = {'method': 'grass', 'species': sid(58), 'map': MAPS['ROUTE_1'], 'repeat': True, 'key': 'hunt'}
    goal = Goal('collect_hunt', 'Hunt', 'Hunt')

    def plan(money, balls, project=hunt):
        s = state(map=MAPS['ROUTE_1'], money=money, items=((ITEMS['POKE_BALL'], balls), (ITEMS['POTION'], 3)))
        return ShoppingController().plan(s, goal, project, requested_goal=goal.key, healing=False,
                                         in_league=False, has_pokedex=True, completed_champion=True)
    assert plan(100000, 7).goal.key == 'restock'
    # Seven balls hunt on without a trip that would come back with one or two.
    short = plan(500, 7)
    assert short.goal is goal and short.abandon is None
    # Below the five a hunt needs to start, it ends so a rematch can refill the purse.
    broke = plan(500, 3)
    assert broke.goal is goal and broke.abandon == 'The purse cannot buy the balls this hunt needs'
    # Outside a hunt the trip is planned as before.
    assert plan(500, 3, project=None).goal.key == 'restock'


@pytest.mark.parametrize('requests', [{'0': 1}, {'152': 1}, {'69': -1}, {'69': True}, []])
def test_invalid_peer_demand_is_rejected(requests):
    participant = object.__new__(Participant)
    participant.emu = SimpleNamespace(policy=SimpleNamespace(collection=Collection()))
    with pytest.raises(ValueError):
        participant.collection_demand({'requests': requests})
