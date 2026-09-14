from pokesim.policies.navigation import Navigator
from pokesim.strategy_data import MAPS, WORLD


def test_remembered_steps_respect_current_boulder_positions():
    m = MAPS['VICTORY_ROAD_3F']
    source, target = (m, 23, 10), (m, 24, 10)
    nav = Navigator()
    nav.edges = {source: {'right': target}}
    nav.live_map = m
    nav.live_positions = [(o[0], o[1]) for o in WORLD[m]['objects']]
    index = next(i for i, o in enumerate(WORLD[m]['objects']) if o[4].endswith('BOULDER3'))
    assert nav.live_positions[index] == (24, 10)
    assert ('right', target) not in nav.neighbors(source, 0)
    nav.live_positions[index] = (22, 10)
    assert ('right', target) in nav.neighbors(source, 0)


def test_hidden_objects_no_longer_block_remembered_steps():
    m = MAPS['VICTORY_ROAD_3F']
    source, target = (m, 23, 10), (m, 24, 10)
    nav = Navigator()
    nav.live_map = m
    nav.live_positions = [(o[0], o[1]) for o in WORLD[m]['objects']]
    nav.edges = {source: {'right': target}}
    assert ('right', target) not in nav.neighbors(source, 0)
    nav.cleared_objects.add(target)
    assert ('right', target) in nav.neighbors(source, 0)



def test_unknown_remote_boulder_position_does_not_replace_an_observed_route():
    m = MAPS['VICTORY_ROAD_3F']
    source, target = (m, 23, 10), (m, 24, 10)
    nav = Navigator()
    nav.edges = {source: {'right': target}}
    nav.live_map = MAPS['VICTORY_ROAD_2F']
    assert ('right', target) in nav.neighbors(source, 0)
    nav.live_map = m
    nav.live_positions = [(o[0], o[1]) for o in WORLD[m]['objects']]
    assert ('right', target) not in nav.neighbors(source, 0)
