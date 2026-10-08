"""Cinnabar Gym doors stay shut until their quiz trainer is beaten, so Blaine is reached one door at a time."""
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import gym_goal
from pokesim.strategy_data import MAPS, WORLD
from test_events import snap
from test_strategy import flags, mon

GYM = MAPS['CINNABAR_GYM']
GATES = [f'EVENT_CINNABAR_GYM_GATE{n}_UNLOCKED' for n in range(1, 7)]


def test_locked_doors_wall_the_static_floor_until_their_flag_is_set():
    nav = Navigator()
    nav.update_story(snap(map=GYM, badges=63))
    world = WORLD[GYM]
    # The map file draws the first door open. Its top row closes and the row below stays walkable.
    assert world['tiles'][6][18] in world['passable']
    assert nav.active_tile(world, 18, 6) not in world['passable']
    assert nav.active_tile(world, 18, 7) in world['passable']
    # The vertical door at block (3, 8) closes its right column.
    assert nav.active_tile(world, 7, 16) not in world['passable']
    assert nav.active_tile(world, 6, 16) in world['passable']
    nav.update_story(snap(map=GYM, badges=63, event_flags=flags(*GATES)))
    assert nav.active_tile(world, 18, 6) in world['passable']
    assert nav.active_tile(world, 7, 16) in world['passable']


def test_the_volcano_goal_faces_the_trainer_of_the_first_locked_door():
    party = (mon(level=70),)
    first = gym_goal(snap(map=GYM, badges=63, party=party), 64)
    assert first.title == "Open Blaine's gym doors" and first.interact
    assert (GYM, 17, 9) in first.targets          # below Super Nerd 2, who faces down
    third = gym_goal(snap(map=GYM, badges=63, party=party, event_flags=flags(*GATES[:2])), 64)
    assert (GYM, 11, 9) in third.targets          # Super Nerd 4 at (11, 8)
    blaine = gym_goal(snap(map=GYM, badges=63, party=party, event_flags=flags(*GATES)), 64)
    assert blaine.title == 'Challenge Blaine'
