"""One record per Gen II goal: the hunt target, training and each postgame activity have their kind's
rules, keep their params once they start, and give the same keys, counters and saves as before
(docs/design/typed-goals.md, slice 2)."""
import copy
import json
import pickle
from types import SimpleNamespace

import pytest

from pokesim.gen2 import kinds, postgame, standdown
from pokesim.planning.goals import GoalRun, ParamWrite
from pokesim.policies import marathon as race
from pokesim.shiny import shiny_bytes

IDENTITY = [24680, [15, 12, 9, 14, 10]]
ROW = {'map': 'ROUTE_29', 'species': 16, 'method': 'grass', 'time': 'morn', 'chance': 30, 'started': 40}
TARGET = {**ROW, 'level': 3, 'expected': 900}
TRAINING = {'identity': IDENTITY, 'target': 17, 'item': None, 'species': 16, 'terminal': False}
TERMINAL = {'identity': IDENTITY, 'target': 16, 'item': None, 'species': 16, 'terminal': True, 'level_goal': 40,
            'postgame': True}
QUALITY = {'kind': 'quality', 'species': 16, 'row': ROW, 'started': 40, 'seen': [[1, [1, 2, 3, 4, 5]]], 'caught': 0,
           'expected': 900, 'tail': 0.5}
SHINY_ROW = {'map': 'ROUTE_30', 'method': 'grass', 'time': 'any', 'species': None, 'chance': 100, 'started': 40}
SHINY = {'kind': 'shiny', 'row': SHINY_ROW, 'started': 40, 'maps': 3, 'expected': 9000, 'encounters': 0,
         'in_battle': False, 'shinies': 0}
TRAIN = {'kind': 'train', 'identity': IDENTITY, 'species': 16, 'level_goal': 40}
MARATHON = {'kind': 'marathon', **race.candidate(), 'started_frame': 100, 'progress_frame': 100}
LEAGUE = {'kind': 'league'}
ACTIVITIES = [QUALITY, SHINY, TRAIN, MARATHON, LEAGUE]

# Each record with its rules, a field it writes once under way and a param it keeps.
RECORDS = [
    (kinds.HUNT, TARGET, 'expected', 'species'),
    (kinds.TRAINING, TRAINING, 'gained', 'species'),
    (kinds.TERMINAL, TERMINAL, 'species', 'identity'),
    (kinds.activity(QUALITY), QUALITY, 'better', 'species'),
    (kinds.activity(SHINY), SHINY, 'asked', 'shinies'),
    (kinds.activity(TRAIN), TRAIN, 'suspended', 'level_goal'),
    (kinds.activity(MARATHON), MARATHON, 'healed_here', 'started_frame'),
    (kinds.activity(LEAGUE), LEAGUE, 'suspended', 'kind'),
]


def collection_of(target=None, training=None, activity=None):
    state = {'target': target, 'training': training}
    if activity is not None:
        state['postgame'] = {'activity': activity, 'searches': {}, 'shiny_maps': [], 'finished': 0}
    return state


def test_every_activity_and_training_has_its_rules():
    for record in ACTIVITIES:
        assert kinds.activity(record).kind == f'postgame.{record["kind"]}'
    assert kinds.activity({'kind': 'older'}) is kinds.OTHER
    assert kinds.training(TRAINING) is kinds.TRAINING
    assert kinds.training(TERMINAL) is kinds.TERMINAL


@pytest.mark.parametrize('rules, record', [(rules, record) for rules, record, _, _ in RECORDS])
def test_a_goal_saves_and_loads_as_the_same_dict(rules, record):
    run = kinds.start(rules, record)
    assert isinstance(run, GoalRun) and run == record and run is not record
    assert kinds.start(rules, run) is run
    saved = json.loads(json.dumps(run))
    loaded = kinds.start(rules, saved)
    assert loaded == json.loads(json.dumps(record))
    assert (loaded.spec.kind, loaded.spec.key) == (run.spec.kind, run.spec.key)
    assert dict(loaded.spec.params) == json.loads(json.dumps(dict(run.spec.params)))


def test_the_hunt_target_keeps_its_encounter_method_as_a_param():
    run = kinds.target(TARGET)
    assert (run.spec.kind, run.spec.key) == ('hunt', 'hunt:16')
    assert run.spec.params['method'] == 'grass'
    assert 'expected' not in run.spec.params
    with pytest.raises(ParamWrite):
        run['method'] = 'surf'


def test_keys_name_the_goal_as_progress_events_did():
    assert kinds.project(TRAINING).spec.key == standdown.train_key(IDENTITY)
    assert kinds.start(kinds.activity(MARATHON), MARATHON).spec.key == 'marathon'
    assert kinds.start(kinds.activity(QUALITY), QUALITY).spec.key == 'quality'


@pytest.mark.parametrize('rules, record, field, param', RECORDS)
def test_run_fields_write_and_params_refuse(rules, record, field, param):
    run = kinds.start(rules, copy.deepcopy(record))
    run[field] = run.get(field)
    with pytest.raises(ParamWrite):
        run[param] = run.get(param)
    with pytest.raises(ParamWrite):
        run.pop(param)


