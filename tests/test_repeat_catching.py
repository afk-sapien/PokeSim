from dataclasses import replace
import random
from types import SimpleNamespace

import pytest

from pokesim.policies.collection import Collection, held_count
from pokesim.policies.battle import choose_battle
from pokesim.policies.progression import Goal
from pokesim.runtime.participant import Participant
from test_collection import state, sid
from test_strategy import mon
from pokesim.strategy_data import ITEMS, MAPS


def test_known_species_remain_eligible_and_needs_have_more_weight():
    c = Collection()
    target = sid(69)
    s = state(owned=frozenset({1, 69}), stored_pokemon=((0, target, 5, ''),))
    routine = c.capture_weight(s, target)
    assert routine > 0
    assert c.capture_weight(replace(s, stored_pokemon=()), target) > routine
    assert c.capture_weight(replace(s, owned=frozenset({1})), target) > routine
    c.set_demand({69: 2})
    assert c.capture_weight(s, target) > routine
    c.set_demand({})
    crowded = replace(s, stored_pokemon=((0, target, 5, ''),) * 20)
    assert 0 < c.capture_weight(crowded, target) < routine


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


def test_recent_repeat_catches_are_deprioritized_temporarily():
    c = Collection()
    target = sid(69)
    s = state(owned=frozenset({1, 69}), stored_pokemon=((0, target, 5, ''),))
    initial = c.capture_weight(s, target)
    c.last_repeat[str(target)] = c.elapsed
    assert 0 < c.capture_weight(s, target) < initial
    c.elapsed += 216000
    assert c.capture_weight(s, target) == initial


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
    def select(candidates, rng, urgent=False):
        captured.extend(candidates)
        return next(project for weight, project in candidates if project.get('repeat'))
    monkeypatch.setattr(c.director, 'select', select)
    nav = SimpleNamespace(distance_lookup=lambda *args: lambda points: 10, can_surf=True, visits={}, path=[])
    s = state(map=MAPS['ROUTE_1'], owned=frozenset(range(1, 152)), money=50000)
    c.choose(s, nav, random.Random(1), Goal('collect_plan', '', ''))
    assert c.project['species'] == target and c.project['repeat']
    assert c.project['initial_count'] == 0
    assert any(weight > 0 and project.get('repeat') for weight, project in captured)


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
    def select(candidates, rng, urgent=False):
        captured.extend(candidates)
        return next(project for weight, project in candidates if project.get('needed_capture'))
    monkeypatch.setattr(c.director, 'select', select)
    nav = SimpleNamespace(distance_lookup=lambda *args: lambda points: 10, can_surf=True, visits={}, path=[])
    c.choose(state(map=MAPS['ROUTE_1'], owned=frozenset(range(1, 152)), money=50000),
             nav, random.Random(1), Goal('collect_plan', '', ''))
    assert c.project['species'] == sid(69)
    assert not any(p.get('species') == sid(16) and p.get('repeat') for w, p in captured)


def test_demand_keeps_needed_copies_without_blocking_all_duplicate_cleanup():
    from pokesim.policies.strategic import StrategicPolicy
    from test_duplicates import snapshot, stored
    policy = StrategicPolicy(1)
    copies = [stored(i, species=sid(69), level=10 + i) for i in range(3)]
    policy.collection.set_demand({69: 3})
    assert policy._release_target(snapshot(copies)) is None
    policy.collection.set_demand({69: 2})
    assert policy._release_target(snapshot(copies)) == (0, 0)


@pytest.mark.parametrize('requests', [{'0': 1}, {'152': 1}, {'69': -1}, {'69': True}, []])
def test_invalid_peer_demand_is_rejected(requests):
    participant = object.__new__(Participant)
    participant.emu = SimpleNamespace(policy=SimpleNamespace(collection=Collection()))
    with pytest.raises(ValueError):
        participant.collection_demand({'requests': requests})
