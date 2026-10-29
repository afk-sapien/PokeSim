"""NPC exchanges retrieve the chosen reserve without spending protected partners."""
from dataclasses import asdict, replace
from unittest.mock import Mock
import random

import pytest

from pokesim.policies.collection import Collection, candidate
from pokesim.policies.director import AdventureDirector
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.ram import StoredMon
from pokesim.screen import Screen
from pokesim.trade.preferences import identity
from test_collection import sid, state
from test_strategy import flags, menu, mon
from shortcut_fakes import Scripted


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
    p.pc.operation = 'withdraw'
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
    c.director.select = lambda options, projects: next(p for p in projects.values() if p['method'] == 'trade')
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
    p.pc.operation = 'deposit'
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
    def select(options, projects):
        candidates_seen.extend(p for p in projects.values() if p['method'] == 'gift')
        return candidates_seen[0]
    c.director.select = select
    nav = Navigator()
    nav.distance_lookup = Mock(return_value=lambda targets: 10)
    c.choose(state(), nav, random.Random(0), Goal('collect_plan', 'Plan', 'Plan'))
    assert [p['species'] for p in candidates_seen] == [sid(chosen)]


@pytest.mark.parametrize('fragment,tile', [('HITMONLEE', (4, 2)), ('HITMONCHAN', (5, 2))])
def test_dojo_ball_is_approached_from_below_never_from_the_other_ball(fragment, tile):
    from pokesim.policies.progression import object_goal
    from pokesim.strategy_data import MAPS
    goal = object_goal('collect_gift', '', '', 'FIGHTING_DOJO', fragment)
    assert goal.targets == ((MAPS['FIGHTING_DOJO'], *tile),) and goal.facing == 'up'


def balls_hidden(map_name, fragment):
    from pokesim.strategy_data import DATA, MAPS, WORLD
    room = MAPS[map_name]
    hidden = bytearray(32)
    for index, obj in enumerate(WORLD[room]['objects']):
        if fragment in obj[4]:
            toggle = DATA['toggle_objects'].index([room, index])
            hidden[toggle // 8] |= 1 << toggle % 8
    return bytes(hidden)


def dojo_return(*party, hidden=bytes(32)):
    from pokesim.strategy_data import MAPS
    owned = frozenset({1, 106, 107})
    return state(map=MAPS['FIGHTING_DOJO'], party=(mon(hp=100, max_hp=100, level=40),) + party,
                 owned=owned, hidden_objects=hidden)


def test_a_gift_taken_by_someone_else_stops_the_wait():
    c = Collection()
    c.dojo_choice = 106
    c.project = dict(c.sources()[sid(106)][0], species=sid(106))
    c.observe(dojo_return())
    assert c.project
    # The other ball was taken, which hides both. Hitmonlee is gone without joining.
    c.observe(dojo_return(hidden=balls_hidden('FIGHTING_DOJO', 'HITMON')))
    assert c.project is None and 'no longer offered' in c.history[-1]


def test_a_gift_that_joined_finishes_once_its_source_is_gone():
    c = Collection()
    c.dojo_choice = 106
    c.project = dict(c.sources()[sid(106)][0], species=sid(106))
    c.observe(dojo_return())
    # Both balls hide while the event flag is not read yet. Hitmonlee in the party means it was received.
    c.observe(dojo_return(mon(species=sid(106)), hidden=balls_hidden('FIGHTING_DOJO', 'HITMON')))
    assert c.project is None and 'no longer offered' not in ''.join(c.history)


def test_legacy_dojo_project_keeps_its_selected_gift():
    c = Collection()
    c.load({'project': {'method': 'gift', 'species': sid(107)}})
    assert c.dojo_choice == 107


def test_npc_project_does_not_steal_field_move_party_selection_during_travel():
    from pokesim.policies.base import PolicyContext
    p = StrategicPolicy(1)
    p.collection.project = trade(p.collection, 124)
    p.goal = Goal('collect_trade', 'Trade', 'Reach the trader')
    s = state(party=(mon(level=70, moves=(15,)), mon(species=sid(61), level=30)))
    mem = menu({1: '  CUT USER', 3: '  POLIWHIRL'}, (1, 1), top=(1, 1))
    p.collection.observe = lambda *args, **kwargs: None
    p.shortcut.start(Scripted('use_field_move', ['a', 'a']), 'cut', s.frame, mem)
    assert p.step(PolicyContext(s, 0, 0, mem))[0].button == 'a'
    assert p.shortcut.active and not getattr(p, 'pending_trade_key', None)


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


def test_the_dojo_gift_outranks_a_quality_hunt_and_its_budget_covers_the_visit():
    c = Collection()
    c.dojo_choice = 106
    source = dict(c.sources()[sid(106)][0], species=sid(106), key='43:gift:177:HITMONLEE')
    hunt = {'method': 'grass', 'species': sid(16), 'map': 12, 'key': 'hunt', 'repeat': True, 'dv_hunt': True,
            'catch_goal': 3}
    options = [candidate(project, 300, {sid(16): 100}, False, {16, 106}) for project in (source, hunt)]
    assert AdventureDirector.select(options, {'43:gift:177:HITMONLEE': source, 'hunt': hunt}) is source
    # Yellow's Dojo visits took 16000 to 41000 frames from 300 tiles away. The budget is three times
    # what the visit is expected to take.
    assert 3 * options[0].expected_frames > 41000


def test_owned_dojo_species_does_not_skip_its_unclaimed_gift():
    c = Collection()
    c.completed_champion = True
    c.dojo_choice = 107
    source = c.sources()[sid(107)][0]
    c.sources = lambda: {sid(107): [source]}
    c.director.select = lambda options, projects: next(p for p in projects.values() if p['method'] == 'gift')
    nav = Navigator()
    nav.distance_lookup = Mock(return_value=lambda targets: 10)
    s = state(owned=frozenset({1, 107}))
    c.choose(s, nav, random.Random(0), Goal('collect_plan', 'Plan', 'Plan'))
    c.observe(s)
    assert c.project is not None
    c.observe(replace(s, event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_GOT_HITMONCHAN')))
    assert c.project is None
