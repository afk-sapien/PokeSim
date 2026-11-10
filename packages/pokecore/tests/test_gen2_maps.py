"""Gen II collision decoding, ice slides and event map changes without a ROM.

Cartridge cases are in test_gen2_maps_roms.py.
"""
from types import SimpleNamespace

from pokecore import gen2
from pokecore.gen2 import maps

ICE, DOOR, WALL, FLOOR = 0x23, 0x72, 0x07, 0x00
ROOM = 1


def enter(tile):
    return tile != WALL


def ice_room():
    """An open 8x6 ice room with doors at (7, 0) and (3, 2)."""
    room = [ICE] * 48
    room[0 * 8 + 7] = DOOR
    room[2 * 8 + 3] = DOOR
    return room


def test_a_slide_runs_to_the_wall_a_stopper_or_a_door():
    grid = ice_room()
    assert maps.move(grid, 8, 6, (7, 0), 'left', enter, frozenset(), frozenset({(3, 2)})) == (0, 0)
    assert maps.move(grid, 8, 6, (7, 0), 'left', enter, frozenset({(2, 0)}), frozenset({(3, 2)})) == (3, 0)
    assert maps.move(grid, 8, 6, (3, 0), 'down', enter, frozenset(), frozenset({(3, 2)})) == (3, 2)
    assert maps.move(grid, 8, 6, (0, 0), 'up', enter, frozenset(), frozenset()) is None


def test_passing_over_a_tile_does_not_stop_the_slide():
    assert maps.move(ice_room(), 8, 6, (7, 0), 'left', enter) == (0, 0)


def test_a_slide_stops_before_a_wall_tile_and_off_ice():
    grid = ice_room()
    grid[0 * 8 + 2] = WALL
    assert maps.move(grid, 8, 6, (7, 0), 'left', enter) == (3, 0)
    grid[0 * 8 + 5] = FLOOR
    assert maps.move(grid, 8, 6, (7, 0), 'left', enter) == (5, 0)
    assert maps.slide(grid, 8, 6, (5, 0), 'left', enter) == (5, 0)


def test_one_sided_walls_stop_a_step_from_either_side():
    # 0xB0 blocks leaving the tile to the right. 0xB1 blocks leaving it to the left, so it is also
    # closed to a step coming in from the left.
    assert maps.side_blocked(0xB0, 'right') and not maps.side_blocked(0xB0, 'left')
    assert maps.side_blocked(0xC4, 'down') and maps.side_blocked(0xC4, 'right')
    assert not maps.side_blocked(0xA0, 'right')
    assert maps.blocked_side is maps.side_blocked
    grid = [FLOOR, 0xB1, FLOOR]
    assert maps.move(grid, 3, 1, (0, 0), 'right', enter) is None
    assert maps.move(grid, 3, 1, (2, 0), 'left', enter) == (1, 0)
    assert maps.move([0xB0, FLOOR], 2, 1, (0, 0), 'right', enter) is None


def test_has_ice():
    assert maps.has_ice(ice_room()) and maps.has_ice([0, 0x2B]) and not maps.has_ice([0, 7])


class Banked:
    """Memory read as ``memory[bank, start:stop]``, enough for one symbol."""

    def __init__(self, address, content):
        self.address, self.content = address, bytes(content)

    def __getitem__(self, key):
        _, span = key
        return self.content[span.start - self.address:span.stop - self.address]


def tables(entries=None):
    entries = entries or {}
    permissions = [0] * 256
    permissions[WALL] = 15
    permissions[0x24] = 1
    return SimpleNamespace(symbols={'wOverworldMapBlocks': (0, 0xC700)}, maps=entries, permissions=permissions,
                           events={}, items={'BICYCLE': 7}, map_ids={entry['constant']: mid for mid, entry in entries.items()})


def at(mid, flags=(), items=(), objects=(), badges=0, party=()):
    return SimpleNamespace(map=mid, x=0, y=0, items=tuple(items), objects=tuple(objects), badges=badges, party=party,
                           event=lambda name: name in flags)


def test_collision_decodes_the_loaded_blocks_inside_their_border():
    # A 4x4 map is 2x2 blocks. Loaded blocks have three border blocks on each side, eight per row.
    table = [[0, 1, 2, 3], [7, 7, 7, 7], [0x23, 0x23, 0, 0]]
    data = tables({ROOM: dict(constant='TEST', width=4, height=4, block_collision=table, collision=[], objects=[])})
    blocks = bytearray(8 * 8)
    blocks[3 * 8 + 3], blocks[3 * 8 + 4], blocks[4 * 8 + 3], blocks[4 * 8 + 4] = 0, 2, 1, 9
    grid = maps.collision(Banked(0xC700, blocks), data, at(ROOM))
    assert grid == [0, 1, 0x23, 0x23,
                    2, 3, 0, 0,
                    7, 7, 7, 7,
                    7, 7, 7, 7]
    assert maps.decode_blocks(blocks, 4, 4, table) == grid


