import json
import random
from dataclasses import replace
from unittest.mock import Mock

from pokesim.policies import training
from pokesim.policies.collection import Collection
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.strategy_data import ITEMS, MAPS, WORLD
from test_collection import sid, state
from test_strategy import mon


def collection():
    c = Collection()
    c.project = {'method': 'train', 'parent': sid(113), 'family': [sid(113)],
                 'initial_level': 65, 'target_level': 70, 'key': 'train:chansey:70'}
    c.remaining = training.TRAINING_BUDGET
    return c


def test_preparation_and_healing_do_not_spend_training_time():
    c = collection()
    s = state(party=(mon(species=sid(113), level=65, experience=10000),))
    for frame in range(0, 8401, 120):
        c.observe(replace(s, frame=frame), training_active=False)
    assert c.project and c.remaining == training.TRAINING_BUDGET
    assert c.details()['training']['preparation_seconds'] == 140
    c.observe(replace(s, frame=8520), training_active=True)
    assert c.remaining == training.TRAINING_BUDGET - 120
    c.observe(replace(s, frame=8640), training_active=False)
    assert c.remaining == training.TRAINING_BUDGET - 120
    assert c.details()['training']['phase'] == 'preparation'


def test_only_new_trainee_experience_extends_a_productive_session():
    c = collection()
    s = state(party=(mon(species=sid(113), level=65, experience=10000),))
    c.observe(s)
    c.remaining = 120
    gained = replace(s, frame=120, party=(replace(s.party[0], experience=10500),))
    c.observe(gained)
    assert c.project and c.remaining == training.TRAINING_EXTENSION
    c.observe(replace(gained, frame=240))
    assert c.remaining == training.TRAINING_EXTENSION - 120
    assert not c.director.outcomes


def test_prep_movement_and_new_maps_cannot_extend_a_failed_project_forever():
    c = collection()
    s = state()
    for frame in range(0, training.PREPARATION_IDLE + 121, 120):
        c.observe(replace(s, frame=frame, x=frame % 20,
                          map=MAPS['ROUTE_1'] if frame % 240 else MAPS['ROUTE_2']), training_active=False)
    assert c.project is None
    assert c.director.outcomes[-1]['reason'] == 'No training preparation progress in five game minutes'


def test_route_progress_is_strict_and_cannot_refill_total_preparation_budget():
    c = collection()
    s = state()
    endpoint = (MAPS['ROUTE_1'], 10, 10)
    for frame in range(0, training.PREPARATION_BUDGET + 121, 120):
        c.observe(replace(s, frame=frame), training_active=False)
        if c.project:
            training.route_progress(c.project, 'collect_train', endpoint, 1000 - frame // 120)
    assert c.project is None
    outcome = c.director.outcomes[-1]
    assert outcome['reason'] == 'Training preparation budget reached'
    assert outcome['timing']['active_frames'] == 0
    assert outcome['timing']['preparation_frames'] == training.PREPARATION_BUDGET


def test_repeated_routes_and_restore_do_not_reset_idle_or_spent_budgets():
    c = collection()
    s = state()
    c.observe(s, training_active=False)
    training.route_progress(c.project, 'party_collection', (1, 2, 3), 10)
    c.observe(replace(s, frame=120), training_active=False)
    training.route_progress(c.project, 'party_collection', (1, 2, 3), 9)
    c.observe(replace(s, frame=240), training_active=False)
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    before = dict(restored.project['training_session'])
    training.route_progress(restored.project, 'party_collection', (1, 2, 3), 10)
    training.route_progress(restored.project, 'party_collection', (1, 2, 3), 9)
    assert restored.project['training_session'] == before
    assert restored.remaining == c.remaining


def test_suspended_pickups_are_bounded_preparation_without_using_training_budget():
    c = collection()
    s = state()
    for frame in range(0, training.PREPARATION_IDLE + 121, 120):
        c.observe(replace(s, frame=frame), suspended=True)
    assert c.project is None
    assert c.director.outcomes[-1]['timing']['active_frames'] == 0


def test_legacy_projects_get_one_migration_and_counters_survive_later_restores():
    c = collection()
    c.remaining = 50
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    assert restored.remaining == training.TRAINING_BUDGET
    restored.remaining = 1000
    again = Collection()
    again.load(json.loads(json.dumps(restored.state_dict())))
    assert again.remaining == 1000


def test_ready_nearby_partners_have_more_weight_than_distant_boxed_partners():
    c = Collection()
    nav = Navigator()
    nav.visits = {(m, 0, 0): 1 for m in WORLD}
    nav.distance_lookup = Mock(return_value=lambda targets: 20 if targets else None)
    s = state(map=MAPS['ROUTE_1'], money=100000, hall_of_fame_count=1,
              owned=frozenset(range(1, 152)), party=(mon(species=sid(113), level=65),),
              stored_pokemon=((2, sid(115), 65, 'RESERVE'),),
              items=tuple((ITEMS[item], 10) for item in ('POKE_BALL', 'OLD_ROD', 'GOOD_ROD', 'SUPER_ROD')))
    captured = []
    def select(candidates, rng, urgent=False):
        captured.extend(candidates)
        return next(p for w, p in candidates if p['method'] == 'train')
    c.director.select = select
    c.observe(s)
    c.choose(s, nav, random.Random(1), Goal('collect_plan', 'Plan', 'Plan'))
    rows = [(w, p) for w, p in captured if p['method'] == 'train']
    weights = {p['parent']: w for w, p in rows}
    assert weights[sid(113)] > weights[sid(115)]
    assert c.remaining == training.TRAINING_BUDGET


def test_productive_sessions_can_heal_repeatedly_without_spending_training_budget():
    c = collection()
    s = state(party=(mon(species=sid(113), level=65, experience=10000),))
    c.observe(s)
    frame = 0
    for episode in range(4):
        for _ in range(100):
            frame += 120
            c.observe(replace(s, frame=frame), training_active=False)
        frame += 120
        s = replace(s, party=(replace(s.party[0], experience=10500 + episode * 500),))
        c.observe(replace(s, frame=frame), training_active=True)
        assert c.project
    clock = c.project['training_session']
    assert clock['preparation_frames'] == 48000
    assert clock['preparation_since_gain'] == 0
    assert c.remaining == training.TRAINING_BUDGET - 480
    assert c.project['gains']['experience'] == 2000
    c.observe(replace(s, frame=frame + 120), training_active=False)
    c.observe(replace(s, frame=frame + 240), training_active=True)
    assert clock['preparation_since_gain'] == 120


def test_real_gains_cannot_extend_the_hard_combined_project_limit():
    c = collection()
    s = state(party=(mon(species=sid(113), level=65, experience=10000),))
    c.observe(s)
    clock = c.project['training_session']
    clock['active_frames'] = 100000
    clock['preparation_frames'] = training.PROJECT_LIMIT - 100000 - 120
    c.observe(replace(s, frame=120, party=(replace(s.party[0], experience=10500),)))
    assert c.project is None
    assert c.director.outcomes[-1]['reason'] == 'Training project time limit reached'
    assert c.director.outcomes[-1]['status'] == 'advanced'
