"""Reused route searches answer exactly as a fresh breadth-first search would."""
from collections import deque
import os
import random
from types import SimpleNamespace

import pytest

from pokesim.gen2.navigation import Navigator
from pokesim.gen2.routes import Regions


def fresh_regions_route(regions, snapshot, target_map, targets, *, cut=False, surf=False, excluded=()):
    """The search as it was before searches were kept between calls."""
    starts = [(snapshot.map, region)
              for region in regions.memberships(snapshot.map, (snapshot.x, snapshot.y), cut, surf, arrive=True)]
    goals = {(target_map, region) for point in targets for region in regions.memberships(target_map, point, cut, surf)}
    queue = deque(starts)
    paths = {start: [] for start in starts}
    while queue:
        node = queue.popleft()
        if node in goals:
            return paths[node]
        for destination, points, kind in regions.edges(node, cut, surf):
            if destination in paths or (node, destination) in excluded:
                continue
            paths[destination] = paths[node] + [(node, destination, points, kind)]
            queue.append(destination)
    return None


def fresh_map_route(nav, start, target, excluded=()):
    queue = deque([start])
    paths = {start: []}
    while queue:
        mid = queue.popleft()
        if mid == target:
            return paths[mid]
        for destination, points, kind in nav.edges(mid):
            if destination not in paths and destination not in excluded and (mid, destination) not in nav.failed_edges:
                paths[destination] = paths[mid] + [(mid, destination, points, kind)]
                queue.append(destination)
    return None


def corridor():
    """Two rooms joined by a pair of doors, with a wall tile that can close the near door."""
    maps = {
        1: {'width': 5, 'height': 3, 'collision': [0, 0, 7, 0, 0, 0, 0x72, 7, 0x72, 0, 0, 0, 7, 0, 0],
            'connections': [], 'objects': [], 'warps': [{'x': 1, 'y': 1, 'map': 2, 'warp': 1},
                                                        {'x': 3, 'y': 1, 'map': 2, 'warp': 2}]},
        2: {'width': 3, 'height': 3, 'collision': [0, 0, 0, 0x72, 0, 0x72, 0, 0, 0],
            'connections': [], 'objects': [], 'warps': [{'x': 0, 'y': 1, 'map': 1, 'warp': 1},
                                                        {'x': 2, 'y': 1, 'map': 1, 'warp': 2}]},
    }
    permissions = [0] * 256
    permissions[7] = 15
    return SimpleNamespace(maps=maps, permissions=permissions)


def test_a_kept_search_follows_live_collision_changes():
    regions = Regions(corridor())
    here = SimpleNamespace(map=1, x=0, y=1)
    first = regions.route(here, 1, [(4, 1)])
    assert [edge[1][0] for edge in first] == [2, 1]
    first.clear()
    assert regions.route(here, 1, [(4, 1)]) == fresh_regions_route(regions, here, 1, [(4, 1)])
    closed = list(regions.data.maps[1]['collision'])
    closed[1 * 5 + 1] = 7
    regions.observe(1, closed)
    assert regions.route(here, 1, [(4, 1)]) is None is fresh_regions_route(regions, here, 1, [(4, 1)])
    regions.observe(1, list(regions.data.maps[1]['collision']))
    assert regions.route(here, 1, [(4, 1)]) == fresh_regions_route(regions, here, 1, [(4, 1)])


def test_excluded_edges_get_their_own_search():
    regions = Regions(corridor())
    here = SimpleNamespace(map=1, x=0, y=1)
    route = regions.route(here, 1, [(4, 1)])
    excluded = {route[0][:2]: 1}
    assert regions.route(here, 1, [(4, 1)], excluded=excluded) is None
    assert regions.route(here, 1, [(4, 1)]) == route


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, request.param)


def test_kept_searches_match_fresh_searches_across_the_world(real_data):
    rng = random.Random(5)
    nav = Navigator(real_data)
    maps = sorted(real_data.maps)
    places = []
    for mid in maps:
        entry = real_data.maps[mid]
        open_tiles = [(x, y) for y in range(entry['height']) for x in range(entry['width'])
                      if nav.passable(entry['collision'][y * entry['width'] + x])]
        places += [(mid, point) for point in rng.sample(open_tiles, min(2, len(open_tiles)))]
    starts = rng.sample(places, 4)
    for start_map, (x, y) in starts:
        here = SimpleNamespace(map=start_map, x=x, y=y)
        # Many targets from one place, in the order a policy step would ask, then again.
        for target_map, point in rng.sample(places, 12) * 2:
            for cut, surf in ((False, False), (True, True)):
                assert (nav.regions.route(here, target_map, [point], cut=cut, surf=surf)
                        == fresh_regions_route(nav.regions, here, target_map, [point], cut=cut, surf=surf))
            assert nav.route(start_map, target_map) == fresh_map_route(nav, start_map, target_map)


def test_kept_region_edges_follow_changes_to_the_maps_they_lead_into(real_data):
    regions = Regions(real_data)
    rng = random.Random(9)
    linked = [mid for mid, entry in sorted(real_data.maps.items()) if entry['connections'] and entry['warps']]

    def nodes(mid):
        return {(mid, region) for flags in ((False, False), (True, True))
                for region in set(regions.regions(mid, *flags).values())}

    def check(mids):
        for mid in mids:
            for node in nodes(mid):
                for flags in ((False, False), (True, True)):
                    kept = list(regions.edges(node, *flags))
                    assert kept == list(regions._edges(node, *flags))
                    # Each caller gets its own point lists to change.
                    for _, points, _ in kept:
                        points.append(None)
                    assert list(regions.edges(node, *flags)) == list(regions._edges(node, *flags))

    for mid in rng.sample(linked, 6):
        entry = real_data.maps[mid]
        neighbours = [row['map'] for row in entry['connections']] + [warp['map'] for warp in entry['warps']]
        check([mid])
        # Wall off every square of a neighbour, then of the map itself, and read the edges again.
        for changed in (neighbours[0], mid):
            regions.observe(changed, [7] * len(real_data.maps[changed]['collision']))
            check([mid, changed])
        regions.observe_rocks(mid, {1})
        check([mid])
