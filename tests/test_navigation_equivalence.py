"""Navigation caches must preserve ordered graph semantics and mutation behavior."""
from copy import deepcopy
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from pokesim.policies import navigation as navigation

ROOM, FIELD, LIFT, COAST = 10001, 10002, 10003, 10004
PUBLIC_STATE = (
    'visits', 'edges', 'blocked', 'failures', 'attempt', 'last_pos', 'path', 'target',
    'use_world', 'cleared_objects', 'tile_overrides', 'can_surf', 'can_cut',
    'story_blocks', 'closed_passages', 'live_map', 'live_positions',
)


@pytest.fixture
def terrain(monkeypatch):
    def world(symbol, width, height, tileset='OVERWORLD'):
        return {'symbol': symbol, 'width': width, 'height': height, 'tileset': tileset,
            'tiles': [[0 for _ in range(width)] for _ in range(height)], 'passable': [0, 7, 44],
            'warps': [], 'connections': [], 'objects': [], 'inactive_warps': [],
            'opened_tiles': [], 'locked_doors': [], 'forced_moves': []}
    worlds = {
        ROOM: world('TEST_ROOM', 5, 5, 'MART'),
        FIELD: world('TEST_FIELD', 7, 6),
        LIFT: world('TEST_LIFT', 3, 3),
        COAST: world('TEST_COAST', 3, 6),
    }
    worlds[ROOM]['warps'] = [[1, 4, FIELD, 0]]
    worlds[FIELD]['warps'] = [[2, 2, ROOM, 0], [4, 2, LIFT, 0]]
    worlds[LIFT]['warps'] = [[1, 1, FIELD, 1]]
    worlds[FIELD]['connections'] = [['east', COAST, 0]]
    worlds[FIELD]['objects'] = [[1, 1, 'SPRITE_SCIENTIST', 'STAY', 'TEST_BLOCKER'],
        [5, 2, 'SPRITE_POKE_BALL', 'STAY', 'TEST_ITEM'], [0, 4, 'SPRITE_NPC', 'WALK', 'TEST_ROAMER']]
    worlds[FIELD]['tiles'][0][3] = 9
    worlds[FIELD]['tiles'][1][3] = 0x3d
    worlds[FIELD]['tiles'][1][5] = 7
    worlds[FIELD]['tiles'][3][3] = 44
    worlds[FIELD]['tiles'][4][3] = 55
    worlds[COAST]['tiles'][1][0] = 0x14
    worlds[FIELD]['opened_tiles'] = [['TEST_GATE_OPEN', 3, 0, 0]]
    worlds[FIELD]['locked_doors'] = [[4, 4, 'TEST_DOOR_OPEN']]
    mapping = {**navigation.MAPS, 'TEST_ROOM': ROOM, 'TEST_FIELD': FIELD,
               'TEST_LIFT': LIFT, 'TEST_COAST': COAST}
    values = {'WORLD': worlds, 'MAPS': mapping, 'OPTIONAL_LIFTS': {LIFT},
        'FORCED': {(FIELD, 4, 4): (FIELD, 5, 4)}, 'LEDGES': {('down', 44, 55)},
        'PAIR_COLLISIONS': {('OVERWORLD', 0, 7)},
        'DATA': {**navigation.DATA, 'toggle_objects': [[FIELD, 0]]},
        'event_set': lambda flags, name: name in flags}
    for name, value in values.items():
        monkeypatch.setattr(navigation, name, value)
    return values


def clone(nav, cls=None):
    other = (cls or navigation.Navigator)()
    for field in PUBLIC_STATE:
        setattr(other, field, deepcopy(getattr(nav, field)))
    return other


def positions(worlds):
    return [(m, x, y) for m, world in worlds.items()
            for y in range(world['height']) for x in range(world['width'])]


def assert_graph_parity(nav, worlds, frame, cls=None):
    reference = clone(nav, cls)
    cached = nav._search_neighbors(frame)
    for position in positions(worlds):
        expected = list(reference.neighbors(position, frame))
        assert list(nav.neighbors(position, frame)) == expected, position
        assert list(cached(position)) == expected, position
        assert list(cached(position)) == expected, position