def test_passable_reads_the_permission_low_nibble():
    data = tables()
    assert maps.passable(data, FLOOR) and not maps.passable(data, WALL)
    assert not maps.passable(data, 0x24) and maps.passable(data, 0x24, surf=True)


def blank(constant, width=40, height=12):
    return dict(constant=constant, width=width, height=height, collision=[0] * (width * height),
                block_collision=[[0] * 4] * 0x7A + [[7, 7, 7, 7]], objects=[])


def test_travel_collision_raises_the_story_walls_until_they_clear():
    data = tables({1: blank('ROUTE_36'), 2: blank('VERMILION_CITY'), 3: blank('ROUTE_16_GATE'),
                     4: blank('VICTORY_ROAD_GATE'), 5: blank('ROUTE_19'), 6: blank('ROUTE_29')})
    plain = data.maps[6]['collision']
    assert maps.travel_collision(data, at(6), 6, plain) is plain
    grid = maps.travel_collision(data, at(1), 1, data.maps[1]['collision'])
    assert grid[9 * 40 + 35] == 7 and sum(grid) == 7
    assert maps.travel_collision(data, at(1, {'EVENT_ROUTE_36_SUDOWOODO'}), 1, data.maps[1]['collision']) == [0] * 480
    assert sum(maps.travel_collision(data, at(2), 2, data.maps[2]['collision'])) == 4 * 7
    assert sum(maps.travel_collision(data, at(3), 3, data.maps[3]['collision'])) == 2 * 7
    assert sum(maps.travel_collision(data, at(3, items=[(7, 1)]), 3, data.maps[3]['collision'])) == 0
    gate = maps.travel_collision(data, at(4, {'EVENT_OPENED_MT_SILVER'}), 4, data.maps[4]['collision'])
    assert gate[5 * 40 + 12] == 7 and gate[5 * 40 + 7] == 0
    assert sum(maps.travel_collision(data, at(5), 5, data.maps[5]['collision'])) == 6 * 4 * 7
    assert data.maps[1]['collision'] == [0] * 480


def test_event_changes_open_doors_on_maps_that_are_not_loaded():
    entries = {mid: blank(name) for mid, name in enumerate(maps.TRAVEL_MAPS, 1)}
    store = blank('GOLDENROD_DEPT_STORE_B1F')
    store['block_collision'] = [[0] * 4] * 0x0D + [[0x70, 0x71, 0x72, 0x73]]
    entries[10] = store
    data = tables(entries)
    data.events = {'EVENT_RECEIVED_CARD_KEY': 1}
    closed = maps.event_changes(data, at(1))
    assert set(closed) == set(range(1, 7)) | {10} and closed[10] == store['collision']
    opened = maps.event_changes(data, at(1, {'EVENT_RECEIVED_CARD_KEY'}))[10]
    assert [opened[4 * 40 + 16], opened[4 * 40 + 17], opened[5 * 40 + 16], opened[5 * 40 + 17]] == [0x70, 0x71, 0x72, 0x73]
    live = {10: [9] * 480}
    assert maps.event_changes(data, at(1, {'EVENT_RECEIVED_CARD_KEY'}), live)[10][0] == 9
    assert 10 not in maps.event_changes(data, at(10))
    assert live[10] == [9] * 480


def test_ice_solids_follow_live_boulders_and_skip_hidden_objects():
    room = dict(constant='ICE', width=8, height=6, objects=[
        dict(x=1, y=1, sprite='SPRITE_BOULDER', event=-1),
        dict(x=2, y=2, sprite='SPRITE_ROCKER', event='EVENT_GONE'),
        dict(x=3, y=3, sprite='SPRITE_POKE_BALL', event=-1),
    ])
    data = tables({ROOM: room})
    data.events = {'EVENT_GONE': 5}
    assert maps.ice_solids(data, at(ROOM, objects=[(1, 4, 4)]), ROOM) == {(4, 4), (2, 2), (3, 3)}
    assert maps.ice_solids(data, at(2, {'EVENT_GONE'}, objects=[(1, 4, 4)]), ROOM) == {(1, 1), (3, 3)}


def test_flyer_needs_the_storm_badge_and_a_hatched_flier():
    egg = SimpleNamespace(egg=True, moves=(19,))
    bird = SimpleNamespace(egg=False, moves=(33, 19))
    assert maps.flyer(at(1, badges=32, party=(egg, bird))) == 1
    assert maps.flyer(at(1, badges=31, party=(bird,))) is None
    assert maps.flyer(at(1, badges=32, party=(egg,))) is None
    assert maps.OUTSIDE == {'TOWN', 'ROUTE'}


def test_names_are_on_the_package():
    for name in ('DIRS', 'OPPOSITE', 'WALLS', 'ICE', 'slide', 'move', 'has_ice', 'side_blocked', 'collision',
                 'passable', 'CHANGES', 'DOORS', 'travel_collision', 'ice_solids', 'OUTSIDE', 'flyer'):
        assert getattr(gen2, name) is getattr(maps, name)
