import json
import random
from collections import Counter
from dataclasses import asdict, replace
from unittest.mock import Mock

from pokesim.policies.battle import choose_battle
from pokesim.policies.collection import Collection
from pokesim.policies.director import AdventureDirector
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.policies.team import reserve_to_deposit
from pokesim.ram import StoredMon
from pokesim.strategy_data import ITEMS, MAPS, WORLD
from pokesim.trade.preferences import identity
from test_collection import sid, state
from test_strategy import mon


def individual(level, trainer, species=113):
    return mon(species=sid(species), level=level, trainer_id=trainer, dvs=(15, 1, 3, 5, 7))


def candidates(snapshot):
    c = Collection()
    nav = Navigator()
    nav.visits = {(m, 0, 0): 1 for m in WORLD}
    nav.distance_lookup = Mock(return_value=lambda targets: 10 if targets else None)
    c.observe(snapshot)
    c.director.select = Mock(wraps=c.director.select)
    c.choose(snapshot, nav, random.Random(4), Goal('collect_plan', 'Plan', 'Plan'))
    return c.director.select.call_args.args[0]


def postgame(**changes):
    return state(map=MAPS['ROUTE_1'], money=100000, hall_of_fame_count=1,
                 owned=frozenset(range(1, 152)),
                 items=tuple((ITEMS[item], 10) for item in ('POKE_BALL', 'OLD_ROD', 'GOOD_ROD', 'SUPER_ROD')),
                 **changes)


def test_duplicates_train_individually_toward_100_and_completed_partners_are_excluded():
    rows = candidates(postgame(party=(individual(100, 1), individual(95, 2), individual(60, 3))))
    projects = [p for _, p in rows if p['method'] == 'train']
    assert len(projects) == 2
    assert {p['initial_level'] for p in projects} == {60, 95}
    assert all(p['target_level'] == 100 for p in projects)
    assert len({p['key'] for p in projects}) == 2


def test_training_identity_survives_evolution_and_does_not_match_another_copy():
    target = individual(92, 1, 1)
    c = Collection()
    c.project = {'method': 'train', 'parent': target.species, 'family': [target.species],
                 'trainee_key': identity(asdict(target)), 'target_level': 100, 'initial_level': 92}
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    evolved = replace(target, species=sid(3), nick='EVOLVED')
    snapshot = postgame(party=(individual(100, 2, 3), evolved))
    assert restored.trainee(snapshot, restored.project) == 1
    assert restored.goal(snapshot).title == 'Train EVOLVED to level 100'


def test_exact_boxed_duplicate_is_withdrawn_and_not_its_level100_peer():
    target = individual(92, 1)
    key = identity(asdict(target))
    boxed = StoredMon(4, 1, target.species, 92, 'TARGET', (), 0, target.dvs, (0,) * 5, 1)
    other = replace(boxed, position=0, level=100, nick='OTHER', trainer_id=2)
    snapshot = postgame(party=(individual(100, 3),), active_box=4,
                        stored_details=(other, boxed),
                        stored_pokemon=((4, target.species, 100, 'OTHER'), (4, target.species, 92, 'TARGET')),
                        boxed_pokemon=((target.species, 100), (target.species, 92)))
    policy = StrategicPolicy(1)
    policy.collection.project = {'method': 'train', 'parent': target.species, 'trainee_key': key, 'box': 4, 'target_level': 100}
    policy.goal = policy.collection.goal(snapshot)
    policy.pc_operation = 'withdraw'
    assert policy.goal.key == 'party_collection'
    assert policy._pc_target(snapshot) == 1
    assert policy.collection.goal(replace(snapshot, stored_pokemon=(), stored_details=())) is None


def test_ambiguous_individuals_are_not_selected_for_training():
    target = individual(92, 1)
    rows = candidates(postgame(party=(target, replace(target))))
    assert not any(p['method'] == 'train' for _, p in rows)


def test_director_prioritizes_training_but_keeps_other_activities():
    d = AdventureDirector()
    rng = random.Random(19)
    rows = [(1, {'method': 'train', 'key': 'near100', 'initial_level': 95}),
            (10000, {'method': 'train', 'key': 'low', 'initial_level': 10}),
            (1, {'method': 'grass', 'key': 'repeat', 'repeat': True}),
            (1, {'method': 'rematch', 'key': 'money'})]
    selected = Counter(d.select(rows, rng)['key'] for _ in range(500))
    assert selected['near100'] > 300
    assert selected['low'] == 0
    assert selected['repeat'] > 0 and selected['money'] > 0
    assert d.select(rows, rng, urgent=True)['key'] == 'money'


def test_completed_reserve_yields_party_space_while_field_move_carrier_stays():
    snapshot = postgame(party=(individual(100, 1), individual(100, 2), individual(70, 3),
                              replace(individual(100, 4), moves=(57,), pp=(15,))))
    assert reserve_to_deposit(snapshot, prefer_completed=True) == 1
    assert reserve_to_deposit(snapshot) == 2


def test_safe_trainee_keeps_experience_instead_of_an_unneeded_level100_switch():
    trainee = individual(90, 1)
    trainee = replace(trainee, hp=200, max_hp=200, defense=200, attack=100, special=100, moves=(33,), pp=(35,))
    veteran = replace(trainee, level=100, attack=400, special=400, trainer_id=2)
    enemy = replace(trainee, level=20, species=sid(16), hp=500, max_hp=500, attack=20, defense=100)
    snapshot = postgame(party=(trainee, veteran), in_battle=1)
    assert choose_battle(snapshot, trainee, enemy, 0).kind == 'switch'
    assert choose_battle(snapshot, trainee, enemy, 0, training_index=0).kind == 'fight'
    unsafe = replace(trainee, hp=1)
    assert choose_battle(replace(snapshot, party=(unsafe, veteran)), unsafe, enemy, 0, training_index=0).kind == 'switch'