def assert_route_parity(nav, frame, cls=None):
    journeys = [((FIELD, 0, 0), [(ROOM, 3, 2)]), ((ROOM, 2, 4), [(FIELD, 6, 5)]),
        ((FIELD, 0, 3), [(COAST, 2, 3)]), ((FIELD, 5, 5), [(LIFT, 1, 1)]),
        ((COAST, 2, 5), [(FIELD, 0, 0)]), ((FIELD, 0, 0), [(FIELD, 2, 0), (FIELD, 0, 2)])]
    for source, goals in journeys:
        reference = clone(nav, cls)
        assert nav.route(source, goals, frame) == reference.route(source, goals, frame)
        assert list(nav.path) == list(reference.path)
        # A warm lookup and an advanced path position must preserve tie breaking.
        reference = clone(nav, cls)
        assert nav.route(source, goals, frame) == reference.route(source, goals, frame)
        assert list(nav.path) == list(reference.path)
        if nav.path:
            advanced = nav.path[0][2]
            reference = clone(nav, cls)
            assert nav.route(advanced, goals, frame) == reference.route(advanced, goals, frame)
            assert list(nav.path) == list(reference.path)


def assert_distance_parity(nav, frame, cls=None):
    for source in ((ROOM, 0, 0), (FIELD, 0, 0), (COAST, 1, 1)):
        for limit in (0, 1, 7, 60000):
            reference = clone(nav, cls)
            actual = nav.distance_lookup(source, frame, limit)
            expected = reference.distance_lookup(source, frame, limit)
            for goals in ([], [source], [(ROOM, 3, 2)], [(FIELD, 6, 5)],
                          [(LIFT, 1, 1)], [(COAST, 2, 3)], [(FIELD, 0, 1), (ROOM, 0, 0)]):
                assert actual(goals) == expected(goals), (source, limit, goals)


def mutations(nav):
    yield 'surf', lambda: setattr(nav, 'can_surf', True)
    yield 'cut', lambda: setattr(nav, 'can_cut', True)
    yield 'story block add', lambda: nav.story_blocks.add((FIELD, 2, 0))
    yield 'story block remove', lambda: nav.story_blocks.clear()
    yield 'tile override add', lambda: nav.tile_overrides.update({(FIELD, 3, 0): 0})
    yield 'tile override replace', lambda: nav.tile_overrides.update({(FIELD, 3, 0): 9})
    yield 'tile override remove', lambda: nav.tile_overrides.clear()
    yield 'closed passage add', lambda: nav.closed_passages.add((FIELD, 2, 1))
    yield 'closed passage remove', lambda: nav.closed_passages.clear()
    yield 'clear static object', lambda: nav.cleared_objects.add((FIELD, 1, 1))
    yield 'restore static object', lambda: nav.cleared_objects.clear()
    yield 'live map', lambda: setattr(nav, 'live_map', FIELD)
    yield 'live positions', lambda: nav.live_positions.append((2, 1))
    yield 'live position mutate', lambda: nav.live_positions.__setitem__(0, (2, 0))
    yield 'live map change', lambda: setattr(nav, 'live_map', ROOM)
    yield 'observed edge add', lambda: nav.edges.setdefault((FIELD, 0, 0), {}).update({'right': (FIELD, 6, 5)})
    yield 'nested observed edge edit', lambda: nav.edges[(FIELD, 0, 0)].update({'right': (FIELD, 2, 0)})
    yield 'observed edge delete', lambda: nav.edges[(FIELD, 0, 0)].clear()
    yield 'block add', lambda: nav.blocked.update({((FIELD, 0, 0), 'down'): 100})
    yield 'block replacement', lambda: nav.blocked.update({((FIELD, 0, 0), 'down'): 40})
    yield 'block clear', lambda: nav.blocked.clear()
    yield 'geometry off', lambda: setattr(nav, 'use_world', False)
    yield 'geometry on', lambda: setattr(nav, 'use_world', True)
    yield 'surf off', lambda: setattr(nav, 'can_surf', False)
    yield 'cut off', lambda: setattr(nav, 'can_cut', False)


