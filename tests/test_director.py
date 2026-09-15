import json
import random
from dataclasses import replace
from unittest.mock import Mock

from pokesim.policies.collection import Collection, training_targets
from pokesim.policies.director import AdventureDirector
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.strategy_data import ITEMS, MAPS, WORLD
from test_collection import sid, state
from test_strategy import mon


def test_restarts_preserve_category_rotation_and_repeated_failure_backoff():
    director = AdventureDirector()
    catch = {'method': 'grass', 'species': sid(16), 'key': 'pidgey'}
    train = {'method': 'train', 'parent': sid(113), 'key': 'chansey'}
    director.select([(1, catch)], random.Random(1))
    director.select([(1, catch)], random.Random(1))
    first_retry = director.finish(catch, 0, False, 'No encounter')
    restored = AdventureDirector()
    restored.load(json.loads(json.dumps(director.state_dict())))
    assert restored.select([(1000, catch), (1, train)], random.Random(1)) == train
    second_retry = restored.finish(catch, first_retry, False, 'No encounter')
    assert second_retry - first_retry == 120000
    assert restored.outcomes[-1]['reason'] == 'No encounter'
    restored.finish(catch, second_retry, True, 'Caught Pidgey')
    assert 'pidgey' not in restored.failures
    assert restored.completed == {'collection': 1}


def test_productive_training_hard_limit_is_advanced_and_does_not_escalate_failure():
    c = Collection()
    c.completed_champion = True
    c.project = {'method': 'train', 'parent': sid(113), 'family': [sid(113)],
                 'initial_level': 65, 'target_level': 70, 'key': 'train:chansey:70'}
    c.remaining = 120
    c.observe(state(frame=0, party=(mon(species=sid(113), level=65, experience=10000),)))
    c.project['training_session']['active_frames'] = 360000 - 120
    c.observe(state(frame=120, party=(mon(species=sid(113), level=65, experience=10500),)))
    assert c.project is None
    assert c.director.outcomes[-1]['status'] == 'advanced'
    assert c.director.outcomes[-1]['gains']['experience'] == 500
    assert not c.director.failures
    assert not c.director.completed


def test_training_target_and_gains_survive_a_checkpoint_until_the_actual_level():
    c = Collection()
    c.completed_champion = True
    c.project = {'method': 'train', 'parent': sid(113), 'family': [sid(113)],
                 'initial_level': 69, 'target_level': 70, 'key': 'train:chansey:70'}
    c.remaining = 72000
    start = state(party=(mon(species=sid(113), level=69, experience=10000),), owned=frozenset({113}))
    c.observe(start)
    assert c.project is not None
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    restored.observe(replace(start, frame=200, party=(replace(start.party[0], level=70, experience=11000),)))
    assert restored.project is None
    outcome = restored.director.outcomes[-1]
    assert outcome['status'] == 'completed'
    assert outcome['target'] == 70
    assert outcome['gains'] == {'experience': 1000, 'levels': 1}


def test_productive_training_still_stops_when_idle_and_preserves_partial_progress():
    c = Collection()
    c.project = {'method': 'train', 'parent': sid(113), 'family': [sid(113)],
                 'initial_level': 65, 'target_level': 70, 'key': 'train:chansey:70'}
    c.remaining = 72000
    c.director.failures[c.project['key']] = 3
    start = state(party=(mon(species=sid(113), level=65, experience=10000),))
    c.observe(start)
    gained = replace(start, frame=120, party=(replace(start.party[0], experience=10524),))
    c.observe(gained)
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    restored.observe(gained)
    for frame in range(240, 7441, 120):
        restored.observe(replace(gained, frame=frame))
    assert restored.project is None
    outcome = restored.director.outcomes[-1]
    assert outcome['status'] == 'advanced'
    assert outcome['gains'] == {'experience': 524, 'levels': 0}
    assert 'No trainee experience gain' in outcome['reason']
    assert outcome['retry_at'] - outcome['elapsed'] == 60000
    assert not restored.director.failures
    assert not restored.director.completed


def test_other_party_experience_and_supply_changes_cannot_hide_failed_training():
    c = Collection()
    c.project = {'method': 'train', 'parent': sid(113), 'family': [sid(113)],
                 'initial_level': 65, 'target_level': 70, 'key': 'train:chansey:70'}
    c.remaining = 72000
    for frame in range(0, 7800, 120):
        c.observe(state(frame=frame, x=frame % 20,
                        items=((ITEMS['POKE_BALL'], 10 + frame % 240),),
                        party=(mon(species=sid(113), level=65, experience=10000),
                               mon(species=sid(3), level=100, experience=frame))))
    assert c.project is None
    assert c.director.outcomes[-1]['status'] == 'deferred'


def test_full_dex_still_selects_training_and_level_100_has_no_training_candidate():
    c = Collection()
    nav = Navigator()
    nav.visits = {(m, 0, 0): 1 for m in WORLD}
    nav.distance_lookup = Mock(return_value=lambda targets: 0 if targets else None)
    s = state(map=MAPS['ROUTE_1'], money=100000, hall_of_fame_count=1,
              owned=frozenset(range(1, 152)), party=(mon(species=sid(113), level=99),),
              items=tuple((ITEMS[item], 10) for item in ('POKE_BALL', 'OLD_ROD', 'GOOD_ROD', 'SUPER_ROD')))
    c.observe(s)
    goal = c.choose(s, nav, random.Random(1), Goal('collect_plan', 'Plan', 'Plan'))
    assert goal.key == 'collect_train'
    assert c.project['target_level'] == 100
    assert goal.targets
    c = Collection()
    s = replace(s, party=(replace(s.party[0], level=100),))
    c.observe(s)
    assert c.choose(s, nav, random.Random(1), Goal('collect_plan', 'Plan', 'Plan')).key == 'collect_rematch'
    assert c.project['method'] != 'train'


def test_high_level_training_has_encounters_and_boxed_partner_uses_existing_pc_flow():
    assert training_targets('red', 99)
    c = Collection()
    c.project = {'method': 'train', 'parent': sid(113), 'family': [sid(113)],
                 'box': 2, 'initial_level': 65, 'target_level': 70, 'key': 'train:chansey:70'}
    s = state(stored_pokemon=((2, sid(113), 65, 'MOCHI'),))
    assert c.goal(s).key == 'party_collection'
    assert c.goal(replace(s, party=s.party + (mon(species=sid(113), level=65),))).key == 'collect_train'


def test_director_records_are_bounded_and_snapshots_do_not_alias_live_state():
    director = AdventureDirector()
    for index in range(200):
        director.finish({'method': 'explore', 'key': str(index)}, index, False, 'Unreachable')
    assert len(director.failures) == 128
    assert len(director.outcomes) == 24
    saved = director.state_dict()
    saved['outcomes'].clear()
    assert len(director.outcomes) == 24