def test_run_fields_cover_every_write_the_goal_makes():
    quality = kinds.start(kinds.activity(QUALITY), copy.deepcopy(QUALITY))
    quality['caught'] += 1
    quality['counted'] = 1
    quality['suspended'] = False
    del quality['tail']
    assert quality.setdefault('tail', 0.25) == 0.25
    shiny = kinds.start(kinds.activity(SHINY), copy.deepcopy(SHINY))
    shiny['encounters'] = shiny.get('encounters', 0) + 1
    shiny['in_battle'] = True
    shiny['counted'] = 1
    marathon = kinds.start(kinds.activity(MARATHON), copy.deepcopy(MARATHON))
    marathon['checkpoint'] += 1
    marathon['race_frames'] += 60
    marathon['progress_frame'] = 160
    marathon.pop('healed_here', None)
    training = kinds.project(copy.deepcopy(TRAINING))
    training['site'] = 'ROUTE_29'
    training.setdefault('refused', []).append(3)
    training['experience'] = 500
    with pytest.raises(ParamWrite):
        training['target'] = 18


def test_copies_and_pickles_keep_the_shared_rules():
    for rules, record, _, _ in RECORDS:
        run = kinds.start(rules, record)
        for twin in (copy.copy(run), copy.deepcopy(run), pickle.loads(pickle.dumps(run))):
            assert twin.rules is rules and twin == run and twin.spec == run.spec
            with pytest.raises(ParamWrite):
                twin['nonsense'] = 1


def test_goal_key_and_counters_follow_the_goal_in_progress():
    def policy(**slots):
        return SimpleNamespace(collection=collection_of(**slots))

    target, training = kinds.target(TARGET), kinds.project(TRAINING)
    assert standdown.goal_key(SimpleNamespace(collection=None)) == (None, '')
    assert standdown.goal_key(policy()) == (None, '')
    assert standdown.goal_key(policy(training=training)) == (standdown.train_key(IDENTITY), '')
    assert standdown.goal_key(policy(target=target, training=training)) == ('hunt:16', '')
    assert standdown.goal_key(policy(target=target, activity=SHINY)) == ('shiny', '')
    assert standdown.goal_key(policy(activity=MARATHON)) == ('marathon', 'RACE')
    assert standdown.goal_key(policy(activity=TRAIN)) == ('train', '')

    assert standdown.hunt(policy(), None) is None
    assert standdown.hunt(policy(training=training), None) is None
    assert standdown.hunt(policy(target=target), None) == (16, None)
    assert standdown.hunt(policy(target=target, activity=SHINY), None) == (None, shiny_bytes)
    species, rule = standdown.hunt(policy(activity=QUALITY), None)
    assert species == 16 and callable(rule)
    for record in (TRAIN, MARATHON, LEAGUE):
        assert standdown.hunt(policy(target=target, activity=record), None) is None


def test_search_rows_and_stall_keys_come_from_the_searches_alone():
    def policy(activity):
        return SimpleNamespace(collection=collection_of(activity=kinds.start(kinds.activity(activity), activity)))

    assert postgame.searching(policy(QUALITY)) == ROW
    assert postgame.searching(policy(SHINY)) == SHINY_ROW
    assert postgame.stall_key(policy(QUALITY)) == 'hunt:16'
    assert postgame.stall_key(policy(SHINY)) == 'shiny:ROUTE_30'
    for record in (TRAIN, MARATHON, LEAGUE):
        assert postgame.searching(policy(record)) is None
        assert postgame.stall_key(policy(record)) is None
    assert postgame.searching(SimpleNamespace(collection={})) is None
    assert postgame.stall_key(SimpleNamespace(collection={})) is None


def test_a_loaded_save_holds_goals_and_gains_no_fields():
    state = json.loads(json.dumps({**collection_of(TARGET, TERMINAL, QUALITY),
                                   'tower': {'previous_training': TRAINING}}))
    before = json.dumps(state, sort_keys=True)
    kinds.adopt(state)
    assert json.dumps(state, sort_keys=True) == before
    assert state['target'].rules is kinds.HUNT
    assert state['training'].rules is kinds.TERMINAL
    assert state['postgame']['activity'].rules is kinds.activity(QUALITY)
    assert state['tower']['previous_training'].rules is kinds.TRAINING
    bare = {'postgame': {'activity': None}}
    kinds.adopt(bare)
    assert bare == {'postgame': {'activity': None}}


def test_the_running_goal_is_the_activity_then_the_target_then_training():
    target, training = kinds.target(TARGET), kinds.project(TRAINING)
    assert kinds.running(collection_of()) == (None, None)
    assert kinds.running(collection_of(training=training)) == (kinds.TRAINING, training)
    assert kinds.running(collection_of(target, training)) == (kinds.HUNT, target)
    rules, record = kinds.running(collection_of(target, training, MARATHON))
    assert rules is kinds.activity(MARATHON) and record is MARATHON
