"""Warp carpets are ground to walk over. They only warp when walked off in their own direction."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.navigation import Navigator
from pokesim.gen2.routes import Regions


def gate():
    """A gate with a corner behind its counter that opens only onto the left carpet, as Route 36's does."""
    maps = {
        1: {'width': 4, 'height': 4, 'constant': 'GATE',
            'collision': [0, 0, 7, 0,
                          0, 7, 7, 0,
                          0x76, 0, 0, 0,
                          0x76, 0, 0, 0x76],
            'connections': [], 'objects': [],
            'warps': [{'x': 0, 'y': 2, 'map': 2, 'warp': 1}, {'x': 0, 'y': 3, 'map': 2, 'warp': 1},
                      {'x': 3, 'y': 3, 'map': 2, 'warp': 1}]},
        2: {'width': 3, 'height': 1, 'constant': 'PARK', 'collision': [0, 0, 0x7E],
            'connections': [], 'objects': [], 'warps': [{'x': 2, 'y': 0, 'map': 1, 'warp': 1}]},
    }
    permissions = [0] * 256
    permissions[7] = 15
    return SimpleNamespace(maps=maps, permissions=permissions)


def here(x, y, mid=1):
    return SimpleNamespace(map=mid, x=x, y=y, objects=(), badges=0, party=(), event_flags=b'', items=())


def test_the_corner_behind_the_counter_is_joined_to_the_room_by_the_carpet():
    regions = Regions(gate())
    labels = regions.regions(1, False, False)
    assert labels[0, 0] == labels[0, 2] == labels[1, 2] == labels[2, 2]
    route = regions.route(here(0, 0), 1, [(3, 0)])
    assert route == []
    # The carpet still leads into the park.
    assert regions.route(here(0, 0), 2, [(0, 0)])[0][3] == 'warp'


def test_a_walk_crosses_a_carpet_without_walking_off_it_the_warp_way():
    nav = Navigator(gate())
    path = nav.local(here(0, 0), [(3, 0)])
    assert path == ['down', 'down', 'right', 'right', 'right', 'up', 'up']
    assert nav.local(here(1, 2), [(0, 1)]) == ['left', 'up']


def test_an_inner_carpet_is_never_walked_off_its_warp_way():
    nav = Navigator(gate())
    # The carpet at (3, 3) warps when walked left from, so reaching (2, 3) goes around it.
    assert nav.local(here(3, 3), [(2, 3)]) == ['up', 'left', 'down']


def test_a_carpet_tile_with_no_warp_is_plain_ground():
    # Olivine Port's gangway has a down carpet tile with no warp on it, and the pier past it looked
    # cut off, so boarding the S.S. Aqua walked back and forth at the port entrance (#241).
    data = gate()
    data.maps[1]['warps'] = [warp for warp in data.maps[1]['warps'] if (warp['x'], warp['y']) != (3, 3)]
    nav = Navigator(data)
    assert nav.local(here(3, 3), [(2, 3)]) == ['left']
    labels = Regions(data).regions(1, False, False)
    assert labels[3, 3] == labels[2, 3]


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, request.param)


def test_the_route_36_gate_officer_corner_has_a_way_out(real_data):
    # The live Silver run stood at (3, 1) behind the counter after a Bug-Catching Contest and every
    # route from there, to training or to a Pokémon Center, came back empty.
    gate_map = real_data.map_ids['ROUTE_36_NATIONAL_PARK_GATE']
    regions = Regions(real_data)
    corner = here(3, 1, gate_map)
    assert regions.route(corner, real_data.map_ids['ROUTE_36'], [(19, 8)]) is not None
    assert regions.route(corner, real_data.map_ids['NATIONAL_PARK'], [(32, 18)]) is not None
    assert Navigator(real_data).local(corner, [(9, 4), (9, 5)]) is not None


def test_the_olivine_port_pier_reaches_the_gangway(real_data):
    port = real_data.map_ids['OLIVINE_PORT']
    entrance = here(11, 8, port)
    assert Navigator(real_data).local(entrance, [(7, 22)]) is not None
    labels = Regions(real_data).regions(port, False, False)
    assert labels[11, 8] == labels[7, 22]
