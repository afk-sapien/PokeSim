import json
import random
from dataclasses import asdict, replace
from collections import Counter

from pokesim.duplicates import dv_quality
from pokesim.policies.collection import Collection
from pokesim.policies.director import AdventureDirector
from pokesim.policies.team import release_target
from pokesim.trade.preferences import identity
from test_level100_priority import candidates, individual, pick, postgame, train
from test_collection import sid
from test_duplicates import snapshot, stored


def test_a_lv_3_copy_with_rare_dvs_outranks_an_untrained_lv_100_copy():
    # Level is not in the value, since any copy can be trained, so the common Lv 100 copy goes.
    low = stored(0, level=3, dvs=(13, 15, 13, 15, 15))
    high = stored(1, level=100, dvs=(0,) * 5)
    assert release_target(snapshot([low, high])) == (0, 1)
    assert release_target(snapshot([low, high]), reserved={(0, 1)}) is None


def test_training_chooses_best_dvs_within_species_even_at_lower_level():
    good = replace(individual(5, 1, 10), dvs=(15,) * 5)
    weak = replace(individual(99, 2, 10), dvs=(1,) * 5)
    rows = candidates(postgame(party=(good, weak)))
    train = [p for _, p in rows if p['method'] == 'train']
    assert len(train) == 1
    assert train[0]['trainee_key'] == identity(asdict(good))
    assert train[0]['perfect_partner']


def test_perfect_partners_in_different_families_can_each_train():
    partners = tuple(replace(individual(5, 1, species), dvs=(15,) * 5) for species in (10, 13))
    train = [p for _, p in candidates(postgame(party=partners)) if p['method'] == 'train']
    assert len(train) == 2
    assert {Collection.trainee(postgame(party=partners), p) for p in train} == {0, 1}


def test_high_dv_registered_evolution_tracks_exact_partner_until_it_evolves():
    weak = replace(individual(20, 2, 25), dvs=(1,) * 5)
    good = replace(individual(5, 1, 25), dvs=(15,) * 5)
    evolved = replace(individual(100, 3, 26), dvs=(5,) * 5)
    s = postgame(party=(weak, good, evolved))
    projects = [p for _, p in candidates(s) if p['method'] == 'evolve' and p['parent'] == sid(25)]
    assert len(projects) == 1
    c = Collection()
    c.project = projects[0]
    c.remaining = 10000
    assert c.trainee(s, c.project) == 1
    c.observe(s)
    assert c.project is not None
    c.observe(replace(s, frame=120, party=(weak, replace(good, species=sid(26)), evolved)))
    assert c.project is None
    assert c.director.completed['evolution'] == 1


def test_hunts_go_to_the_species_with_the_poorest_best_copy_whatever_its_number_of_routes():
    hunt = {'method': 'grass', 'repeat': True, 'dv_hunt': True, 'catch_goal': 3}
    rows = [{**hunt, 'key': f'route-{i}', 'species': sid(16), 'map': 12} for i in range(50)]
    rows += [{**hunt, 'key': 'caterpie', 'species': sid(10), 'map': 51}]
    assert pick(*rows, tails={sid(16): 10, sid(10): 80}) == 'caterpie'
    # Once the catches improve its best copy, the turn passes to the other species.
    assert pick(*rows, tails={sid(16): 60, sid(10): 20}) == 'route-0'


def test_training_toward_a_credit_ranks_above_every_quality_hunt():
    from pokesim.planning.arbiter import Tier
    from pokesim.policies.collection import HUNT_TIER, candidate
    hunt = {'method': 'grass', 'key': 'hunt', 'species': sid(10), 'map': 51, 'repeat': True, 'dv_hunt': True,
            'catch_goal': 3}
    # A hunt for a poor best copy beats training that earns no credit.
    assert pick(train('train', 90, mastery=False), hunt, tails={sid(10): 100}) == 'hunt'
    # Training toward a level 100 credit goes first, even from level 10 against the poorest best copy.
    assert pick(train('train', 90), hunt, tails={sid(10): 10}) == 'train'
    assert pick(train('train', 10), hunt, tails={sid(10): 100}) == 'train'
    assert HUNT_TIER > Tier.UPGRADE
    assert candidate(hunt, 10, {sid(10): 100}, False, set()).tier == HUNT_TIER
    assert candidate(train('train', 10), 10, {}, False, set()).tier == Tier.UPGRADE


