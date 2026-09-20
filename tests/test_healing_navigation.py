"""Healing routes avoid disconnected observations and unnecessary dungeon puzzles."""
from unittest.mock import Mock

import pytest

from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import healing_goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import MAPS, WORLD
from test_events import snap
from test_strategy import mon


def test_unrelated_map_change_is_not_learned_as_a_walk():
    nav = Navigator()
    source = (MAPS['VICTORY_ROAD_2F'], 7, 11)
    target = (MAPS['LAVENDER_TOWN'], 3, 6)
    nav.issued(source, 'right', 0)
    nav.observe(target, 60)
    assert source not in nav.edges
    assert nav.attempt is None


def test_saved_disconnected_walk_is_removed_without_losing_real_steps():
    nav = Navigator()
    source = (MAPS['VICTORY_ROAD_2F'], 7, 11)
    target = (MAPS['LAVENDER_TOWN'], 3, 6)
    neighbor = (source[0], 6, 11)
    nav.load_state_dict({'edges': [[source, 'right', target], [source, 'left', neighbor]],
                         'visits': [[source, 12]]})
    assert nav.edges[source] == {'left': neighbor}
    assert nav.visits[source] == 12
    assert all(destination != target for _, destination in nav.neighbors(source, 0))


@pytest.mark.parametrize('source, direction, target', [
    ((MAPS['VICTORY_ROAD_2F'], 28, 8), 'right', (MAPS['ROUTE_23'], 14, 31)),
    ((MAPS['ROUTE_23'], 10, 0), 'up', (MAPS['INDIGO_PLATEAU'], 10, 17)),
    ((MAPS['POKEMON_MANSION_3F'], 16, 13), 'down', (MAPS['POKEMON_MANSION_1F'], 16, 14)),
    ((MAPS['VICTORY_ROAD_3F'], 23, 14), 'down', (MAPS['VICTORY_ROAD_2F'], 22, 16)),
])
def test_real_exits_connections_and_scripted_falls_remain_learned(source, direction, target):
    nav = Navigator()
    nav.issued(source, direction, 0)
    nav.observe(target, 60)
    assert nav.edges[source][direction] == target
    restored = Navigator()
    restored.load_state_dict(nav.state_dict())
    assert restored.edges[source][direction] == target


def test_healing_uses_reachable_victory_road_exit_before_resetting_puzzles(monkeypatch):
    policy = StrategicPolicy(7)
    state = snap(map=MAPS['VICTORY_ROAD_3F'], x=26, y=11, frame=1000,
                 badges=255, party=(mon(level=100, hp=10, moves=(57, 70, 33)),))
    policy.nav.update_story(state)
    policy.nav.live_map = state.map
    policy.nav.live_positions = [tuple(obj[:2]) for obj in WORLD[state.map]['objects']]
    monkeypatch.setattr(policy.boulders, 'route', Mock(
        side_effect=AssertionError('A reachable healing exit must precede puzzle work')))
    action = policy._overworld(state, bytearray(65536))[0]
    assert action.button in ('up', 'down', 'left', 'right')
    assert policy.goal.key == 'heal'
    assert policy.nav.path[-1][2] == (MAPS['INDIGO_PLATEAU_LOBBY'], 7, 7)


def test_healing_does_not_skip_current_puzzle_for_a_closed_remote_gate(monkeypatch):
    policy = StrategicPolicy(7)
    state = snap(map=MAPS['VICTORY_ROAD_3F'], x=23, y=7, frame=1000,
                 badges=255, party=(mon(level=100, hp=10, moves=(57, 70, 33)),))
    policy.nav.update_story(state)
    policy.nav.live_map = state.map
    policy.nav.live_positions = [tuple(obj[:2]) for obj in WORLD[state.map]['objects']]
    targets = healing_goal(state).targets
    assert policy.nav.route((state.map, state.x, state.y), targets, state.frame) is not None
    assert policy.nav.open_route(state, targets) is None
    puzzle = Mock(return_value='left')
    monkeypatch.setattr(policy.boulders, 'route', puzzle)
    memory = bytearray(65536)
    memory[0xD728] = 1
    assert policy._overworld(state, memory)[0].button == 'left'
    puzzle.assert_called_once()


def test_open_route_rechecks_remote_switches_after_a_map_change():
    from dataclasses import replace
    from test_strategy import flags
    nav = Navigator()
    state = snap(map=MAPS['ROUTE_23'], x=9, y=93, frame=1000,
                 badges=255, party=(mon(moves=(57, 70, 33)),), event_flags=flags(
                     'EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH',
                     'EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH1',
                     'EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH2',
                     'EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH1',
                     'EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH2'))
    targets = ((MAPS['INDIGO_PLATEAU_LOBBY'], 7, 7),)
    assert nav.open_route(state, targets) is not None
    closed = replace(state, event_flags=flags())
    assert nav.open_route(closed, targets) is None


def test_learned_walk_does_not_pass_through_a_boulder_that_moved_back():
    nav = Navigator()
    state = snap(map=MAPS['VICTORY_ROAD_2F'], x=22, y=16)
    nav.update_story(state)
    nav.live_map = state.map
    nav.live_positions = [tuple(obj[:2]) for obj in WORLD[state.map]['objects']]
    rock = next(i for i, obj in enumerate(WORLD[state.map]['objects'])
                if obj[4].endswith('BOULDER3'))
    nav.live_positions[rock] = (23, 16)
    source, target = (state.map, 22, 16), (state.map, 23, 16)
    nav.edges[source] = {'right': target}
    assert ('right', target) not in nav.neighbors(source, state.frame)
    assert nav.route(source, (target,), state.frame) is None
    nav.live_positions[rock] = (22, 15)
    assert ('right', target) in nav.neighbors(source, state.frame)
    assert nav.route(source, (target,), state.frame) == 'right'


def test_a_nurse_on_open_floor_is_approached_directly_and_a_center_nurse_across_her_counter():
    from pokesim.policies.progression import healing_goal
    from pokesim.strategy_data import MAPS, WORLD
    from test_events import snap
    silph = MAPS['SILPH_CO_9F']
    nurse = next(o for o in WORLD[silph]['objects'] if o[2] == 'SPRITE_NURSE')
    assert healing_goal(snap(map=silph)).targets == ((silph, nurse[0], nurse[1] + 1),)
    center = MAPS['VIRIDIAN_POKECENTER']
    desk = next(o for o in WORLD[center]['objects'] if o[2] == 'SPRITE_NURSE')
    assert healing_goal(snap(map=center)).targets == ((center, desk[0], desk[1] + 2),)


def test_the_silph_nurse_is_not_a_heal_target_once_the_building_is_freed():
    from pokesim.policies.progression import healing_goal
    from pokesim.strategy_data import MAPS
    from test_events import snap
    from test_strategy import flags
    silph = MAPS['SILPH_CO_9F']
    freed = healing_goal(snap(map=silph, event_flags=flags('EVENT_BEAT_SILPH_CO_GIOVANNI')))
    assert freed.targets and all(m != silph for m, _, _ in freed.targets)