def test_warm_neighbors_and_routes_match_fresh_state_after_mutations(terrain):
    nav = navigation.Navigator()
    assert_graph_parity(nav, terrain['WORLD'], 20)
    assert_route_parity(nav, 20)
    for label, mutate in mutations(nav):
        mutate()
        try:
            assert_graph_parity(nav, terrain['WORLD'], 20)
            assert_route_parity(nav, 20)
            assert_distance_parity(nav, 20)
        except AssertionError as error:
            raise AssertionError('Navigation changed after ' + label) from error


def test_directed_exit_warp_and_optional_lift_order(terrain):
    nav = navigation.Navigator()
    lateral = list(nav.neighbors((ROOM, 2, 4), 0))
    assert ('left', (ROOM, 1, 4)) in lateral
    assert ('left', (FIELD, 2, 2)) not in lateral
    assert ('down', (FIELD, 2, 2)) in list(nav.neighbors((ROOM, 1, 4), 0))
    assert ('right', (LIFT, 1, 1)) not in list(nav.neighbors((FIELD, 3, 2), 0))
    nav.edges[(FIELD, 3, 2)] = {'right': (LIFT, 1, 1)}
    assert all(direction != 'right' for direction, _ in nav.neighbors((FIELD, 3, 2), 0))
    nav.edges[(FIELD, 2, 1)] = {'down': (FIELD, 2, 2)}
    assert ('down', (ROOM, 1, 4)) in list(nav.neighbors((FIELD, 2, 1), 0))
    nav.edges[(ROOM, 1, 4)] = {'down': (FIELD, 1, 4)}
    assert ('down', (FIELD, 2, 2)) in list(nav.neighbors((ROOM, 1, 4), 0))


def test_ladders_and_observed_directions_do_not_gain_inverse_edges(terrain):
    nav = navigation.Navigator()
    nav.use_world = False
    nav.edges[(FIELD, 0, 0)] = {'up': (ROOM, 1, 4), 'down': (FIELD, 0, 1), 'right': (COAST, 0, 0)}
    assert list(nav.neighbors((FIELD, 0, 0), 0)) == [
        ('down', (FIELD, 0, 1)), ('right', (COAST, 0, 0)), ('up', (ROOM, 1, 4))]
    assert list(nav.neighbors((ROOM, 1, 4), 0)) == []
    nav.use_world = True
    nav.story_blocks.add((COAST, 0, 0))
    assert all(direction != 'right' for direction, _ in nav.neighbors((FIELD, 0, 0), 0))


def test_block_expiration_changes_routes_without_mutating_the_block_map(terrain):
    nav = navigation.Navigator()
    source = (FIELD, 0, 0)
    nav.blocked[(source, 'down')] = 40
    for frame in (0, 39, 40, 41, 0, 40):
        values = list(nav.neighbors(source, frame))
        assert (('down', (FIELD, 0, 1)) in values) == (frame >= 40)
        assert_graph_parity(nav, terrain['WORLD'], frame)
        assert_route_parity(nav, frame)


