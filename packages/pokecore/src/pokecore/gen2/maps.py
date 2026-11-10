"""Gold, Silver and Crystal map collision, ice sliding and the map changes event flags make.

Collision grids are one byte per walking tile, row by row, as the consumer's ``data.maps``
entries hold them (``collision``, ``block_collision``, ``width``, ``height``). ``data`` is the
consumer's game tables, as for :func:`pokecore.gen2.read_snapshot`. Route planning stays
with the consumer: these helpers only say what the game itself would let the player do.
"""
from __future__ import annotations

from .ram import Memory

ICE = frozenset((0x23, 0x2B))
WALLS = ({'right'}, {'left'}, {'up'}, {'down'}, {'down', 'right'}, {'down', 'left'},
         {'up', 'right'}, {'up', 'left'})
DIRS = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}
OPPOSITE = {'up': 'down', 'down': 'up', 'left': 'right', 'right': 'left'}

# The map environments Fly can be used from.
OUTSIDE = frozenset({'TOWN', 'ROUTE'})

# Event flag, map and the (x, y, block) blocks the game swaps in while the flag is set.
CHANGES = (
    ('EVENT_LANCES_ROOM_ENTRANCE_CLOSED', 'LANCES_ROOM', ((4, 22, 0x34),)),
    ('EVENT_LANCES_ROOM_EXIT_OPEN', 'LANCES_ROOM', ((4, 0, 0x0B),)),
    ('EVENT_USED_BASEMENT_KEY', 'GOLDENROD_UNDERGROUND', ((18, 6, 0x2E),)),
    ('EVENT_USED_THE_CARD_KEY_IN_THE_RADIO_TOWER', 'RADIO_TOWER_3F', ((14, 2, 0x2A), (14, 4, 1))),
    ('EVENT_UNCOVERED_STAIRCASE_IN_MAHOGANY_MART', 'MAHOGANY_MART_1F', ((6, 2, 0x1E),)),
    ('EVENT_OPENED_DOOR_TO_GIOVANNIS_OFFICE', 'TEAM_ROCKET_BASE_B3F', ((10, 8, 7),)),
    ('EVENT_OPENED_DOOR_TO_ROCKET_HIDEOUT_TRANSMITTER', 'TEAM_ROCKET_BASE_B2F', ((14, 12, 7),)),
    ('EVENT_RECEIVED_CARD_KEY', 'GOLDENROD_DEPT_STORE_B1F', ((16, 4, 0x0D),)),
    ('EVENT_BOULDER_IN_BLACKTHORN_GYM_1', 'BLACKTHORN_GYM_1F', ((8, 2, 0x3B),)),
    ('EVENT_BOULDER_IN_BLACKTHORN_GYM_2', 'BLACKTHORN_GYM_1F', ((2, 4, 0x3A),)),
    ('EVENT_BOULDER_IN_BLACKTHORN_GYM_3', 'BLACKTHORN_GYM_1F', ((8, 6, 0x3B),)),
)
# The blocks each EVENT_DOOR_<n>_OPEN flag opens in the Goldenrod Underground switch room.
DOORS = (
    ((16, 6, 0x2D),), ((10, 6, 0x2D),), ((2, 6, 0x2D),),
    ((2, 10, 0x2D),), ((10, 10, 0x2D),), ((16, 10, 0x2D),),
    ((12, 6, 0x2A), (12, 8, 0x2D)), ((6, 6, 0x2A), (6, 8, 0x2D)),
    ((12, 10, 0x2A), (12, 12, 0x2D)), ((6, 10, 0x2A), (6, 12, 0x2D)),
    ((18, 10, 0x2A), (18, 12, 0x2D)),
)
# The Elite Four rooms close behind the player and open ahead once the member is beaten.
LEAGUE = tuple((f'EVENT_{name}_ROOM_{event}', f'{name}_ROOM', ((4, y, block),))
               for name in ('WILLS', 'KOGAS', 'BRUNOS', 'KARENS')
               for event, y, block in [('ENTRANCE_CLOSED', 14, 0x2A), ('EXIT_OPEN', 2, 0x16)])
