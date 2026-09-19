"""Directed Cable Club travel uses reachable routes and tolerates short input stalls."""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from pokesim.interactions.centers import CENTERS
from pokesim.policies.travel import TravelNavigator, TravelPolicy
from pokesim.strategy_data import MAPS, WORLD
from test_events import snap
from test_strategy import flags, mon


def trainer(**changes):
    values = dict(map=MAPS['VICTORY_ROAD_2F'], x=25, y=7, frame=1000,
                  badges=255, party=(mon(moves=(57, 70, 33)),))
    values.update(changes)
    return snap(**values)


def prepare_navigation(policy, snapshot):
    policy.nav.update_story(snapshot)
    policy.nav.live_map = snapshot.map
    policy.nav.live_positions = [tuple(obj[:2]) for obj in WORLD[snapshot.map]['objects']]


@pytest.mark.parametrize('targets', [((174, 15, 8),), tuple(center['pc'] for center in CENTERS.values())])
def test_destination_route_precedes_unneeded_dungeon_puzzle(monkeypatch, targets):
    policy = TravelPolicy(targets)
    snapshot = trainer()
    prepare_navigation(policy, snapshot)
    puzzle = Mock(side_effect=AssertionError('A reachable exit must not start another puzzle'))
    monkeypatch.setattr(policy.boulders, 'route', puzzle)
    assert policy._overworld(snapshot, bytearray(65536))[0].button == 'down'
    assert policy.goal.targets == policy.targets
    assert policy.nav.path[-1][2] == (174, 15, 8)


def test_western_victory_road_can_reach_indigo_without_restarting_collection():
    policy = TravelPolicy(((MAPS['INDIGO_PLATEAU_LOBBY'], 15, 8),))
    snapshot = trainer(x=2, y=11, event_flags=flags(
        'EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH1',
        'EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH2',
        'EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH1',
        'EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH2'))
    prepare_navigation(policy, snapshot)
    action = policy._overworld(snapshot, bytearray(65536))[0]
    assert action.button == 'right'
    assert policy.nav.path[-1][2] == (174, 15, 8)
    assert policy.goal.key == 'cable_travel'


def test_temporary_block_waits_then_reports_a_persistent_obstacle():
    policy = TravelPolicy(((89, 13, 4),))
    snapshot = trainer(map=0, x=5, y=5)
    policy.nav.route = Mock(return_value=None)
    policy.nav.blocked[((snapshot.map, 5, 5), 'down')] = snapshot.frame + 600
    action = policy._overworld(snapshot, bytearray(65536))[0]
    assert action.button is None and action.gap > 0
    assert 'temporary obstacle' in policy.reason
    with pytest.raises(ValueError, match='unresolved obstacle'):
        policy._overworld(replace(snapshot, frame=snapshot.frame + 600), bytearray(65536))


def test_block_on_another_map_does_not_hide_an_unreachable_destination():
    policy = TravelPolicy(((89, 13, 4),))
    snapshot = trainer(map=0, x=5, y=5)
    policy.nav.route = Mock(return_value=None)
    policy.nav.blocked[((194, 25, 7), 'down')] = snapshot.frame + 600
    with pytest.raises(ValueError, match='unresolved obstacle'):
        policy._overworld(snapshot, bytearray(65536))


def test_lower_eastern_corridor_tries_reachable_ladder_instead_of_x_region():
    policy = TravelPolicy(((89, 13, 4),))
    snapshot = trainer(x=24, y=16)
    prepare_navigation(policy, snapshot)
    policy.boulders.route = Mock(return_value=None)
    assert policy.nav.route((194, 24, 16), ((198, 27, 15),), snapshot.frame) is None
    assert policy._overworld(snapshot, bytearray(65536))[0].button == 'right'
    assert policy.nav.path[-1][2] == (198, 23, 7)


def test_remote_puzzle_gate_is_not_assumed_open_just_for_having_strength():
    navigation = TravelNavigator()
    snapshot = trainer()
    navigation.update_story(snapshot)
    assert (MAPS['VICTORY_ROAD_1F'], 9, 12) in navigation.closed_passages
    snapshot = replace(snapshot, event_flags=flags('EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH'))
    navigation.update_story(snapshot)
    assert (MAPS['VICTORY_ROAD_1F'], 9, 12) not in navigation.closed_passages


@pytest.mark.parametrize('snapshot, next_map', [
    (trainer(map=MAPS['ROUTE_23'], x=9, y=93), MAPS['VICTORY_ROAD_1F']),
    (trainer(map=MAPS['VICTORY_ROAD_1F'], x=17, y=11,
             event_flags=flags('EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH')),
     MAPS['VICTORY_ROAD_2F']),
])
def test_center_journey_approaches_unsolved_remote_puzzle(snapshot, next_map):
    policy = TravelPolicy(((MAPS['INDIGO_PLATEAU_LOBBY'], 15, 8),))
    prepare_navigation(policy, snapshot)
    pos = (snapshot.map, snapshot.x, snapshot.y)
    assert policy.nav.route(pos, policy.targets, snapshot.frame) is None
    closed = policy.nav.closed_passages.copy()
    memory = bytearray(65536)
    memory[0xD700] = 2
    action = policy._overworld(snapshot, memory)[0]
    assert action.button in ('up', 'down', 'left', 'right')
    assert policy.nav.path[-1][2][0] == next_map
    assert all(source[0] == snapshot.map for source, _, _ in policy.nav.path)
    assert policy.nav.closed_passages == closed
    assert not any(target in closed for _, _, target in policy.nav.path)
    assert policy.goal.targets == policy.targets


def test_remote_puzzle_approach_requires_strength_partner():
    policy = TravelPolicy(((MAPS['INDIGO_PLATEAU_LOBBY'], 15, 8),))
    snapshot = trainer(map=MAPS['ROUTE_23'], x=9, y=93, party=(mon(moves=(57, 33)),))
    prepare_navigation(policy, snapshot)
    assert policy.nav.approach_next_map(snapshot, policy.targets) is None


def test_remote_puzzle_approach_does_not_bypass_current_closed_gate():
    policy = TravelPolicy(((MAPS['INDIGO_PLATEAU_LOBBY'], 15, 8),))
    snapshot = trainer(map=MAPS['VICTORY_ROAD_1F'], x=2, y=15)
    prepare_navigation(policy, snapshot)
    assert policy.nav.approach_next_map(snapshot, policy.targets) is None


def test_current_puzzle_precedes_planning_another_map(monkeypatch):
    policy = TravelPolicy(tuple(center['pc'] for center in CENTERS.values()))
    snapshot = trainer(map=MAPS['VICTORY_ROAD_3F'], x=23, y=7)
    prepare_navigation(policy, snapshot)
    monkeypatch.setattr(policy.nav, 'route', Mock(return_value=None))
    monkeypatch.setattr(policy.boulders, 'route', Mock(return_value='left'))
    monkeypatch.setattr(policy.nav, 'approach_next_map', Mock(
        side_effect=AssertionError('Solve the current puzzle before leaving its floor')))
    memory = bytearray(65536)
    memory[0xD728] = 1
    assert policy._overworld(snapshot, memory)[0].button == 'left'
