"""The Rocket Hideout B1F door to the elevator stays shut until the Rocket behind it is beaten.

The map draws the door open, so routes to the elevator walked into it and bounced between B1F and B2F
until the rung ended. The map script closes it while EVENT_BEAT_ROCKET_HIDEOUT_1_TRAINER_4 is unset.
"""
from pokesim.policies.navigation import Navigator
from pokesim.strategy_data import MAPS
from test_events import snap
from test_strategy import flags

B1F, ELEVATOR = MAPS['ROCKET_HIDEOUT_B1F'], MAPS['ROCKET_HIDEOUT_ELEVATOR']
DOOR = {(B1F, x, y) for x in (24, 25) for y in (16, 17)}
CAR = {(ELEVATOR, x, y) for x in range(4) for y in range(4)}


def route(event_flags):
    nav = Navigator()
    nav.update_story(snap(map=B1F, x=25, y=15, event_flags=event_flags))
    assert nav.route((B1F, 25, 15), CAR, 0) is not None
    return [target for _, _, target in nav.path]


def test_the_elevator_route_avoids_the_shut_door():
    path = route(flags())
    assert not DOOR & set(path)
    assert MAPS['ROCKET_HIDEOUT_B2F'] in {m for m, _, _ in path}


def test_the_door_opens_once_its_rocket_is_beaten():
    assert DOOR & set(route(flags('EVENT_BEAT_ROCKET_HIDEOUT_1_TRAINER_4')))


def way_out(event_flags):
    b4f = MAPS['ROCKET_HIDEOUT_B4F']
    nav = Navigator()
    nav.update_story(snap(map=b4f, x=24, y=12, event_flags=event_flags))
    corner = {(MAPS['GAME_CORNER'], x, y) for x in range(20) for y in range(18)}
    assert nav.route((b4f, 24, 12), corner, 0) is not None
    return nav, {m for _, _, (m, _, _) in nav.path}


def test_the_lift_leaves_for_b2f_while_the_door_is_shut():
    # A heal from Giovanni's floor rode down to the B1F stop and walked back into the lift until a fight opened the door.
    nav, maps = way_out(flags())
    assert nav.hideout_lift_floor() == 'B2F'
    assert MAPS['ROCKET_HIDEOUT_B2F'] in maps


def test_the_lift_leaves_for_b1f_once_the_door_is_open():
    nav, maps = way_out(flags('EVENT_BEAT_ROCKET_HIDEOUT_1_TRAINER_4'))
    assert nav.hideout_lift_floor() == 'B1F'
    assert MAPS['ROCKET_HIDEOUT_B2F'] not in maps
