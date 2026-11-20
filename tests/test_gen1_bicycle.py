"""Gen I Bicycle: the Fan Club voucher and the Cerulean bike shop on the road to Rock Tunnel, and getting
on for a long walk wherever the game allows a ride."""
from collections import deque

import pytest

from pokesim.policies.menus import tap
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import bicycle_goal, story_goal
from pokesim.policies.strategic import MOUNT_STEPS, WATER_TILES, StrategicPolicy, ride_ahead, rideable
from pokecore.gen1 import W_WALK_BIKE_SURF_STATE
from pokesim.strategy_data import ITEMS, MAPS, WORLD
from shortcut_fakes import Recorder
from test_events import snap
from test_gen1_flash import ABRA, road
from test_screen import fake_mem
from test_strategy import flags, mon

BIKE = ((ITEMS['BICYCLE'], 1),)
FLASH_KNOWN = (mon(level=40, moves=(15, 33, 22, 45)), mon(species=ABRA, level=20, moves=(100, 148, 0, 0)))


def line(m, x, y, steps, dy=-1):
    """A route of ``steps`` steps north from (x, y) on map ``m``, as navigation keeps it."""
    return [((m, x, y + dy * k), 'up', (m, x, y + dy * (k + 1))) for k in range(steps)]


def test_the_voucher_comes_before_the_bicycle_and_neither_once_it_is_owned():
    assert bicycle_goal(snap()).key == 'bike_voucher'
    assert bicycle_goal(snap(items=((ITEMS['BIKE_VOUCHER'], 1),))).key == 'bicycle'
    assert bicycle_goal(snap(items=BIKE)) is None
    assert bicycle_goal(snap(event_flags=flags('EVENT_GOT_BICYCLE'))) is None
    # A voucher put away in the PC never comes back to the bag, so the run goes on without the Bicycle.
    assert bicycle_goal(snap(event_flags=flags('EVENT_GOT_BIKE_VOUCHER'))) is None


def test_the_bicycle_waits_for_room_in_the_bag():
    """A deep Red save carried twenty kinds and nothing to sell, so the chairman had no room to give to."""
    fill = lambda n, *extra: tuple((ITEMS['POTION'] + k, 1) for k in range(n)) + extra
    voucher = (ITEMS['BIKE_VOUCHER'], 1)
    assert bicycle_goal(snap(items=fill(18))).key == 'bike_voucher'
    assert bicycle_goal(snap(items=fill(19))) is None
    assert bicycle_goal(snap(items=fill(18, voucher))).key == 'bicycle'
    assert bicycle_goal(snap(items=fill(19, voucher))) is None


def test_the_bicycle_is_fetched_after_flash_and_only_before_rock_tunnel():
    assert story_goal(road()).key == 'flash'
    assert story_goal(road(party=FLASH_KNOWN)).key == 'bike_voucher'
    assert story_goal(road(party=FLASH_KNOWN, items=((ITEMS['BIKE_VOUCHER'], 1),))).key == 'bicycle'
    assert story_goal(road(party=FLASH_KNOWN, items=BIKE)).key not in ('bike_voucher', 'bicycle')
    # A run already through the tunnel gets it after the League instead of walking back.
    past = road(party=FLASH_KNOWN, towns_visited=1 << MAPS['LAVENDER_TOWN'])
    assert story_goal(past).key not in ('bike_voucher', 'bicycle')


@pytest.mark.parametrize('name, allowed', [('ROUTE_1', True), ('VIRIDIAN_FOREST', True), ('MT_MOON_1F', True),
                                           ('ROUTE_23', True), ('INDIGO_PLATEAU', True), ('UNDERGROUND_PATH_NORTH_SOUTH', True),
                                           ('REDS_HOUSE_1F', False), ('VIRIDIAN_POKECENTER', False),
                                           ('VIRIDIAN_GYM', False), ('ROUTE_2_GATE', False)])
def test_the_bicycle_rides_where_the_game_allows_it(name, allowed):
    assert rideable(MAPS[name]) == allowed


def test_the_ride_ahead_counts_land_steps_up_to_the_mount_length():
    route = MAPS['ROUTE_1']
    assert ride_ahead(line(route, 9, 34, MOUNT_STEPS + 6)) == MOUNT_STEPS
    assert ride_ahead(line(route, 9, 34, 5)) == 5
    into_house = line(route, 9, 34, 2) + [((route, 9, 32), 'up', (MAPS['REDS_HOUSE_1F'], 2, 7))]
    assert ride_ahead(into_house + line(MAPS['REDS_HOUSE_1F'], 2, 7, 20)) == 2


def test_the_ride_ahead_stops_at_water():
    sea = MAPS['ROUTE_19']
    world = WORLD[sea]
    x, y = next((x, y) for y in range(1, world['height']) for x in range(world['width'])
                if Navigator._tile(world, x, y) in WATER_TILES and Navigator._tile(world, x, y - 1) not in WATER_TILES)
    assert ride_ahead([((sea, x, y), 'up', (sea, x, y - 1)), ((sea, x, y - 1), 'down', (sea, x, y))]) == 1


def riding(steps, state=0, items=BIKE, name='ROUTE_1'):
    policy = StrategicPolicy(7)
    shortcuts = Recorder.on(policy)
    m = MAPS[name]
    policy.nav.path = deque(line(m, 9, 30, steps))
    mem = fake_mem({})
    mem[W_WALK_BIKE_SURF_STATE] = state
    return policy, shortcuts, snap(map=m, x=9, y=30, items=items), mem


def test_a_long_walk_outdoors_gets_on_the_bicycle_first():
    policy, shortcuts, s, mem = riding(MOUNT_STEPS)
    assert policy._move(s, mem, 'up')
    assert shortcuts.kinds() == ['use_item'] and policy.shortcut.key == ('item', ITEMS['BICYCLE'], None)


@pytest.mark.parametrize('steps, items, name', [(MOUNT_STEPS - 1, BIKE, 'ROUTE_1'), (MOUNT_STEPS, (), 'ROUTE_1'),
                                                (MOUNT_STEPS, BIKE, 'VIRIDIAN_POKECENTER')],
                         ids=['short_walk', 'no_bicycle', 'indoors'])
def test_a_short_walk_or_a_walk_indoors_goes_on_foot(steps, items, name):
    policy, shortcuts, s, mem = riding(steps, items=items, name=name)
    assert policy._move(s, mem, 'up') == tap('up', 8, 12) and shortcuts.started == []


@pytest.mark.parametrize('state, press', [(1, tap('up', 4, 8)), (2, tap('up', 8, 12))], ids=['riding', 'surfing'])
def test_a_rider_presses_half_a_step_and_never_uses_the_bicycle_again(state, press):
    policy, shortcuts, s, mem = riding(MOUNT_STEPS, state=state)
    assert policy._move(s, mem, 'up') == press and shortcuts.started == []
