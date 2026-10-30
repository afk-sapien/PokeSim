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
