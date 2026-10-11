"""Fly still reaches a visited town when no walking route to it exists."""
from dataclasses import dataclass
import os
from types import SimpleNamespace

import pytest


@pytest.fixture(scope='module')
def crystal():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, 'crystal')


@dataclass(frozen=True)
class Spot:
    map: int
    x: int
    y: int
    badges: int
    party: tuple
    event_flags: bytes = b''


def test_a_returned_sudowoodo_on_route_36_leaves_fly_as_the_way_to_olivine(crystal):
    """A reopened Sudowoodo encounter blocks Route 36 again, which cuts every walking route from Route 29 to
    Ecruteak and Olivine. The Battle Tower trip then flew nowhere and gave up on "no route" once a second."""
    from pokesim.gen2.flight import shortcut
    from pokesim.gen2.menus import Fly
    from pokesim.gen2.navigation import Navigator
    from pokesim.gen2.world import travel_collision

    data = crystal
    ids = data.map_ids
    nav = Navigator(data)
    standing = SimpleNamespace(event=lambda name: name != 'EVENT_ROUTE_36_SUDOWOODO', items=())
    route_36 = ids['ROUTE_36']
    nav.regions.observe(route_36, travel_collision(data, standing, route_36, data.maps[route_36]['collision']))
    flyer = SimpleNamespace(egg=False, moves=(19, 0, 0, 0))
    surfer = SimpleNamespace(egg=False, moves=(57, 15, 0, 0))
    here = Spot(ids['ROUTE_29'], 27, 16, 0xFFFF, (surfer, flyer))
    target = ids['OLIVINE_POKECENTER_1F']
    policy = SimpleNamespace(data=data, nav=nav, goal=SimpleNamespace(x=5, y=6))
    assert nav.regions.route(here, target, [(5, 6)], cut=True, surf=True) is None

    mem = SimpleNamespace(read=lambda name, size: (2 ** 32 - 1).to_bytes(4, 'little'), memory=None)
    flight = shortcut(policy, here, mem, target)
    assert isinstance(flight, Fly) and flight.slot == 1
    assert flight.destination == ids['OLIVINE_CITY']


def test_fly_is_not_offered_when_no_visited_town_leads_there(crystal):
    from pokesim.gen2.flight import shortcut
    from pokesim.gen2.navigation import Navigator
    from pokesim.gen2.world import travel_collision

    data = crystal
    ids = data.map_ids
    nav = Navigator(data)
    standing = SimpleNamespace(event=lambda name: name != 'EVENT_ROUTE_36_SUDOWOODO', items=())
    route_36 = ids['ROUTE_36']
    nav.regions.observe(route_36, travel_collision(data, standing, route_36, data.maps[route_36]['collision']))
    here = Spot(ids['ROUTE_29'], 27, 16, 0xFFFF, (SimpleNamespace(egg=False, moves=(19, 0, 0, 0)),))
    policy = SimpleNamespace(data=data, nav=nav, goal=SimpleNamespace(x=5, y=6))
    # Only towns on the near side of the tree have been visited, so landing there does not help either.
    visited = sum(1 << point['spawn'] for point in data.fly_points
                  if point['map'] in (ids['NEW_BARK_TOWN'], ids['CHERRYGROVE_CITY'], ids['VIOLET_CITY']))
    mem = SimpleNamespace(read=lambda name, size: visited.to_bytes(4, 'little'), memory=None)
    assert shortcut(policy, here, mem, ids['OLIVINE_POKECENTER_1F']) is None


def walled(data):
    """A navigator with Route 36 blocked by a returned Sudowoodo."""
    from pokesim.gen2.navigation import Navigator
    from pokesim.gen2.world import travel_collision

    nav = Navigator(data)
    standing = SimpleNamespace(event=lambda name: name != 'EVENT_ROUTE_36_SUDOWOODO', items=())
    route_36 = data.map_ids['ROUTE_36']
    nav.regions.observe(route_36, travel_collision(data, standing, route_36, data.maps[route_36]['collision']))
    return nav


@pytest.mark.parametrize('inside, x, y, outdoors', [
    ('CHERRYGROVE_POKECENTER_1F', 3, 4, 'CHERRYGROVE_CITY'),
    ('DARK_CAVE_VIOLET_ENTRANCE', 3, 14, 'ROUTE_31'),
    ('ROUTE_29_ROUTE_46_GATE', 4, 4, 'ROUTE_46'),
])
def test_inside_with_no_walking_route_walks_out_before_flying(crystal, inside, x, y, outdoors):
    """Fly only works on town and route maps. Inside a Pokémon Center, a cave or a gate, the Tower trip
    used to see no route at all and gave up about 45 times a minute."""
    from pokesim.gen2.flight import outside, shortcut

    data = crystal
    ids = data.map_ids
    nav = walled(data)
    here = Spot(ids[inside], x, y, 0xFFFF, (SimpleNamespace(egg=False, moves=(19, 57, 15, 0)),))
    target = ids['OLIVINE_POKECENTER_1F']
    policy = SimpleNamespace(data=data, nav=nav, goal=SimpleNamespace(x=5, y=6))
    mem = SimpleNamespace(read=lambda name, size: (2 ** 32 - 1).to_bytes(4, 'little'), memory=None)
    assert nav.regions.route(here, target, [(5, 6)], cut=True, surf=True) is None
    assert shortcut(policy, here, mem, target) is None
    exit_point = outside(policy, here, mem, target)
    assert exit_point is not None
    if outdoors:
        assert exit_point[0] == ids[outdoors]
    assert data.maps[exit_point[0]]['environment'] in {'TOWN', 'ROUTE'}
    assert nav.regions.route(here, exit_point[0], [exit_point[1]], cut=True, surf=True) is not None
    landed = Spot(exit_point[0], *exit_point[1], 0xFFFF, here.party)
    assert shortcut(policy, landed, mem, target) is not None


def test_walking_out_is_left_alone_when_walking_works_or_fly_cannot(crystal):
    from pokesim.gen2.flight import outside

    data = crystal
    ids = data.map_ids
    nav = walled(data)
    mem = SimpleNamespace(read=lambda name, size: (2 ** 32 - 1).to_bytes(4, 'little'), memory=None)
    policy = SimpleNamespace(data=data, nav=nav, goal=SimpleNamespace(x=5, y=6))
    flying = (SimpleNamespace(egg=False, moves=(19, 0, 0, 0)),)
    center = Spot(ids['CHERRYGROVE_POKECENTER_1F'], 3, 4, 0xFFFF, flying)
    # Walking reaches Violet City, so nothing changes.
    assert outside(policy, center, mem, ids['VIOLET_POKECENTER_1F']) is None
    # Without the Fly badge, or with nobody that knows Fly, walking out would not help.
    assert outside(policy, Spot(center.map, 3, 4, 0xFFFF & ~32, flying), mem, ids['OLIVINE_POKECENTER_1F']) is None
    assert outside(policy, Spot(center.map, 3, 4, 0xFFFF, (SimpleNamespace(egg=False, moves=(57, 0, 0, 0)),)),
                   mem, ids['OLIVINE_POKECENTER_1F']) is None
