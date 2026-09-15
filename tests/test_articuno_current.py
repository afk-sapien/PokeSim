"""Reach Articuno through ordinary Strength pushes and the game's current flags."""
from dataclasses import replace

from pokesim.policies.collection import Collection
from pokesim.policies.navigation import DIRS, SEAFOAM_HOLES, Navigator
from pokesim.policies.puzzles import BoulderPlanner, seafoam_current_task
from pokesim.policies.strategic import StrategicPolicy
from pokesim.screen import Screen
from pokesim.strategy_data import DATA, MAPS, WORLD
from test_collection import sid, state
from test_screen import fake_mem
from test_strategy import flags, mon


FIRST = 'EVENT_SEAFOAM4_BOULDER1_DOWN_HOLE'
SECOND = 'EVENT_SEAFOAM4_BOULDER2_DOWN_HOLE'


def test_articuno_goal_requires_both_boulders_before_surf():
    c = Collection()
    project = {'method': 'static', 'species': sid(144), 'map': MAPS['SEAFOAM_ISLANDS_B4F'], 'fragment': 'ARTICUNO'}
    for done in ((), (FIRST,), (SECOND,)):
        goal = c.project_goal(state(event_flags=flags(*done)), project)
        assert goal.key == 'collect_seafoam_current'
        assert goal.targets == ((MAPS['SEAFOAM_ISLANDS_B3F'], 6, 15),)
    assert c.project_goal(state(event_flags=flags(FIRST, SECOND)), project).key == 'collect_static'


def test_articuno_expedition_requires_a_strength_partner():
    source = {'method': 'static', 'species': sid(144), 'map': MAPS['SEAFOAM_ISLANDS_B4F'], 'fragment': 'ARTICUNO'}
    c = Collection()
    assert not c.available(state(party=(mon(moves=(57,)),)), source)
    assert c.available(state(party=(mon(moves=(57, 70)),)), source)


def test_push_plan_clears_both_holes_without_dropping_the_player():
    room = MAPS['SEAFOAM_ISLANDS_B3F']
    nav = Navigator()
    nav.live_map = room
    nav.live_positions = [tuple(obj[:2]) for obj in WORLD[room]['objects']]
    planner = BoulderPlanner()
    s = state(map=room, x=8, y=6)
    done = []
    hidden = bytearray(32)
    for step in range(300):
        nav.update_story(s)
        task = seafoam_current_task(s, nav)
        if task is None:
            break
        direction = planner.route(s, nav, task)
        assert direction is not None, (s.x, s.y, task)
        dx, dy = DIRS[direction]
        dest = s.x + dx, s.y + dy
        assert (room, *dest) not in SEAFOAM_HOLES
        index = next(i for i, obj in enumerate(WORLD[room]['objects']) if obj[4].endswith(task[0]))
        if dest == nav.live_positions[index]:
            ahead = dest[0] + dx, dest[1] + dy
            assert ahead not in [p for i, p in enumerate(nav.live_positions) if i != index
                                 and (room, *WORLD[room]['objects'][i][:2]) not in nav.cleared_objects]
            nav.live_positions[index] = ahead
            if (room, *ahead) in SEAFOAM_HOLES:
                flag = {(3, 16): FIRST, (6, 16): SECOND}[ahead]
                assert index == (1 if flag == FIRST else 2)
                done.append(flag)
                bit = DATA['toggle_objects'].index([room, index])
                hidden[bit // 8] |= 1 << (bit % 8)
        s = replace(s, x=dest[0], y=dest[1], frame=s.frame + 32,
                    event_flags=flags(*done), hidden_objects=bytes(hidden))
    assert done == [FIRST, SECOND]
    assert step < 300
    assert seafoam_current_task(s, nav) is None


def test_completed_first_hole_is_not_reopened_after_room_reentry():
    room = MAPS['SEAFOAM_ISLANDS_B3F']
    nav = Navigator()
    nav.live_positions = [tuple(obj[:2]) for obj in WORLD[room]['objects']]
    s = state(map=room, event_flags=flags(FIRST))
    assert seafoam_current_task(s, nav) == ('BOULDER4', (9, 12))


def test_current_refusal_exits_the_surf_menu():
    from pokesim.policies.battle import Decision
    policy = StrategicPolicy(7)
    policy.intent = Decision('field', 0)
    policy.field_move = 'SURF'
    s = state(map=MAPS['SEAFOAM_ISLANDS_B4F'], textbox=True)
    memory = fake_mem({14: 'The current is', 16: 'much too fast!'})
    action = policy._dispatch(s, Screen(memory), 'dialogue', memory)[0]
    assert action.button == 'b'
    assert policy.intent is None and policy.field_move is None