# Maps whose collision travel_collision changes, whether or not they are loaded.
TRAVEL_MAPS = ('ROUTE_16_GATE', 'ROUTE_17_ROUTE_18_GATE', 'VERMILION_CITY', 'ROUTE_19', 'ROUTE_36',
               'VICTORY_ROAD_GATE')


def has_ice(grid):
    return not ICE.isdisjoint(grid)


def side_blocked(tile, direction):
    """Whether a one-sided wall on ``tile`` stops movement in ``direction``."""
    return tile & 0xF0 in (0xB0, 0xC0) and direction in WALLS[tile & 7]


blocked_side = side_blocked


def slide(grid, width, height, point, button, enter, solid=frozenset(), stop=frozenset()):
    """Where a player who just stepped onto ``point`` while moving ``button`` comes to rest.

    Stepping onto an ice tile commits the player to that direction until the next tile is
    blocked or is not ice. ``enter`` says whether a tile can be walked on. ``solid`` holds tiles
    occupied by objects. A tile in ``stop`` ends the slide as soon as it is entered, as warps do.
    """
    dx, dy = DIRS[button]
    x, y = point
    while grid[y * width + x] in ICE and (x, y) not in stop:
        nx, ny = x + dx, y + dy
        if (not 0 <= nx < width or not 0 <= ny < height or (nx, ny) in solid
                or side_blocked(grid[y * width + x], button)
                or side_blocked(grid[ny * width + nx], OPPOSITE[button])
                or not enter(grid[ny * width + nx])):
            break
        x, y = nx, ny
    return x, y


def move(grid, width, height, point, button, enter, solid=frozenset(), stop=frozenset()):
    """Where one step from ``point`` ends, or None when the first tile cannot be entered."""
    dx, dy = DIRS[button]
    x, y = point
    nx, ny = x + dx, y + dy
    if (not 0 <= nx < width or not 0 <= ny < height or (nx, ny) in solid
            or side_blocked(grid[y * width + x], button)
            or side_blocked(grid[ny * width + nx], OPPOSITE[button])
            or not enter(grid[ny * width + nx])):
        return None
    return slide(grid, width, height, (nx, ny), button, enter, solid, stop)