def test_capabilities_and_static_objects_change_actual_edges(terrain):
    nav = navigation.Navigator()
    assert ('right', (COAST, 0, 1)) not in nav.neighbors((FIELD, 6, 1), 0)
    nav.can_surf = True
    assert ('right', (COAST, 0, 1)) in nav.neighbors((FIELD, 6, 1), 0)
    assert ('right', (FIELD, 3, 1)) not in nav.neighbors((FIELD, 2, 1), 0)
    nav.can_cut = True
    assert ('right', (FIELD, 3, 1)) in nav.neighbors((FIELD, 2, 1), 0)
    assert ('down', (FIELD, 1, 1)) not in nav.neighbors((FIELD, 1, 0), 0)
    nav.live_map, nav.live_positions = FIELD, [(2, 1)]
    assert ('down', (FIELD, 1, 1)) in nav.neighbors((FIELD, 1, 0), 0)
    assert ('down', (FIELD, 2, 1)) not in nav.neighbors((FIELD, 2, 0), 0)
    nav.cleared_objects.add((FIELD, 1, 1))
    assert ('down', (FIELD, 2, 1)) in nav.neighbors((FIELD, 2, 0), 0)
    assert ('right', (FIELD, 5, 2)) in nav.neighbors((FIELD, 4, 2), 0)


def test_geometry_mutation_and_world_replacement_never_return_stale_neighbors(terrain, monkeypatch):
    nav = navigation.Navigator()
    source = (ROOM, 0, 0)
    assert ('right', (ROOM, 1, 0)) in nav.neighbors(source, 0)
    terrain['WORLD'][ROOM]['tiles'][0][1] = 9
    assert ('right', (ROOM, 1, 0)) not in nav.neighbors(source, 0)
    replacement = deepcopy(terrain['WORLD'])
    replacement[ROOM]['tiles'][0][1] = 0
    monkeypatch.setattr(navigation, 'WORLD', replacement)
    assert ('right', (ROOM, 1, 0)) in nav.neighbors(source, 0)
    assert_graph_parity(nav, replacement, 0)


def test_story_updates_and_restore_invalidate_cached_terrain(terrain):
    nav = navigation.Navigator()
    snapshot = SimpleNamespace(map=FIELD, party=[SimpleNamespace(moves=())], badges=0,
        event_flags=frozenset(), hidden_objects=b'\0', saffron_open=True, items=[])
    nav.update_story(snapshot)
    assert ('right', (FIELD, 3, 0)) not in nav.neighbors((FIELD, 2, 0), 0)
    snapshot.event_flags = frozenset({'TEST_GATE_OPEN', 'TEST_DOOR_OPEN'})
    snapshot.hidden_objects = b'\1'
    snapshot.party = [SimpleNamespace(moves=(15, 57, 70))]
    snapshot.badges = 18
    nav.update_story(snapshot)
    assert ('right', (FIELD, 3, 0)) in nav.neighbors((FIELD, 2, 0), 0)
    assert nav.can_cut and nav.can_surf
    assert (FIELD, 1, 1) in nav.cleared_objects
    assert_graph_parity(nav, terrain['WORLD'], 0)
    nav.edges[(ROOM, 0, 0)] = {'right': (ROOM, 4, 4)}
    nav.blocked[((ROOM, 0, 0), 'right')] = 100
    saved = nav.state_dict()
    nav.restore()
    assert ('right', (ROOM, 4, 4)) in nav.neighbors((ROOM, 0, 0), 0)
    nav.edges[(ROOM, 0, 0)]['right'] = (COAST, 2, 3)
    nav.load_state_dict(saved)
    assert ('right', (ROOM, 4, 4)) in nav.neighbors((ROOM, 0, 0), 0)
    assert_graph_parity(nav, terrain['WORLD'], 0)


def test_observation_failures_and_new_edges_invalidate_routes(terrain):
    nav = navigation.Navigator()
    source = (ROOM, 0, 0)
    for issued, observed in ((0, 21), (30, 51)):
        nav.issued(source, 'right', issued)
        nav.observe(source, observed)
    assert all(direction != 'right' for direction, _ in nav.neighbors(source, 51))
    nav.issued(source, 'right', 60)
    nav.observe((ROOM, 2, 0), 81)
    assert ('right', (ROOM, 2, 0)) in nav.neighbors(source, 81)
    assert not nav.blocked
    assert_route_parity(nav, 81)


