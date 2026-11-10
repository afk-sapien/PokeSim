"""The Gen II map audit passes on every game, and still catches the map facts behind #254 and #241, and a walk through Ilex Forest before Cut."""
import importlib.util
import os
from pathlib import Path

import pytest

from pokesim.gen2.navigation import Navigator
from pokesim.gen2.routes import CARPETS, Regions, walk_crossings

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('map_audit_tool', ROOT / 'tools' / 'map_audit.py')
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


@pytest.fixture(scope='module', params=tool.GAMES)
def game(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    data = GameData.load(directory, request.param)
    return request.param, data, tool.audit(data)


def test_every_allow_row_names_its_games_and_a_reason():
    for key, (games, reason) in tool.ALLOWED.items():
        assert games and games <= tool.EVERY, key
        assert reason.strip(), key


def test_every_finding_is_allowed_and_every_allow_row_is_found(game):
    name, _, findings = game
    new, stale = tool.problems(name, findings)
    assert new == {}
    assert stale == []


SEAMS = {
    ('seam', 'ROUTE_44', 'east', 'BLACKTHORN_CITY', 'pocket'),
    ('seam', 'BLACKTHORN_CITY', 'west', 'ROUTE_44', 'pocket'),
    ('seam', 'ROUTE_10_NORTH', 'south', 'ROUTE_10_SOUTH', 'pocket'),
    ('seam', 'ROUTE_10_SOUTH', 'north', 'ROUTE_10_NORTH', 'pocket'),
    ('seam', 'AZALEA_TOWN', 'west', 'ROUTE_34', 'no crossing'),
    ('seam', 'ROUTE_34', 'east', 'AZALEA_TOWN', 'no crossing'),
}


def test_a_router_that_counts_every_link_fails_on_the_seams(game):
    # The router counted Blackthorn one map from Route 44, so a healing trip walked into Ice Path
    # and stalled (#254). The walk router skips that link and five like it, and the audit must
    # name all six for a router that counts them again.
    _, data, findings = game
    assert not any(key[0] == 'seam' for key in findings)
    names = {mid: entry['constant'] for mid, entry in data.maps.items()}
    every = tool.check_seams(data, Regions(data), Navigator(data), names, walk=False)
    assert set(every) == SEAMS


def walker(data):
    """A walk between two maps by name, with the field moves given, as the names of the maps it enters."""
    ids = {entry['constant']: mid for mid, entry in data.maps.items()}
    names = {mid: entry['constant'] for mid, entry in data.maps.items()}
    navigator = Navigator(data)

    def walk(start, target, *moves):
        route = navigator.walk(tool.player(ids[start], moves), ids[target])
        return None if route is None else [names[step[1]] for step in route]
    return walk


def test_a_walk_goes_through_the_cave_or_forest_between_two_seam_maps(game):
    _, data, _ = game
    walk = walker(data)
    assert walk('ROUTE_44', 'BLACKTHORN_CITY') == ['ICE_PATH_1F', 'BLACKTHORN_CITY']
    assert walk('ROUTE_10_NORTH', 'ROUTE_10_SOUTH') == ['ROUTE_9', 'ROCK_TUNNEL_1F', 'ROUTE_10_SOUTH']
    assert walk('AZALEA_TOWN', 'ROUTE_34', 'cut') == [
        'ILEX_FOREST_AZALEA_GATE', 'ILEX_FOREST', 'ROUTE_34_ILEX_FOREST_GATE', 'ROUTE_34']
    assert walk('ROUTE_34', 'GOLDENROD_CITY') == ['GOLDENROD_CITY']


def test_a_walk_through_ilex_forest_needs_cut(game):
    # The tree in Ilex Forest splits its two gates, so before Cut the walk from Azalea Town to
    # Route 34 is not the four maps through the forest.
    _, data, findings = game
    assert not any(key[0] == 'crossing' for key in findings)
    ids = {entry['constant']: mid for mid, entry in data.maps.items()}
    forest = (ids['ILEX_FOREST_AZALEA_GATE'], ids['ILEX_FOREST'], ids['ROUTE_34_ILEX_FOREST_GATE'])
    assert walk_crossings(data)[forest] == (frozenset({'cut'}),)
    assert walk_crossings(data)[forest[::-1]] == (frozenset({'cut'}),)
    walk = walker(data)
    for moves in ((), ('surf',)):
        route = walk('AZALEA_TOWN', 'ROUTE_34', *moves)
        assert route is not None and 'ILEX_FOREST' not in route and len(route) > 4
        assert 'ILEX_FOREST' not in walk('ROUTE_34', 'AZALEA_TOWN', *moves)
    assert walk('ROUTE_34', 'AZALEA_TOWN', 'cut') == [
        'ROUTE_34_ILEX_FOREST_GATE', 'ILEX_FOREST', 'ILEX_FOREST_AZALEA_GATE', 'AZALEA_TOWN']


class FieldMovesIgnored(Navigator):
    """A navigator that walks as if the player had every field move, as walks did before they read them."""
    def walk(self, snapshot, target):
        return super().walk(tool.player(snapshot.map, ('cut', 'surf')), target)


def test_a_walk_that_ignores_field_moves_fails_the_crossing_check(game):
    _, data, _ = game
    names = {mid: entry['constant'] for mid, entry in data.maps.items()}
    found = tool.check_crossings(data, FieldMovesIgnored(data), names)
    forest = ('crossing', 'ILEX_FOREST_AZALEA_GATE', 'ILEX_FOREST', 'ROUTE_34_ILEX_FOREST_GATE')
    assert forest + ('no moves',) in found
    assert forest + ('surf',) in found
    assert not any(key[-1] == 'cut+surf' for key in found)


class CarpetDoors:
    """The game data with a warp on every carpet that has none, which is how routes read carpets before #244."""
    def __init__(self, data):
        self.data = data
        self.maps = {}
        for mid, entry in data.maps.items():
            width = entry['width']
            doors = {(warp['x'], warp['y']) for warp in entry['warps']}
            extra = [{'x': index % width, 'y': index // width, 'map': mid, 'warp': 1}
                     for index, tile in enumerate(entry['collision'])
                     if tile in CARPETS and (index % width, index // width) not in doors]
            self.maps[mid] = {**entry, 'warps': entry['warps'] + extra}

    def __getattr__(self, name):
        return getattr(self.data, name)


def test_a_carpet_read_as_a_door_cuts_off_the_olivine_port_pier(game):
    # The gangway carpet at (7, 17) has no warp. Read as a door, it split the pier from the gangway,
    # so boarding the S.S. Aqua walked back and forth at the port entrance (#241).
    _, data, findings = game
    assert not any(key[0] == 'carpet' for key in findings)
    view = CarpetDoors(data)
    names = {mid: entry['constant'] for mid, entry in data.maps.items()}
    before = tool.check_carpets(data, Regions(view), Navigator(view), names)
    assert ('carpet', 'OLIVINE_PORT', 7, 17, 'walled in') in before
