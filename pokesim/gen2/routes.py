"""Route between connected map regions, including revisits through other entrances."""
from collections import deque

DIRECTIONS = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}
OPPOSITE = {'up': 'down', 'down': 'up', 'left': 'right', 'right': 'left'}
WALLS = ({'right'}, {'left'}, {'up'}, {'down'}, {'down', 'right'}, {'down', 'left'},
         {'up', 'right'}, {'up', 'left'})


def side_wall(tile, direction):
    return tile & 0xF0 in (0xB0, 0xC0) and direction in WALLS[tile & 7]


class Regions:
    def __init__(self, data):
        self.data = data
        self.cache = {}
        self.live = {}
        self.cleared_rocks = {}

    def observe_rocks(self, mid, cleared):
        if self.cleared_rocks.get(mid, set()) != cleared:
            self.cache = {key: value for key, value in self.cache.items() if key[0] != mid}
            self.cleared_rocks[mid] = set(cleared)

    def observe(self, mid, grid):
        previous = self.live.get(mid, self.data.maps[mid]['collision'])
        if previous != grid:
            self.cache = {key: value for key, value in self.cache.items() if key[0] != mid}
        self.live[mid] = grid

    def walkable(self, tile, cut, surf):
        return (self.data.permissions[tile] & 15) == 0 or cut and tile in (0x12, 0x1A) or surf and (self.data.permissions[tile] & 15) == 1

    def regions(self, mid, cut, surf):
        key = (mid, cut, surf)
        if key in self.cache:
            return self.cache[key]
        entry = self.data.maps[mid]
        grid = list(self.live.get(mid, entry['collision']))
        for index, obj in enumerate(entry['objects'], 1):
            if (obj['sprite'] == 'SPRITE_ROCK' and index not in self.cleared_rocks.get(mid, set())) or (obj['sprite'] == 'SPRITE_BOULDER'
                    and entry.get('constant', '').startswith('MOUNT_MORTAR_')):
                grid[obj['y'] * entry['width'] + obj['x']] = 7
        width, height = entry['width'], entry['height']
        labels = {}
        terminals = {(warp['x'], warp['y']) for warp in entry['warps']
                     if 0x60 <= grid[warp['y'] * width + warp['x']] <= 0x7F}
        index = 0
        for y in range(height):
            for x in range(width):
                if (x, y) in labels or (x, y) in terminals or not self.walkable(grid[y * width + x], cut, surf):
                    continue
                index += 1
                labels[x, y] = index
                queue = deque([(x, y)])
                while queue:
                    px, py = queue.popleft()
                    for button, (dx, dy) in DIRECTIONS.items():
                        nx, ny = px + dx, py + dy
                        if (nx, ny) in labels or (nx, ny) in terminals or not 0 <= nx < width or not 0 <= ny < height:
                            continue
                        if (side_wall(grid[py * width + px], button)
                                or side_wall(grid[ny * width + nx], OPPOSITE[button])
                                or not self.walkable(grid[ny * width + nx], cut, surf)):
                            continue
                        labels[nx, ny] = index
                        queue.append((nx, ny))
        self.cache[key] = labels
        return labels

    def memberships(self, mid, point, cut, surf):
        labels = self.regions(mid, cut, surf)
        if point in labels:
            return {labels[point]}
        entry = self.data.maps[mid]
        grid = self.live.get(mid, entry['collision'])
        x, y = point
        if not 0 <= x < entry['width'] or not 0 <= y < entry['height']:
            return set()
        tile = grid[y * entry['width'] + x]
        if not 0x60 <= tile <= 0x7F:
            return set()
        # Doors and caves step down on arrival. Edge carpets face the interior.
        exits = {0x70: (0, -1), 0x71: (0, 1), 0x76: (1, 0), 0x78: (0, 1),
                 0x79: (0, 1), 0x7A: (0, 1), 0x7B: (0, 1), 0x7E: (-1, 0)}
        directions = [exits[tile]] if tile in exits else DIRECTIONS.values()
        return {labels[neighbor] for dx, dy in directions
                if (neighbor := (x + dx, y + dy)) in labels}

    def edges(self, node, cut, surf):
        mid, region = node
        entry = self.data.maps[mid]
        labels = self.regions(mid, cut, surf)
        grid = self.live.get(mid, entry['collision'])
        for warp in entry['warps']:
            x, y = warp['x'], warp['y']
            if region not in self.memberships(mid, (x, y), cut, surf) or not 0x60 <= grid[y * entry['width'] + x] <= 0x7F:
                continue
            destination = self.data.maps[warp['map']]
            if entry.get('constant', '').endswith('MAGNET_TRAIN_STATION') and destination['constant'].endswith('MAGNET_TRAIN_STATION'):
                continue
            if not 1 <= warp['warp'] <= len(destination['warps']):
                continue
            landing = destination['warps'][warp['warp'] - 1]
            for target_region in self.memberships(warp['map'], (landing['x'], landing['y']), cut, surf):
                yield (warp['map'], target_region), [(x, y)], 'warp'
        for (x, y), label in labels.items():
            tile = grid[y * entry['width'] + x]
            if label != region or tile & 0xF0 != 0xA0:
                continue
            for direction in WALLS[tile & 7]:
                dx, dy = DIRECTIONS[direction]
                landing = labels.get((x + 2 * dx, y + 2 * dy))
                if landing is not None and landing != region:
                    yield (mid, landing), [(x, y)], direction
        for connection in entry['connections']:
            target = self.data.maps[connection['map']]
            other_labels = self.regions(connection['map'], cut, surf)
            offset = connection['offset'] * 2
            direction = connection['direction']
            groups = {}
            horizontal = direction in ('north', 'south')
            for index in range(entry['width'] if horizontal else entry['height']):
                other = index - offset
                if not 0 <= other < (target['width'] if horizontal else target['height']):
                    continue
                if horizontal:
                    point = (index, 0 if direction == 'north' else entry['height'] - 1)
                    landing = (other, target['height'] - 1 if direction == 'north' else 0)
                    exit_point = (index, -1 if direction == 'north' else entry['height'])
                else:
                    point = (0 if direction == 'west' else entry['width'] - 1, index)
                    landing = (target['width'] - 1 if direction == 'west' else 0, other)
                    exit_point = (-1 if direction == 'west' else entry['width'], index)
                target_region = other_labels.get(landing)
                if labels.get(point) == region and target_region is not None:
                    groups.setdefault(target_region, []).append(exit_point)
            for target_region, points in groups.items():
                yield (connection['map'], target_region), points, direction

    def route(self, snapshot, target_map, targets, *, cut=False, surf=False, excluded=()):
        starts = [(snapshot.map, region) for region in self.memberships(snapshot.map, (snapshot.x, snapshot.y), cut, surf)]
        goals = {(target_map, region) for point in targets for region in self.memberships(target_map, point, cut, surf)}
        queue = deque(starts)
        paths = {start: [] for start in starts}
        while queue:
            node = queue.popleft()
            if node in goals:
                return paths[node]
            for destination, points, kind in self.edges(node, cut, surf):
                if destination in paths or (node, destination) in excluded:
                    continue
                paths[destination] = paths[node] + [(node, destination, points, kind)]
                queue.append(destination)
        return None