def test_pre_optimization_baseline_qualification(terrain):
    """Optional local oracle, supplied outside the repository during optimization."""
    path = os.environ.get('POKESIM_NAVIGATION_BASELINE')
    if not path:
        pytest.skip('Set POKESIM_NAVIGATION_BASELINE to the pre-change module for differential qualification')
    baseline = ModuleType('pokesim.policies._baseline_navigation')
    baseline.__package__ = 'pokesim.policies'
    exec(compile(Path(path).read_text(), path, 'exec'), baseline.__dict__)
    baseline.__dict__.update(terrain)
    nav = navigation.Navigator()
    for label, mutate in [('initial', lambda: None), *list(mutations(nav))]:
        mutate()
        for frame in (0, 20, 40, 101):
            try:
                assert_graph_parity(nav, terrain['WORLD'], frame, baseline.Navigator)
                assert_route_parity(nav, frame, baseline.Navigator)
                assert_distance_parity(nav, frame, baseline.Navigator)
            except AssertionError as error:
                raise AssertionError('Pre-change baseline mismatch after ' + label) from error


def test_cached_geometry_mutations_preserve_ordered_edges_and_routes(terrain):
    nav = navigation.Navigator()
    worlds = terrain['WORLD']
    edits = [
        lambda: worlds[ROOM]['tiles'][0].__setitem__(1, 9),
        lambda: worlds[ROOM]['passable'].append(9),
        lambda: worlds[FIELD]['objects'][0].__setitem__(0, 2),
        lambda: worlds[FIELD]['objects'][0].__setitem__(3, 'WALK'),
        lambda: worlds[FIELD]['warps'][0].__setitem__(0, 3),
        lambda: worlds[FIELD]['warps'].append([3, 2, COAST, 0]),
        lambda: worlds[COAST]['warps'].append([1, 1, FIELD, 0]),
        lambda: worlds[FIELD]['inactive_warps'].append([3, 2]),
        lambda: worlds[FIELD]['inactive_warps'].clear(),
        lambda: worlds[FIELD]['connections'][0].__setitem__(2, 1),
        lambda: worlds[ROOM].__setitem__('tileset', 'OVERWORLD'),
        lambda: worlds[ROOM]['warps'][0].__setitem__(2, -1),
        lambda: terrain['FORCED'].update({(FIELD, 4, 4): (COAST, 2, 2)}),
        lambda: terrain['OPTIONAL_LIFTS'].clear(),
        lambda: terrain['LEDGES'].clear(),
        lambda: terrain['PAIR_COLLISIONS'].clear(),
    ]
    assert_graph_parity(nav, worlds, 0)
    for edit in edits:
        edit()
        assert_graph_parity(nav, worlds, 0)
        assert_route_parity(nav, 0)
        assert_distance_parity(nav, 0)


def test_observed_doorway_geometry_stays_current_when_inference_disabled(terrain):
    nav = navigation.Navigator()
    nav.use_world = False
    source = (FIELD, 2, 1)
    nav.edges[source] = {'down': (FIELD, 2, 2)}
    assert nav._search_neighbors(0)(source) == (('down', (ROOM, 1, 4)),)
    terrain['WORLD'][ROOM]['warps'][0][:2] = [3, 4]
    assert nav._search_neighbors(0)(source) == (('down', (ROOM, 3, 4)),)
    assert_graph_parity(nav, terrain['WORLD'], 0)


def test_live_memory_updates_invalidate_cached_npc_positions(terrain):
    nav = navigation.Navigator()
    assert_graph_parity(nav, terrain['WORLD'], 0)
    memory = bytearray(65536)
    memory[0xC215], memory[0xC214] = 6, 5
    nav.update_live(SimpleNamespace(map=FIELD), memory)
    assert ('down', (FIELD, 2, 1)) not in nav._search_neighbors(0)((FIELD, 2, 0))
    memory[0xC215], memory[0xC214] = 7, 6
    nav.update_live(SimpleNamespace(map=FIELD), memory)
    assert ('down', (FIELD, 2, 1)) in nav._search_neighbors(0)((FIELD, 2, 0))
    assert_graph_parity(nav, terrain['WORLD'], 0)
