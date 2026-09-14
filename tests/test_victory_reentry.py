from dataclasses import replace

from pokesim.policies.navigation import Navigator
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import MAPS, WORLD
from test_events import snap
from test_strategy import flags, mon


def test_remembered_steps_cannot_cross_a_reset_switch_gate():
    m = MAPS['VICTORY_ROAD_2F']
    source, gate, beyond = (m, 22, 14), (m, 23, 14), (m, 24, 14)
    nav = Navigator()
    nav.load_state_dict({'edges': [[list(source), 'right', list(gate)],
                                   [list(gate), 'right', list(beyond)]]})
    closed = snap(map=m, party=(mon(moves=(70, 0, 0, 0)),))
    nav.update_story(closed)
    assert ('right', gate) not in nav.neighbors(source, 0)
    assert nav.route(source, [beyond], 0) is None

    opened = replace(closed, event_flags=flags('EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH2'))
    nav.update_story(opened)
    assert ('right', gate) in nav.neighbors(source, 0)
    assert nav.route(source, [beyond], 0) == 'right'

    nav.update_story(closed)
    assert nav.route(source, [beyond], 0) is None


def test_healing_from_middle_floor_can_reach_the_upper_puzzle():
    s = snap(map=MAPS['VICTORY_ROAD_2F'], x=14, y=9, frame=100,
             badges=255, party=(mon(hp=30, max_hp=100, moves=(70, 0, 0, 0), pp=(0, 0, 0, 0)),))
    policy = StrategicPolicy(7)
    policy.nav.update_story(s)
    policy.nav.live_map = s.map
    policy.nav.live_positions = [(o[0], o[1]) for o in WORLD[s.map]['objects']]
    action = policy._overworld(s, bytearray(65536))[0]
    assert policy.mode == 'following objective'
    assert action.button in ('up', 'down', 'left', 'right')
    assert policy.nav.target == frozenset({(MAPS['VICTORY_ROAD_3F'], 23, 7)})
