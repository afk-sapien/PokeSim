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