def decode_blocks(blocks, width, height, table):
    """The collision grid of loaded map blocks, which carry a three-block border on every side.

    A block number past ``table`` (the map's ``block_collision``) reads as a wall (7).
    """
    stride = width // 2 + 6
    return [table[block][(y % 2) * 2 + x % 2] if (block := blocks[(y // 2 + 3) * stride + x // 2 + 3]) < len(table)
            else 7 for y in range(height) for x in range(width)]


def collision(memory, data, snapshot):
    """The live collision grid of the loaded map, from ``wOverworldMapBlocks``.

    It follows block swaps the game has made (opened doors, moved boulders) and then applies
    :func:`travel_collision`. Each call decodes again and returns a fresh list.
    """
    entry = data.maps[snapshot.map]
    width, height = entry['width'], entry['height']
    blocks = Memory(memory, data).read('wOverworldMapBlocks', (width // 2 + 6) * (height // 2 + 6))
    grid = decode_blocks(blocks, width, height, entry['block_collision'])
    return list(travel_collision(data, snapshot, snapshot.map, grid))


def passable(data, collision, surf=False):
    """Whether a collision byte can be walked on, or surfed on when ``surf`` is set."""
    permission = data.permissions[collision] & 15
    return permission == 0 or permission == 1 and surf


def travel_collision(data, snapshot, mid, grid):
    """``grid`` with the walls the game raises until story flags or items clear them.

    The Sudowoodo on Route 36, the Snorlax by Vermilion City, the Cinnabar rocks on Route 19,
    the Victory Road gate guards and the bike-only Route 16 and 17 gates. Returns ``grid``
    itself when nothing applies, otherwise a changed copy.
    """
    entry = data.maps[mid]
    name, width = entry['constant'], entry['width']
    if name == 'VICTORY_ROAD_GATE':
        grid = list(grid)
        for event, x in [('EVENT_OPENED_MT_SILVER', 7), ('EVENT_FOUGHT_SNORLAX', 12)]:
            if not snapshot.event(event):
                grid[5 * width + x] = 7
    if name == 'ROUTE_36' and not snapshot.event('EVENT_ROUTE_36_SUDOWOODO'):
        grid = list(grid)
        grid[9 * width + 35] = 7
    if name == 'ROUTE_19' and not snapshot.event('EVENT_CINNABAR_ROCKS_CLEARED'):
        grid = list(grid)
        for x, y in ((6, 6), (8, 6), (10, 6), (12, 8), (4, 8), (10, 10)):
            for dy in range(2):
                for dx in range(2):
                    grid[(y + dy) * width + x + dx] = entry['block_collision'][0x7A][dy * 2 + dx]
    if name in {'ROUTE_16_GATE', 'ROUTE_17_ROUTE_18_GATE'} and data.items['BICYCLE'] not in dict(snapshot.items):
        grid = list(grid)
        for y in (4, 5):
            grid[y * width + 5] = 7
    if name == 'VERMILION_CITY' and not snapshot.event('EVENT_VERMILION_CITY_SNORLAX'):
        grid = list(grid)
        for y in (8, 9):
            for x in (34, 35):
                grid[y * width + x] = 7
    return grid


def event_changes(data, snapshot, live=None):
    """Collision grids of maps other than the loaded one, as their event flags leave them.

    Returns {map id: grid} for every map in :data:`CHANGES`, :data:`LEAGUE`, the switch room
    doors and :data:`TRAVEL_MAPS`. ``live`` maps a map id to the last grid seen there, used as
    the base for flag edits. The loaded map is skipped by flag edits, since its live grid from
    :func:`collision` already shows them. Events missing from ``data.events`` are skipped.
    """
    live = live or {}
    edits = {}
    doors = tuple((f'EVENT_DOOR_{i}_OPEN', 'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES', blocks)
                  for i, blocks in enumerate(DOORS, 1))
    for event, name, blocks in CHANGES + LEAGUE + doors:
        if event not in data.events:
            continue
        mid = data.map_ids[name]
        if mid == snapshot.map:
            continue
        entry = data.maps[mid]
        grid = edits.setdefault(mid, list(live.get(mid, entry['collision'])))
        opened = snapshot.event(event)
        for x, y, block in blocks:
            for dy in range(2):
                for dx in range(2):
                    offset = (y + dy) * entry['width'] + x + dx
                    grid[offset] = entry['block_collision'][block][dy * 2 + dx] if opened else entry['collision'][offset]
    for name in TRAVEL_MAPS:
        mid = data.map_ids[name]
        edits[mid] = list(travel_collision(data, snapshot, mid, data.maps[mid]['collision']))
    return edits


def ice_solids(data, snapshot, mid):
    """Tiles of map ``mid`` held by objects the game is currently showing.

    Objects an event flag has hidden are skipped. Boulders use the position the game reports
    while their map is loaded, since the player can push them. Everything else stays where the map puts it.
    """
    live = {index: (x, y) for index, x, y in snapshot.objects} if snapshot.map == mid else {}
    points = set()
    for index, obj in enumerate(data.maps[mid]['objects'], 1):
        if obj['event'] in data.events and snapshot.event(obj['event']):
            continue
        points.add(live.get(index, (obj['x'], obj['y'])) if obj['sprite'] == 'SPRITE_BOULDER' else (obj['x'], obj['y']))
    return points


def flyer(snapshot):
    """The party slot that can use Fly, or None without the Storm Badge or a Pokémon that knows it."""
    if not snapshot.badges & 32:
        return None
    return next((i for i, mon in enumerate(snapshot.party) if not mon.egg and 19 in mon.moves), None)