def test_a_quality_hunt_ranks_below_training():
    from pokesim.planning import arbiter
    from pokesim.planning.arbiter import Tier
    from pokesim.policies.collection import candidate
    hunt = {'method': 'grass', 'key': 'hunt', 'species': sid(10), 'map': 51, 'repeat': True, 'dv_hunt': True,
            'catch_goal': 3}
    quality = candidate(hunt, 10, {sid(10): 100}, False, set())
    trainer = candidate(train('train', 10), 10, {}, False, set())
    assert trainer.tier == Tier.UPGRADE
    assert arbiter.choose([quality, trainer]) is trainer


def test_the_plan_placeholder_and_its_errands_rank_as_filler():
    from types import SimpleNamespace
    from pokesim.planning.arbiter import Candidate, Tier, choose
    from pokesim.policies.pipeline import Ballot
    from pokesim.policies.strategic import goal_candidate
    plan = goal_candidate(SimpleNamespace(key='collect_plan'), None, kind='plan')
    assert plan.tier == Tier.FILLER
    errand = Ballot(SimpleNamespace(key='collect_plan'), plan).errand_candidate('buy', 'buy')
    assert errand.tier == Tier.FILLER
    # A filler side project beats the worthless plan placeholder.
    side = Candidate('buy_tm', Tier.FILLER, 1.0, 1000)
    assert choose([side, plan]) is side


def test_a_due_marathon_outranks_training_and_quality_hunts_but_not_new_entries():
    from pokesim.planning.arbiter import Tier
    from pokesim.policies import marathon
    from pokesim.policies.collection import HUNT_TIER, candidate
    race = {**marathon.candidate(), 'key': 'marathon'}
    assert candidate(race, 0, {}, False, set()).tier == Tier.RACE
    assert Tier.PROGRESS < Tier.RACE < Tier.UPGRADE < HUNT_TIER
    hunt = {'method': 'grass', 'key': 'hunt', 'species': sid(10), 'map': 51, 'repeat': True, 'dv_hunt': True,
            'catch_goal': 3}
    assert pick(race, train('train', 90), hunt, tails={sid(10): 10}) == 'marathon'
    entry = {'method': 'grass', 'key': 'entry', 'species': sid(10), 'map': 51}
    assert pick(race, entry, owned=frozenset()) == 'entry'


def test_repeat_batch_and_rotation_survive_checkpoint():
    c = Collection()
    c.project = {'species':sid(10), 'method':'grass', 'repeat':True, 'dv_hunt':True,
                 'initial_count':1, 'catch_goal':3, 'key':'caterpie'}
    c.last_hunt[str(sid(10))] = 123
    c.remaining = 108000
    s = postgame(party=(individual(100, 1),), stored_pokemon=((0,sid(10),3,'A'),))
    c.observe(s)
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    restored.observe(replace(s, frame=120, stored_pokemon=s.stored_pokemon * 2))
    assert restored.project is not None
    assert restored.project['gains']['catches'] == 1
    restored.observe(replace(s, frame=240, stored_pokemon=s.stored_pokemon * 4))
    assert restored.project is None
    assert restored.last_hunt == c.last_hunt
    assert restored.director.outcomes[-1]['gains']['catches'] == 3


def test_custom_names_distinguish_perfect_partners_in_one_family():
    partners = tuple(replace(individual(5, 1, 10), dvs=(15,) * 5, nick=nick) for nick in ('ALPHA', 'BETA'))
    s = postgame(party=partners)
    train = [p for _, p in candidates(s) if p['method'] == 'train']
    assert len(train) == 2
    assert {Collection.trainee(s, p) for p in train} == {0, 1}


def test_dv_hunts_accept_weak_incidental_duplicates_with_bounded_attempts():
    from pokesim.policies.battle import choose_battle
    c = Collection()
    c.project = {'species':sid(10), 'method':'grass', 'repeat':True, 'dv_hunt':True, 'map':51}
    me = replace(individual(100, 1), hp=200, max_hp=200, moves=(33,), pp=(35,))
    enemy = replace(individual(3, 2, 13), hp=10, max_hp=10, moves=(), pp=())
    s = postgame(party=(me,), in_battle=1)
    repeat = c.repeat_target(enemy.species, 51)
    assert repeat == sid(13)
    assert c.repeat_target(enemy.species, 194) == sid(10)
    assert choose_battle(s, me, enemy, 0, repeat_species=repeat).kind == 'item'
    assert choose_battle(s, me, enemy, 0, repeat_species=repeat, catch_attempts=5).kind != 'item'
    c.project = {'method':'train'}
    assert c.repeat_target(enemy.species) is None


