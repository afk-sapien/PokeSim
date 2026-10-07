"""Persistent map changes derived from cartridge event flags."""
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
DOORS = (
    ((16, 6, 0x2D),), ((10, 6, 0x2D),), ((2, 6, 0x2D),),
    ((2, 10, 0x2D),), ((10, 10, 0x2D),), ((16, 10, 0x2D),),
    ((12, 6, 0x2A), (12, 8, 0x2D)), ((6, 6, 0x2A), (6, 8, 0x2D)),
    ((12, 10, 0x2A), (12, 12, 0x2D)), ((6, 10, 0x2A), (6, 12, 0x2D)),
    ((18, 10, 0x2A), (18, 12, 0x2D)),
)


def update(regions, snapshot):
    edits = {}
    league = tuple((f'EVENT_{name}_ROOM_{event}', f'{name}_ROOM', ((4, y, block),))
                   for name in ('WILLS', 'KOGAS', 'BRUNOS', 'KARENS')
                   for event, y, block in [('ENTRANCE_CLOSED', 14, 0x2A), ('EXIT_OPEN', 2, 0x16)])
    changes = CHANGES + league + tuple((f'EVENT_DOOR_{i}_OPEN', 'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES', blocks)
                              for i, blocks in enumerate(DOORS, 1))
    for event, name, blocks in changes:
        if event not in snapshot.data.events:
            continue
        mid = snapshot.data.map_ids[name]
        if mid == snapshot.map:
            continue
        entry = snapshot.data.maps[mid]
        grid = edits.setdefault(mid, list(regions.live.get(mid, entry['collision'])))
        opened = snapshot.event(event)
        for x, y, block in blocks:
            for dy in range(2):
                for dx in range(2):
                    offset = (y + dy) * entry['width'] + x + dx
                    grid[offset] = entry['block_collision'][block][dy * 2 + dx] if opened else entry['collision'][offset]
    for name in ('ROUTE_16_GATE', 'ROUTE_17_ROUTE_18_GATE', 'VERMILION_CITY', 'ROUTE_19', 'ROUTE_36', 'VICTORY_ROAD_GATE'):
        mid = snapshot.data.map_ids[name]
        edits[mid] = travel_collision(snapshot.data, snapshot, mid, snapshot.data.maps[mid]['collision'])
    for mid, grid in edits.items():
        regions.observe(mid, grid)


def travel_collision(data, snapshot, mid, grid):
    name = data.maps[mid]['constant']
    if name == 'VICTORY_ROAD_GATE':
        grid = list(grid)
        for event, x in [('EVENT_OPENED_MT_SILVER', 7), ('EVENT_FOUGHT_SNORLAX', 12)]:
            if not snapshot.event(event):
                grid[5 * data.maps[mid]['width'] + x] = 7
    if name == 'ROUTE_36' and not snapshot.event('EVENT_FOUGHT_SUDOWOODO'):
        grid = list(grid)
        grid[9 * data.maps[mid]['width'] + 35] = 7
    if name == 'ROUTE_19' and not snapshot.event('EVENT_CINNABAR_ROCKS_CLEARED'):
        grid = list(grid)
        entry = data.maps[mid]
        for x, y in ((6, 6), (8, 6), (10, 6), (12, 8), (4, 8), (10, 10)):
            for dy in range(2):
                for dx in range(2):
                    grid[(y + dy) * entry['width'] + x + dx] = entry['block_collision'][0x7A][dy * 2 + dx]
    if name in {'ROUTE_16_GATE', 'ROUTE_17_ROUTE_18_GATE'} and data.items['BICYCLE'] not in dict(snapshot.items):
        grid = list(grid)
        width = data.maps[mid]['width']
        for y in (4, 5):
            grid[y * width + 5] = 7
    if name == 'VERMILION_CITY' and not snapshot.event('EVENT_FOUGHT_SNORLAX'):
        grid = list(grid)
        width = data.maps[mid]['width']
        for y in (8, 9):
            for x in (34, 35):
                grid[y * width + x] = 7
    return grid


def ice_solids(data, snapshot, mid):
    """Tiles of an ice map held by objects the game is currently showing.

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
