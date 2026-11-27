"""One record per Gen I goal: its rules by kind, its params fixed once it starts, and the same keys,
categories and saves as before (docs/design/typed-goals.md, slice 1)."""
import copy
import json
import pickle

import pytest

from pokesim.planning.goals import GoalRun, ParamWrite
from pokesim.planning.monitor import SPENT, STAND_DOWNS, STOOD_DOWN, Backoff, Monitor
from pokesim.policies import kinds
from pokesim.policies.collection import Collection, legendary_project
from pokesim.policies.director import category
from test_collection import sid

METHODS = ('grass', 'surf', 'fish', 'safari', 'static', 'gift', 'trade', 'fossil', 'return_fossil', 'marathon',
           'rematch', 'trainer', 'explore', 'prize', 'rod', 'amber', 'evolve', 'train')

# One project of each kind, as the offers draw builds it, with a run field each kind writes.
PROJECTS = [
    {'method': 'grass', 'species': sid(16), 'map': 12, 'repeat': True, 'catch_goal': 3, 'key': 'pidgey',
     'gains': {'catches': 1}},
    {'method': 'surf', 'species': sid(72), 'map': 33, 'key': 'tentacool', 'closest_distance': 4},
    {'method': 'fish', 'species': sid(129), 'map': 0, 'rod': 'OLD_ROD', 'key': 'magikarp', 'progress_mark': 7},
    {'method': 'safari', 'species': sid(128), 'map': 220, 'key': 'tauros', 'support_trip': 'restock'},
    {'method': 'static', 'species': sid(144), 'map': 159, 'fragment': 'ARTICUNO', 'legendary': True,
     'key': 'legendary:articuno', 'initial_held': 0},
    {'method': 'gift', 'species': sid(133), 'map': 128, 'fragment': 'EEVEE_POKEBALL', 'key': 'eevee',
     'initial_held': 0},
    {'method': 'trade', 'species': sid(122), 'map': 30, 'fragment': None, 'give': sid(63), 'key': 'mr_mime',
     'parent': sid(63), 'box': 2, 'give_key': 'abra:7'},
    {'method': 'fossil', 'species': sid(138), 'map': 166, 'fragment': 'SCIENTIST2', 'item': 'HELIX_FOSSIL',
     'key': 'omanyte', 'supplies_prepared': True},
    {'method': 'return_fossil', 'map': 166, 'item': 'OLD_AMBER', 'key': 'amber_return'},
    {'method': 'marathon', 'route': 'cycling_road', 'key': 'marathon', 'checkpoint': 2, 'race_frames': 900,
     'healed_here': False},
    {'method': 'rematch', 'hof_count': 3, 'key': 'rematch', 'parent': sid(6), 'trainee_key': 'charizard:7',
     'trainee_nick': 'BLAZE', 'family': [sid(6)], 'scoped_partner': True, 'box': 1, 'league_rotation': True,
     'rotation_ready': False},
    {'method': 'trainer', 'map': 40, 'target': (40, 5, 6), 'key': 'trainer'},
    {'method': 'explore', 'map': 1, 'target': (1, 2, 3), 'key': 'explore'},
    {'method': 'prize', 'item': 'TM_23', 'key': 'prize'},
    {'method': 'rod', 'item': 'GOOD_ROD', 'map': 140, 'key': 'rod'},
    {'method': 'amber', 'map': 104, 'key': 'amber'},
    {'method': 'evolve', 'species': sid(26), 'parent': sid(25), 'evolution': {'method': 'item', 'requirement': 'THUNDER_STONE'},
     'key': 'raichu', 'initial_experience': 1000, 'box': None},
    {'method': 'train', 'parent': sid(113), 'family': [sid(113)], 'initial_level': 65, 'target_level': 70,
     'key': 'train:chansey:70', 'initial_experience': 10000,
     'training_session': {'preparation_frames': 0, 'active_frames': 120}},
]


def old_key(project):
    """The key builder the offers draw had before the kinds, kept here as the reference."""
    key = str(project.get('species', 0)) + ':' + project['method'] + ':' + str(project.get('map', 0)) + ':' + str(project.get('fragment', ''))
    if legendary_project(project):
        key = f'legendary:{project["species"]}:{project["map"]}'
    if project['method'] == 'evolve' and project.get('trainee_key'):
        key += ':' + project['trainee_key']
    if project['method'] == 'train':
        key = f'train:{project.get("trainee_key") or project["parent"]}:{project["target_level"]}'
        if project.get('scoped_partner'):
            key += ':' + str(project['parent']) + ':' + project.get('trainee_nick', '')
    return key


def old_category(project):
    """The category the director gave before the kinds, kept here as the reference."""
    if project.get('legendary'):
        return 'legendary'
    method = project['method']
    if method == 'marathon':
        return 'recreation'
    if method == 'evolve':
        return 'evolution'
    if method == 'train':
        return 'training'
    if method in ('trainer', 'explore'):
        return 'exploration'
    if method in ('rematch', 'rod'):
        return 'supplies'
    return 'collection'