def test_dv_hunts_only_catch_a_copy_that_beats_every_held_copy():
    from pokesim.policies.battle import W_ENEMY_MON, enemy_dvs
    c = Collection()
    c.project = {'species': sid(10), 'method': 'grass', 'repeat': True, 'dv_hunt': True, 'map': 51}
    held = replace(individual(5, 2, 13), dvs=(15, 1, 3, 5, 7))
    s = postgame(party=(individual(100, 1), held), in_battle=1)
    assert c.repeat_target(sid(13), 51, s, (0, 0, 0, 0, 0)) is None
    assert c.repeat_target(sid(13), 51, s, (15, 1, 3, 5, 7)) is None
    assert c.repeat_target(sid(13), 51, s, (15, 15, 15, 15, 15)) == sid(13)
    # A species with no copy held, or the hunt's own target, is judged the same way.
    assert c.repeat_target(sid(16), 51, s, (0, 0, 0, 0, 0)) == sid(16)
    s = postgame(party=(individual(100, 1), replace(held, species=sid(10))), in_battle=1)
    assert c.repeat_target(sid(10), 194, s, (0, 0, 0, 0, 0)) is None
    assert c.repeat_target(sid(10), 194, s, (15, 15, 15, 15, 15)) == sid(10)
    mem = bytearray(0x10000)
    mem[W_ENEMY_MON + 12:W_ENEMY_MON + 14] = b'\x13\x57'
    assert enemy_dvs(mem) == (15, 1, 3, 5, 7)


def test_isolated_league_side_opens_passage_before_another_local_hunt():
    from types import SimpleNamespace
    from pokesim.strategy_data import MAPS
    from pokesim.policies.progression import Goal
    c = Collection()
    c.completed_champion = True
    s = replace(postgame(party=(replace(individual(100, 1), moves=(70,)),)),
                map=MAPS['ROUTE_23'], x=18, y=27)
    nav = SimpleNamespace(distance_lookup=lambda *args: lambda targets: None, path=[])
    goal = c.choose(s, nav, random.Random(0), Goal('collect_plan', '', ''))
    assert goal.key == 'collect_passage'
    assert goal.targets == ((MAPS['ROUTE_23'], 8, 138),)
    assert c.project is None


def test_route22_gate_connects_both_sides_for_return_hunts():
    from pokesim.policies.navigation import Navigator
    from pokesim.strategy_data import MAPS, WORLD
    gate = MAPS['ROUTE_22_GATE']
    exits = [Navigator._warp(gate, warp) for warp in WORLD[gate]['warps']]
    assert exits == [(MAPS['ROUTE_22'], 8, 5), (MAPS['ROUTE_22'], 8, 5),
                     (MAPS['ROUTE_23'], 7, 139), (MAPS['ROUTE_23'], 8, 139)]


def test_postgame_restocks_before_ball_count_blocks_future_dv_hunts():
    from pokesim.policies.strategic import StrategicPolicy
    from pokesim.policies.progression import Goal
    from pokesim.strategy_data import ITEMS, MAPS
    from test_screen import fake_mem
    policy = StrategicPolicy(7)
    policy.completed['pokedex'] = True
    policy.collection.completed_champion = True
    policy.goal = Goal('collect_plan', '', '')
    policy.collection.pick = lambda *args: None
    policy.pickups.pick = lambda *args: None
    s = replace(postgame(party=(individual(100, 1),)),
                items=((ITEMS['GREAT_BALL'], 3), (ITEMS['POTION'], 3)))
    policy._overworld(s, fake_mem({}))
    assert policy.goal.key == 'restock'


def test_hunt_reaches_remote_puzzle_by_an_accessible_ladder():
    from unittest.mock import Mock
    from pokesim.policies.strategic import StrategicPolicy
    from pokesim.policies.progression import Goal
    from test_travel import trainer, prepare_navigation
    from test_screen import fake_mem
    p = StrategicPolicy(0)
    s = trainer(x=24, y=16)
    prepare_navigation(p, s)
    goal = Goal('collect_hunt', 'Find Caterpie', '', ((51, 17, 40),))
    p.collection.project = {'method':'grass', 'species':sid(10)}
    # The collection pick runs after the Champion falls, so the goal it is handed is the plan placeholder.
    p.goal = Goal('collect_plan', 'Plan', 'Plan')
    p.collection.pick = lambda *args: (goal, None, None)
    p.pickups.pick = lambda *args: None
    p.boulders.route = Mock(return_value=None)
    assert p._overworld(s, fake_mem({}))[0].button == 'right'
    assert p.nav._open_navigation.path[-1][2] == (198, 23, 7)
