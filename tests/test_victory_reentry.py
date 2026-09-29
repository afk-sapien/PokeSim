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


def test_legendary_expedition_leaves_closed_east_pocket_by_accessible_ladder():
    from pokesim.policies.progression import Goal
    from test_screen import fake_mem
    from test_travel import trainer, prepare_navigation
    s = trainer(x=24, y=13)
    policy = StrategicPolicy(0)
    prepare_navigation(policy, s)
    goal = Goal('collect_static', 'Collect Zapdos', '', ((MAPS['POWER_PLANT'], 4, 10),))
    policy.collection.project = {'method': 'static', 'species': 75}
    policy.collection.choose = lambda *args: goal
    policy.pickups.choose = lambda *args: None
    action = policy._overworld(s, fake_mem({}))[0]
    assert action.button in ('down', 'right')
    assert policy.nav._open_navigation is not None
    assert policy.nav._open_navigation.path[-1][2] == (MAPS['VICTORY_ROAD_3F'], 27, 15)


def test_return_corridor_drops_accessible_boulder_before_unreachable_upper_switch():
    from pokesim.policies.progression import Goal
    from test_screen import fake_mem
    from test_travel import trainer, prepare_navigation
    s = trainer(map=MAPS['VICTORY_ROAD_3F'], x=23, y=10)
    policy = StrategicPolicy(0)
    prepare_navigation(policy, s)
    policy.nav.live_positions[-2] = (22, 10)
    goal = Goal('collect_static', 'Collect Zapdos', '', ((MAPS['POWER_PLANT'], 4, 10),))
    policy.collection.project = {'method': 'static', 'species': 75}
    policy.collection.choose = lambda *args: goal
    policy.pickups.choose = lambda *args: None
    memory = fake_mem({})
    memory[0xD728] = 1
    action = policy._overworld(s, memory)[0]
    assert action.button == 'down'
    assert policy.mode == 'moving a boulder onto the switch'
    assert policy.boulders.task == (s.map, ('BOULDER4', (23, 15)))


def test_after_lower_return_switch_climb_to_upper_puzzle_not_back_to_east_pocket():
    from pokesim.policies.progression import Goal
    from test_screen import fake_mem
    from test_travel import trainer, prepare_navigation
    s = trainer(x=22, y=16, event_flags=flags('EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH2',
                                            'EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH2'))
    policy = StrategicPolicy(0)
    prepare_navigation(policy, s)
    policy.nav.live_positions[-1] = (9, 16)
    goal = Goal('collect_static', 'Collect Zapdos', '', ((MAPS['POWER_PLANT'], 4, 10),))
    policy.collection.project = {'method': 'static', 'species': 75}
    policy.collection.choose = lambda *args: goal
    policy.pickups.choose = lambda *args: None
    policy._overworld(s, fake_mem({}))
    assert policy.nav._open_navigation.path[-1][2] == (MAPS['VICTORY_ROAD_3F'], 23, 7)


def test_open_upper_switch_continues_to_western_ladder_for_southern_expedition():
    from pokesim.policies.progression import Goal
    from test_screen import fake_mem
    from test_travel import trainer, prepare_navigation
    s = trainer(map=MAPS['VICTORY_ROAD_3F'], x=23, y=7,
                event_flags=flags('EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH1',
                                  'EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH2',
                                  'EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH2'))
    policy = StrategicPolicy(0)
    prepare_navigation(policy, s)
    policy.nav.live_positions[-4] = (3, 5)
    goal = Goal('collect_static', 'Collect Zapdos', '', ((MAPS['POWER_PLANT'], 4, 10),))
    policy.collection.project = {'method': 'static', 'species': 75}
    policy.collection.choose = lambda *args: goal
    policy.pickups.choose = lambda *args: None
    policy._overworld(s, fake_mem({}))
    assert policy.nav._open_navigation.path[-1][2] == (MAPS['VICTORY_ROAD_2F'], 1, 1)


def test_open_middle_switch_continues_to_first_floor_for_southern_expedition():
    from pokesim.policies.progression import Goal
    from test_screen import fake_mem
    from test_travel import trainer, prepare_navigation
    s = trainer(x=2, y=11, event_flags=flags('EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH1'))
    policy = StrategicPolicy(0)
    prepare_navigation(policy, s)
    policy.nav.live_positions[-3] = (1, 16)
    goal = Goal('collect_static', 'Collect Zapdos', '', ((MAPS['POWER_PLANT'], 4, 10),))
    policy.collection.project = {'method': 'static', 'species': 75}
    policy.collection.choose = lambda *args: goal
    policy.pickups.choose = lambda *args: None
    policy._overworld(s, fake_mem({}))
    assert policy.nav._open_navigation.path[-1][2] == (MAPS['VICTORY_ROAD_1F'], 1, 1)


def test_western_return_ladder_clears_loose_boulder_to_reach_entrance_switch():
    from pokesim.policies.progression import Goal
    from pokesim.policies.puzzles import boulder_task
    from test_screen import fake_mem
    from test_travel import trainer, prepare_navigation
    s = trainer(x=1, y=1)
    policy = StrategicPolicy(0)
    prepare_navigation(policy, s)
    goal = Goal('collect_static', 'Collect Zapdos', '', ((MAPS['POWER_PLANT'], 4, 10),))
    policy.collection.project = {'method': 'static', 'species': 75}
    policy.collection.choose = lambda *args: goal
    policy.pickups.choose = lambda *args: None
    memory = fake_mem({})
    memory[0xD728] = 1
    policy._overworld(s, memory)
    assert policy.boulders.task == (s.map, ('BOULDER2', (5, 6)))
    policy.nav.live_positions[-2] = (5, 6)
    after = replace(s, x=5, y=5)
    assert policy.boulders.route(after, policy.nav, boulder_task(after)) is not None


def test_first_floor_return_clears_corridor_before_reopening_exit():
    from pokesim.policies.progression import Goal
    from pokesim.policies.puzzles import boulder_task
    from test_screen import fake_mem
    from test_travel import trainer, prepare_navigation
    s = trainer(map=MAPS['VICTORY_ROAD_1F'], x=1, y=1)
    policy = StrategicPolicy(0)
    prepare_navigation(policy, s)
    goal = Goal('collect_static', 'Collect Zapdos', '', ((MAPS['POWER_PLANT'], 4, 10),))
    policy.collection.project = {'method': 'static', 'species': 75}
    policy.collection.choose = lambda *args: goal
    policy.pickups.choose = lambda *args: None
    memory = fake_mem({})
    memory[0xD728] = 1
    policy._overworld(s, memory)
    assert policy.boulders.task == (s.map, ('BOULDER3', (2, 13)))
    policy.nav.live_positions[-1] = (2, 13)
    after = replace(s, x=2, y=12)
    assert policy.boulders.route(after, policy.nav, boulder_task(after)) is not None