def test_every_gen1_method_has_rules_and_any_other_takes_the_plain_kind():
    assert sorted(kinds.RULES) == sorted(METHODS)
    assert {project['method'] for project in PROJECTS} == set(METHODS)
    for method in METHODS:
        assert kinds.rules(method).kind == method
    assert kinds.rules('wild') is kinds.OTHER and kinds.rules(None) is kinds.OTHER


@pytest.mark.parametrize('project', PROJECTS, ids=lambda project: project['method'])
def test_a_goal_saves_and_loads_as_the_same_dict(project):
    c = Collection()
    c.project = project
    run = c.project
    assert isinstance(run, GoalRun) and run == project and run is not project
    assert run.rules is kinds.rules(project['method'])
    assert run.spec.kind == project['method'] and run.spec.key == project['key']
    assert not set(run.spec.params) & (run.rules.run | {'key', 'method'})
    saved = json.loads(json.dumps(c.state_dict()))
    assert saved['project'] == json.loads(json.dumps(project))
    restored = Collection()
    restored.load(saved)
    assert isinstance(restored.project, GoalRun) and restored.project == saved['project']
    assert restored.project.rules is run.rules
    assert restored.project.spec.kind == run.spec.kind and restored.project.spec.key == run.spec.key
    # A save turns a tuple into a list, as it did before the kinds.
    assert dict(restored.project.spec.params) == json.loads(json.dumps(dict(run.spec.params)))
    for twin in (copy.copy(run), copy.deepcopy(run), pickle.loads(pickle.dumps(run))):
        assert isinstance(twin, GoalRun) and twin == run and twin.rules is run.rules and twin.spec == run.spec


@pytest.mark.parametrize('project', PROJECTS, ids=lambda project: project['method'])
def test_a_started_goal_writes_its_run_fields_and_refuses_its_params(project):
    run = GoalRun.start(project, kinds.rules(project['method']))
    for name in run.rules.run:
        run[name] = run.get(name)
    run['gains'] = {'catches': 2}
    assert project.get('gains') != {'catches': 2}   # the run has its own copy of the offer
    with pytest.raises(ParamWrite):
        run['key'] = 'other'
    with pytest.raises(ParamWrite):
        run.update(method='grass')
    with pytest.raises(ParamWrite):
        run.setdefault('a_new_param', 1)
    with pytest.raises(ParamWrite):
        run.clear()
    assert run['key'] == project['key'] and 'a_new_param' not in run


@pytest.mark.parametrize('project', PROJECTS + [
    {'method': 'static', 'species': sid(143), 'map': 60, 'fragment': 'SNORLAX'},
    {'method': 'evolve', 'species': sid(26), 'parent': sid(25), 'trainee_key': 'pikachu:7'},
    {'method': 'train', 'parent': sid(113), 'target_level': 70, 'trainee_key': 'chansey:9'},
    {'method': 'train', 'parent': sid(113), 'target_level': 70, 'trainee_key': 'chansey:9',
     'scoped_partner': True, 'trainee_nick': 'MOCHI'},
    {'method': 'wild', 'species': sid(16)},
], ids=lambda project: project['method'])
def test_keys_and_categories_are_the_ones_the_old_switches_gave(project):
    assert kinds.rules(project['method']).key(project) == old_key(project)
    assert category(project) == old_category(project)


def test_only_marathon_and_training_keep_their_own_clock_and_only_hunts_bring_balls():
    assert {method for method in METHODS if kinds.rules(method).own_clock} == {'marathon', 'train'}
    assert {method for method in METHODS if kinds.rules(method).own_balls} == {'grass', 'surf', 'fish'}
    assert {method for method in METHODS if kinds.rules(method).wild} == {'grass', 'surf', 'fish', 'safari'}
    for method in ('marathon', 'train'):
        assert kinds.rules(method).budget({'method': method}) is None


def test_the_monitor_sets_spent_frames_and_reports_its_stand_downs():
    monitor = Monitor(backoff=Backoff(100, doublings=3))
    monitor.set_spent('hunt', 500)
    assert monitor.spent('hunt') == 500
    monitor.set_spent('hunt', 0)
    assert 'hunt' not in monitor.rows(SPENT)
    assert monitor.since('hunt') is None
    assert monitor.stand_down('hunt', 10) == 10 + 100
    assert monitor.since('hunt') == 10
    stood = monitor.stood_down()
    stood['hunt'] = 99
    assert monitor.since('hunt') == 10   # a copy, not the table
    # With ``most``, the count stops at its cap and the key moves to the newest end.
    monitor.stand_down('walk', 20)
    for now in (30, 40, 50, 60, 70):
        monitor.stand_down('hunt', now, most=4)
    assert monitor.rows(STAND_DOWNS) == {'walk': 1, 'hunt': 4}
    assert list(monitor.rows(STOOD_DOWN)) == ['hunt', 'walk']
    monitor.stand_down('hunt', 80, most=4)
    assert list(monitor.rows(STAND_DOWNS)) == ['walk', 'hunt']
    # A stand-down that ran out is forgotten, its count kept.
    monitor.expire(20 + 200)
    assert monitor.since('walk') is None and monitor.rows(STAND_DOWNS)['walk'] == 1
    assert monitor.since('hunt') == 80
    monitor.trim(1)
    assert list(monitor.rows(STAND_DOWNS)) == ['hunt']
