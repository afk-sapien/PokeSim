"""Ice sliding, the region graph on ice maps and the escalation when no route exists."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2 import ice
from pokesim.gen2.data import GameData
from pokesim.gen2.navigation import Navigator
from pokesim.gen2.policy import Policy
from tools.check_gen2_ice import reachable

ICE, DOOR, WALL, FLOOR = 0x23, 0x72, 0x07, 0x00
ROOM, HALL = 1, 2


def synthetic():
    """An open ice room where the door at (3, 2) can only be reached when something stops a slide above it."""
    permissions = [0] * 256
    permissions[WALL] = 7
    room = [ICE] * 48
    room[0 * 8 + 7] = DOOR
    room[2 * 8 + 3] = DOOR
    hall = [FLOOR] * 16
    hall[0] = DOOR
    maps = {
        ROOM: dict(constant='TEST_ICE_ROOM', width=8, height=6, collision=room, objects=[], connections=[],
                   warps=[dict(x=7, y=0, map=HALL, warp=1), dict(x=3, y=2, map=HALL, warp=1)]),
        HALL: dict(constant='TEST_HALL', width=4, height=4, collision=hall, objects=[], connections=[],
                   warps=[dict(x=0, y=0, map=ROOM, warp=1)]),
    }
    return SimpleNamespace(maps=maps, permissions=permissions, events={}, items={}, map_ids={'TEST_ICE_ROOM': ROOM})


def snapshot(x, y, mid=ROOM):
    return SimpleNamespace(map=mid, x=x, y=y, badges=0, party=[], objects=(), frame=0, in_battle=False,
                           event=lambda name: False)


def test_a_slide_runs_to_the_wall_a_stopper_or_a_door():
    data = synthetic()
    grid, enter = data.maps[ROOM]['collision'], lambda tile: tile != WALL
    assert ice.move(grid, 8, 6, (7, 0), 'left', enter, frozenset(), frozenset({(3, 2)})) == (0, 0)
    assert ice.move(grid, 8, 6, (7, 0), 'left', enter, frozenset({(2, 0)}), frozenset({(3, 2)})) == (3, 0)
    assert ice.move(grid, 8, 6, (3, 0), 'down', enter, frozenset(), frozenset({(3, 2)})) == (3, 2)
    assert ice.move(grid, 8, 6, (0, 0), 'up', enter, frozenset(), frozenset()) is None


def test_the_region_graph_knows_an_unreachable_door_until_a_stopper_appears():
    data = synthetic()
    navigator = Navigator(data)
    start = snapshot(7, 0)
    assert navigator.regions.route(start, ROOM, [(3, 2)]) is None
    navigator.regions.observe_solids(ROOM, {(2, 0)})
    assert navigator.regions.route(start, ROOM, [(3, 2)]) is not None
    navigator.regions.observe_solids(ROOM, set())
    assert navigator.regions.route(start, ROOM, [(3, 2)]) is None


def test_the_step_planner_slides_the_way_the_game_does():
    navigator = Navigator(synthetic())
    navigator.regions.observe_solids(ROOM, {(2, 0)})
    assert navigator.local(snapshot(7, 0), [(3, 2)]) == ['left', 'down']
    navigator.regions.observe_solids(ROOM, set())
    assert navigator.local(snapshot(7, 0), [(3, 2)]) is None


def test_passing_over_a_target_does_not_stop_the_slide():
    navigator = Navigator(synthetic())
    # (4, 0) lies on the way along the top row. A slide cannot end there without a stopper.
    assert navigator.local(snapshot(7, 0), [(4, 0)]) is None


def test_a_warp_event_on_plain_ice_is_not_a_wall():
    data = synthetic()
    data.maps[ROOM]['warps'].append(dict(x=4, y=0, map=HALL, warp=1))
    navigator = Navigator(data)
    assert navigator.local(snapshot(7, 0), [(0, 0)]) == ['left']


def test_the_offline_check_matches_the_region_graph():
    data = synthetic()
    assert (3, 2) not in reachable(data, ROOM, (7, 0))
    assert (3, 2) in reachable(data, ROOM, (7, 0), {(2, 0)})


def test_exploring_leaves_by_the_way_out_the_region_graph_offers():
    navigator = Navigator(synthetic())
    assert navigator.explore(snapshot(0, 0)) == ['right']


def test_exploring_a_pocket_with_no_exit_offers_no_move():
    pocket = synthetic()
    pocket.maps[ROOM]['warps'] = [dict(x=3, y=2, map=HALL, warp=1)]
    assert Navigator(pocket).explore(snapshot(0, 0)) is None


def test_a_policy_with_no_route_waits_then_asks_for_a_reload():
    pocket = synthetic()
    pocket.maps[ROOM]['warps'] = [dict(x=3, y=2, map=HALL, warp=1)]
    policy = Policy.__new__(Policy)
    policy.nav, policy.stranded, policy.unreachable_waits = Navigator(pocket), 0, 0
    policy.goal = SimpleNamespace(label='Reach the far door')
    failures = []
    policy.fail = failures.append
    where = SimpleNamespace(**vars(snapshot(0, 0)), map_name='Test Ice Room')
    for _ in range(Policy.STRANDED_LIMIT - 1):
        assert policy.stranded_action(where, None, False).button is None
    assert not failures
    policy.stranded_action(where, None, False)
    assert failures == ['no route to Reach the far door from Test Ice Room'] and policy.stranded == 0


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real(request):
    cartridges, directory = os.environ.get('GEN2_CARTRIDGE_DIR'), os.environ.get('GEN2_DATA_DIR')
    if not cartridges or not directory:
        pytest.skip('Set GEN2_CARTRIDGE_DIR and GEN2_DATA_DIR to local Gen II files')
    return GameData.load(directory, request.param)


def test_every_ice_map_can_be_crossed_once_its_puzzle_is_solved(real):
    """The Ice Path's far exits are only reachable when the boulders sit on the lower floor."""
    ids = {entry['constant']: mid for mid, entry in real.maps.items()}
    mahogany, blackthorn = ids['ICE_PATH_B2F_MAHOGANY_SIDE'], ids['ICE_PATH_B2F_BLACKTHORN_SIDE']
    entry = real.maps[mahogany]
    landing, exit_door = (17, 1), (9, 11)
    boulders = {(obj['x'], obj['y']) for obj in entry['objects'] if obj['sprite'] == 'SPRITE_BOULDER'}
    assert exit_door not in reachable(real, mahogany, landing)
    assert exit_door in reachable(real, mahogany, landing, boulders)
    assert real.maps[blackthorn]['warps']


def test_the_pocket_beside_the_ice_path_exit_routes_back_out(real):
    ids = {entry['constant']: mid for mid, entry in real.maps.items()}
    mahogany, upper = ids['ICE_PATH_B2F_MAHOGANY_SIDE'], ids['ICE_PATH_B1F']
    navigator = Navigator(real)
    navigator.regions.observe_solids(mahogany, set())
    route = navigator.regions.route(snapshot(17, 1, mahogany), upper, [(17, 3)])
    assert route is not None
