import pytest

from pokesim.policies.navigation import DIRS, Navigator
from pokesim.strategy_data import MAPS, WORLD


@pytest.mark.parametrize('name', ['PEWTER_MART', 'VIRIDIAN_MART', 'CERULEAN_MART', 'PEWTER_POKECENTER'])
def test_exit_mat_sideways_steps_stay_inside_and_exit_points_down(name):
    m = MAPS[name]
    nav = Navigator()
    nav.edges[(m, 3, 7)] = {'right': (m, 4, 7)}
    nav.edges[(m, 4, 7)] = {'left': (m, 3, 7)}
    destination = nav._warp(m, WORLD[m]['warps'][0])
    for x, direction, other in ((3, 'right', 4), (4, 'left', 3)):
        start = (m, x, 7)
        neighbors = list(nav.neighbors(start, 0))
        assert (direction, (m, other, 7)) in neighbors
        assert (direction, destination) not in neighbors
        assert nav.route(start, [destination], 0) == 'down'


def test_old_exit_sample_with_indoor_coordinates_uses_real_outdoor_destination():
    m = MAPS['PEWTER_MART']
    nav = Navigator()
    source = (m, 4, 7)
    nav.edges[source] = {'down': (MAPS['PEWTER_CITY'], 4, 7)}
    destination = nav._warp(m, WORLD[m]['warps'][1])
    assert ('down', destination) in list(nav.neighbors(source, 0))
    assert ('down', (MAPS['PEWTER_CITY'], 4, 7)) not in list(nav.neighbors(source, 0))


def test_a_cave_mouth_on_the_map_edge_only_leaves_by_walking_outward():
    # Victory Road 2F has two exit squares stacked on its east edge. Stepping from one onto the
    # other stays inside, so a route that paces between them never reaches Route 23.
    m = MAPS['VICTORY_ROAD_2F']
    nav = Navigator()
    upper, lower = (m, 29, 7), (m, 29, 8)
    outside = nav._warp(m, WORLD[m]['warps'][1])
    assert outside[0] == MAPS['ROUTE_23']
    for start, sideways, other in ((upper, 'down', lower), (lower, 'up', upper)):
        neighbors = list(nav.neighbors(start, 0))
        assert ('right', outside) in neighbors
        assert (sideways, other) in neighbors and (sideways, outside) not in neighbors
        assert nav.route(start, [outside], 0) == 'right'


def test_ladders_on_a_map_edge_still_warp_when_stepped_on():
    m = MAPS['VICTORY_ROAD_2F']
    ladder = next(w for w in WORLD[m]['warps'] if w[2] != -1 and (w[0] in (0, WORLD[m]['width'] - 1) or w[1] in (0, WORLD[m]['height'] - 1)))
    nav = Navigator()
    assert all(nav._directed_warp(m, ladder, direction) == nav._warp(m, ladder) for direction in ('up', 'down', 'left', 'right'))


def test_a_route_gate_door_warps_only_while_facing_its_carpet():
    # Outdoors, a warp square whose own tile is not a door warps only while the player faces a carpet
    # tile. Route 7's east gate is entered walking left from (19, 10). The map file also lists (18, 9),
    # which faces no carpet, and a route that walked onto it paced there without entering.
    m = MAPS['ROUTE_7']
    nav = Navigator()
    warps = {tuple(warp[:2]): warp for warp in WORLD[m]['warps']}
    facing = {square: [d for d in DIRS if nav._directed_warp(m, warps[square], d)] for square in warps}
    assert facing == {(18, 9): [], (18, 10): ['left'], (11, 9): [], (11, 10): ['right'],
                      (5, 13): ['up', 'down', 'left', 'right']}
    gate = nav._warp(m, warps[(18, 10)])
    assert ('left', gate) in list(nav.neighbors((m, 19, 10), 0))
    assert ('left', (m, 18, 9)) in list(nav.neighbors((m, 19, 9), 0))
    assert gate not in [q for _, q in nav.neighbors((m, 18, 9), 0)]
