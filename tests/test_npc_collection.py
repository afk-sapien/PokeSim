"""NPC exchanges retrieve the chosen reserve without spending protected partners."""
from dataclasses import asdict, replace
from unittest.mock import Mock
import random

import pytest

from pokesim.policies.collection import Collection
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.ram import StoredMon
from pokesim.screen import Screen
from pokesim.trade.preferences import identity
from test_collection import sid, state
from test_strategy import flags, menu, mon


def stored(species, position=0, level=20, trainer=7):
    return StoredMon(2, position, sid(species), level, 'RESERVE', (33,), 1000,
                     (1, 2, 3, 4, 5), (0, 0, 0, 0, 0), trainer)


def with_storage(s, *entries):
    return replace(s, stored_details=entries,
                   stored_pokemon=tuple((p.box, p.species, p.level, p.nick) for p in entries))


def trade(c, target):
    return dict(next(r for r in c.sources()[sid(target)] if r['method'] == 'trade'), species=sid(target))


@pytest.mark.parametrize('target,give', [(122, 63), (124, 61)])
def test_npc_project_retrieves_selected_boxed_partner_then_visits_npc(target, give):
    p = StrategicPolicy(1)
    reserve = stored(give)
    s = with_storage(state(), reserve)
    p.collection.project = trade(p.collection, target)
    goal = p.collection.goal(s)
    assert goal.key == 'party_collection'
    assert p.collection.project['box'] == 2
    assert p.collection.project['give_key'] == identity(asdict(reserve))
    p.goal = goal
    p.pc_operation = 'withdraw'
    assert p._pc_target(replace(s, active_box=2, boxed_pokemon=((reserve.species, reserve.level),))) == 0
    partner = mon(species=reserve.species, level=reserve.level, dvs=reserve.dvs,
                  trainer_id=reserve.trainer_id)
    s = replace(s, map=p.collection.project['map'], party=s.party + (partner,),
                stored_details=(), stored_pokemon=())
    assert p.collection.goal(s).key == 'collect_trade'
    p.goal = p.collection.goal(s)
    mem = menu({2: '  FIGHTER', 4: '  RESERVE'}, (0, 4), index=1)
    assert p._dispatch(s, Screen(mem), 'party', mem)[0].button == 'a'
    assert p.pending_trade_key == identity(asdict(reserve))
    p.collection.remaining = 100
    p.collection.project['key'] = 'npc'
    p.collection.observe(replace(s, owned=s.owned | {target}))
    assert p.collection.project is None


@pytest.mark.parametrize('target,give', [(122, 63), (124, 61)])
def test_planner_includes_trade_from_a_boxed_reserve(target, give):
    c = Collection()
    c.completed_champion = True
    c.sources = lambda: {sid(target): [trade(Collection(), target)]}
    c.director.select = lambda candidates, rng, urgent: next(p for _, p in candidates if p['method'] == 'trade')
    nav = Navigator()
    nav.distance_lookup = Mock(return_value=lambda targets: 10)
    s = with_storage(state(), stored(give))
    assert c.choose(s, nav, random.Random(0), Goal('collect_plan', 'Plan', 'Plan')).key == 'party_collection'
    assert c.project['give'] == sid(give)


@pytest.mark.parametrize('preference', ['locked', 'offered'])
def test_npc_trade_respects_protected_partners_before_and_after_withdrawal(preference):
    p = StrategicPolicy(1)
    reserve = stored(63)
    key = identity(asdict(reserve))
    p.trade_preferences = lambda: {key: {'state': preference}}
    project = trade(p.collection, 122)
    assert p.collection.trade_candidate(with_storage(state(), reserve), project) is None
    offered = mon(species=reserve.species, level=20, dvs=reserve.dvs, trainer_id=reserve.trainer_id)
    assert p.collection.trade_candidate(state(party=(mon(level=50), offered)), project) is None
    p.collection.project = project
    p.goal = Goal('collect_trade', 'Trade', 'Trade')
    p.pending_trade_key = key
    mem = menu({2: '  YES', 4: '  NO'}, (0, 2))
    assert p._dispatch(state(), Screen(mem), 'yes_no', mem)[0].button == 'down'


def test_npc_trade_does_not_substitute_a_different_individual_or_ambiguous_identity():
    c = Collection()
    first, second = stored(63), stored(63, 1, trainer=8)
    project = dict(trade(c, 122), give_key=identity(asdict(first)))
    assert c.trade_candidate(with_storage(state(), second), project) is None
    assert c.trade_candidate(with_storage(state(), first, replace(first, position=1)), project) is None
    assert c.trade_candidate(with_storage(state(), second, first), project)['trainer_id'] == 7


def test_npc_trade_preserves_strongest_party_member_and_unique_field_moves():
    c = Collection()
    project = trade(c, 124)
    assert c.trade_candidate(state(party=(mon(level=30), mon(species=sid(61), level=50))), project) is None
    assert c.trade_candidate(state(party=(mon(level=50), mon(species=sid(61), level=20, moves=(57,)))), project) is None
    s = with_storage(state(party=(mon(level=50),)), replace(stored(61), moves=(57,)))
    assert c.trade_candidate(s, project) is None
    s = replace(s, party=(mon(level=50, moves=(57,)),))
    assert c.trade_candidate(s, project) is not None


