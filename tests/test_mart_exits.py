import pytest

from pokesim.policies.navigation import Navigator
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