def test_full_party_deposit_keeps_locks_field_moves_and_chosen_trade_reserve():
    p = StrategicPolicy(1)
    locked = mon(level=2, trainer_id=2, dvs=(1, 2, 3, 4, 5))
    offered = replace(locked, trainer_id=3)
    party = (mon(level=90), locked, offered, mon(level=5, moves=(57,)),
             mon(level=10), mon(level=15))
    p.trade_preferences = lambda: {identity(asdict(locked)): {'state': 'locked'},
                                   identity(asdict(offered)): {'state': 'offered'}}
    s = with_storage(state(party=party), stored(63))
    p.collection.project = trade(p.collection, 122)
    p.goal = p.collection.goal(s)
    p.pc_operation = 'deposit'
    assert p._pc_target(s) == 4
    assert p.collection.trade_candidate(replace(s, party=party[:4] + (locked, offered)), p.collection.project) is None


def test_active_npc_reserve_is_not_released_for_storage_space():
    p = StrategicPolicy(1)
    p.collection.project = trade(p.collection, 122)
    s = with_storage(state(), stored(63), stored(63, 1, trainer=8))
    assert p._release_target(s) is None


def test_dojo_choice_varies_by_seed_and_survives_save():
    assert {StrategicPolicy(seed).collection.dojo_choice for seed in range(30)} == {106, 107}
    for seed in range(5):
        p = StrategicPolicy(seed)
        restored = StrategicPolicy(seed + 100)
        restored.load_state_dict(p.state_dict())
        assert restored.collection.dojo_choice == p.collection.dojo_choice


@pytest.mark.parametrize('chosen,flag', [(106, 'EVENT_GOT_HITMONLEE'), (107, 'EVENT_GOT_HITMONCHAN')])
def test_dojo_choice_honors_already_received_gift(chosen, flag):
    c = Collection()
    c.dojo_choice = 213 - chosen
    c.observe(state(event_flags=flags('EVENT_GOT_POKEDEX', flag)))
    assert c.dojo_choice == chosen
    for target in (106, 107):
        assert not c.available(state(event_flags=flags(flag)), c.sources()[sid(target)][0])


@pytest.mark.parametrize('chosen', [106, 107])
def test_planner_only_offers_selected_dojo_gift(chosen):
    c = Collection()
    c.dojo_choice = chosen
    c.completed_champion = True
    all_sources = c.sources()
    c.sources = lambda: {sid(d): all_sources[sid(d)] for d in (106, 107)}
    candidates_seen = []
    def select(candidates, rng, urgent):
        candidates_seen.extend(p for _, p in candidates if p['method'] == 'gift')
        return candidates_seen[0]
    c.director.select = select
    nav = Navigator()
    nav.distance_lookup = Mock(return_value=lambda targets: 10)
    c.choose(state(), nav, random.Random(0), Goal('collect_plan', 'Plan', 'Plan'))
    assert [p['species'] for p in candidates_seen] == [sid(chosen)]


def test_legacy_dojo_project_keeps_its_selected_gift():
    c = Collection()
    c.load({'project': {'method': 'gift', 'species': sid(107)}})
    assert c.dojo_choice == 107


def test_npc_project_does_not_steal_field_move_party_selection_during_travel():
    from pokesim.policies.battle import Decision
    p = StrategicPolicy(1)
    p.collection.project = trade(p.collection, 124)
    p.goal = Goal('collect_trade', 'Trade', 'Reach the trader')
    p.intent = Decision('field', 0, 0, 'Use Cut')
    s = state(party=(mon(level=70, moves=(15,)), mon(species=sid(61), level=30)))
    mem = menu({1: '  CUT USER', 3: '  POLIWHIRL'}, (1, 1), top=(1, 1))
    assert p._dispatch(s, Screen(mem), 'party', mem)[0].button == 'a'
    assert not getattr(p, 'pending_trade_key', None)


@pytest.mark.parametrize('target,npc', [(122, 'GAMEBOY_KID'), (124, 'GAMBLER')])
def test_npc_goals_target_the_trader_instead_of_the_other_resident(target, npc):
    from pokesim.policies.progression import object_goal
    from pokesim.strategy_data import WORLD
    c = Collection()
    project = trade(c, target)
    actual = c.project_goal(state(), project)
    expected = object_goal('trade', 'Trade', 'Trade', WORLD[project['map']]['symbol'], npc)
    assert actual.targets == expected.targets
    assert actual.approaches == expected.approaches


def test_completed_travel_battles_keep_npc_expedition_alive():
    c = Collection()
    c.project = dict(trade(c, 124), key='npc')
    c.remaining = 180000
    for frame in range(0, 9000, 120):
        c.observe(state(frame=frame, in_battle=1 if frame % 600 else 0))
    assert c.project is not None
    assert c.idle_frames < 600


def test_owned_dojo_species_does_not_skip_its_unclaimed_gift():
    c = Collection()
    c.completed_champion = True
    c.dojo_choice = 107
    source = c.sources()[sid(107)][0]
    c.sources = lambda: {sid(107): [source]}
    c.director.select = lambda candidates, rng, urgent: next(p for _, p in candidates if p['method'] == 'gift')
    nav = Navigator()
    nav.distance_lookup = Mock(return_value=lambda targets: 10)
    s = state(owned=frozenset({1, 107}))
    c.choose(s, nav, random.Random(0), Goal('collect_plan', 'Plan', 'Plan'))
    c.observe(s)
    assert c.project is not None
    c.observe(replace(s, event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_GOT_HITMONCHAN')))
    assert c.project is None
