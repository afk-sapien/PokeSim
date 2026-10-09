"""Gen II map routing with live collision blocks and object avoidance."""
from collections import deque

from . import ice
from .ram import Memory, Snapshot
from .routes import Regions, Search
from .world import ice_solids, travel_collision

DIRS = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}
OPPOSITE = {'up': 'down', 'down': 'up', 'left': 'right', 'right': 'left'}
WALLS = ({'right'}, {'left'}, {'up'}, {'down'}, {'down', 'right'}, {'down', 'left'},
         {'up', 'right'}, {'up', 'left'})


def blocked_side(tile, direction):
    return tile & 0xF0 in (0xB0, 0xC0) and direction in WALLS[tile & 7]


class Navigator:
    def __init__(self, data):
        self.data = data
        self.blocked = {}
        self.previous = None
        self.visits = {}
        self.explored = {}
        self.exploring = None
        self.failed_edges = {}
        self.searches = {}
        self.objects = {}
        self.regions = Regions(data)
        self.region_failures = {}
        self.last_map = None
        self.moved_frame = -10 ** 9

    def observe(self, snapshot):
        if self.last_map is not None and self.last_map != snapshot.map:
            self.objects.pop(snapshot.map, None)
            self.regions.observe_rocks(snapshot.map, set())
        self.last_map = snapshot.map
        visible = {index: (x, y) for index, x, y in snapshot.objects}
        known = self.objects.setdefault(snapshot.map, {})
        objects = self.data.maps[snapshot.map]['objects']
        # A pushed boulder also shows up under a spare index (255) at its new tile, so it is counted once.
        real = {point for index, point in visible.items() if 1 <= index <= len(objects)}
        visible = {index: point for index, point in visible.items() if 1 <= index <= len(objects) or point not in real}
        moved = set()
        for index, (x, y) in list(known.items()):
            boulder = not 1 <= index <= len(objects) or objects[index - 1]['sprite'] == 'SPRITE_BOULDER'
            if index in visible and visible[index] != (x, y) and boulder:
                moved.add((x, y))
            if index not in visible and abs(x - snapshot.x) <= 4 and abs(y - snapshot.y) <= 4:
                del known[index]
                if boulder:
                    moved.add((x, y))
        known.update(visible)
        if moved:
            self.moved_frame = snapshot.frame
        real = {point for index, point in known.items() if 1 <= index <= len(objects)}
        for index in [index for index, point in known.items() if not 1 <= index <= len(objects) and point in real]:
            del known[index]
        for key in [key for key in self.blocked if key[0] == snapshot.map and key[1:] in moved]:
            del self.blocked[key]
        for mid in self.regions.ice_maps:
            self.regions.observe_solids(mid, ice_solids(self.data, snapshot, mid))
        cleared = set(self.regions.cleared_rocks.get(snapshot.map, set()))
        for index, obj in enumerate(objects, 1):
            if (obj['sprite'] == 'SPRITE_ROCK' and index not in visible
                    and abs(obj['x'] - snapshot.x) <= 4 and abs(obj['y'] - snapshot.y) <= 4):
                cleared.add(index)
        cleared.difference_update(visible)
        self.regions.observe_rocks(snapshot.map, cleared)
        for index in list(known):
            if 1 <= index <= len(objects):
                event = objects[index - 1]['event']
                if event in self.data.events and snapshot.event(event) and index not in visible:
                    del known[index]
        point = (snapshot.map, snapshot.x, snapshot.y)
        self.visits[point] = self.visits.get(point, 0) + 1
        if self.previous:
            before, button, frame = self.previous
            if point == before and snapshot.frame - frame >= 24 and not snapshot.in_battle:
                dx, dy = DIRS[button]
                ahead = (snapshot.x + dx, snapshot.y + dy)
                # A boulder push, or the Strength question, leaves the player in place without the
                # tile being a wall, and the boulder's old tile is free once it has moved on.
                pushing = snapshot.frame - self.moved_frame <= 120 or any(
                    point == ahead for index, point in known.items()
                    if 1 <= index <= len(objects) and objects[index - 1]['sprite'] == 'SPRITE_BOULDER')
                if not pushing:
                    self.blocked[(snapshot.map, *ahead)] = snapshot.frame + 180
            self.previous = None
        self.blocked = {key: until for key, until in self.blocked.items() if until > snapshot.frame}

    def issued(self, snapshot, button):
        if button in DIRS:
            self.previous = ((snapshot.map, snapshot.x, snapshot.y), button, snapshot.frame)

    def collision(self, snapshot, memory=None):
        entry = self.data.maps[snapshot.map]
        if memory is None:
            return self.regions.live.get(snapshot.map, entry['collision'])
        width, height = entry['width'], entry['height']
        stride = width // 2 + 6
        mem = Memory(memory, self.data)
        blocks = mem.read('wOverworldMapBlocks', stride * (height // 2 + 6))
        # The grid is a function of the map, its loaded blocks, and the flags and items the travel
        # rules read, so it is decoded again only when one of those changes.
        # Stand-in snapshots without flags or items are decoded every time.
        key = (snapshot.map, blocks, snapshot.event_flags, snapshot.items) if isinstance(snapshot, Snapshot) else None
        cached = getattr(self, '_collision', None)
        if key is None or cached is None or cached[0] != key:
            table = entry['block_collision']
            grid = [table[block][(y % 2) * 2 + x % 2] if (block := blocks[(y // 2 + 3) * stride + x // 2 + 3]) < len(table) else 7
                    for y in range(height) for x in range(width)]
            cached = self._collision = key, travel_collision(self.data, snapshot, snapshot.map, grid)
        # Each caller gets its own list, as a fresh decode would give it.
        return list(cached[1])

    def passable(self, collision, *, surf=False):
        permission = self.data.permissions[collision] & 15
        return permission == 0 or permission == 1 and surf

    def local(self, snapshot, targets, memory=None, *, surf=False, avoid_warps=True, distant_objects=True):
        entry = self.data.maps[snapshot.map]
        width, height = entry['width'], entry['height']
        grid = list(self.collision(snapshot, memory))
        for index, obj in enumerate(entry['objects'], 1):
            if obj['sprite'] == 'SPRITE_ROCK' and index not in self.regions.cleared_rocks.get(snapshot.map, set()):
                grid[obj['y'] * width + obj['x']] = 7
        can_cut = bool(snapshot.badges & 2) and any(15 in mon.moves for mon in snapshot.party)
        border = {}
        if memory is not None:
            stride = width // 2 + 6
            blocks = Memory(memory, self.data).read('wOverworldMapBlocks', stride * (height // 2 + 6))
            table = entry['block_collision']
            for point in ([(x, y) for x in range(width) for y in (-1, height)]
                          + [(x, y) for y in range(height) for x in (-1, width)]):
                x, y = point
                block = blocks[(y // 2 + 3) * stride + x // 2 + 3]
                border[point] = table[block][(y % 2) * 2 + x % 2] if block < len(table) else 7
        targets = set(targets)
        occupied = set(self.objects.get(snapshot.map, {}).values()) if distant_objects else set()
        occupied.update((x, y) for _, x, y in snapshot.objects)
        boulders = {index for index, obj in enumerate(entry['objects'], 1) if obj['sprite'] == 'SPRITE_BOULDER'}
        occupied.update(point for index, point in self.objects.get(snapshot.map, {}).items() if index in boulders)
        occupied.update((x, y) for index, x, y in snapshot.objects if index in boulders)
        warps = {(warp['x'], warp['y']) for warp in entry['warps']
                 if 0x60 <= grid[warp['y'] * width + warp['x']] <= 0x7F} - targets if avoid_warps else set()
        # Objects out of sight still stop a slide, so ice maps also count the ones the map data places.
        occupied |= self.regions.solids.get(snapshot.map, frozenset()) if snapshot.map in self.regions.ice_maps else set()
        bumped = {(nx, ny) for (mid, nx, ny) in self.blocked if mid == snapshot.map}
        # Only a warp ends a slide on the spot. Passing over any other target does not stop the player there.
        doors = {(warp['x'], warp['y']) for warp in entry['warps']}
        origin = (snapshot.x, snapshot.y)
        queue = deque([origin])
        paths = {origin: []}
        while queue:
            x, y = queue.popleft()
            if (x, y) in targets:
                return paths[(x, y)]
            for button, (dx, dy) in DIRS.items():
                jumping = grid[y * width + x] & 0xF0 == 0xA0 and button in WALLS[grid[y * width + x] & 7]
                distance = 2 if jumping else 1
                point = (x + dx * distance, y + dy * distance)
                nx, ny = point
                if (point in paths or point in occupied or point in warps
                        or (snapshot.map, nx, ny) in self.blocked):
                    continue
                inside = 0 <= nx < width and 0 <= ny < height
                if not inside:
                    if point in targets and self.passable(border.get(point, 7), surf=surf):
                        return paths[(x, y)] + [button]
                    continue
                if (blocked_side(grid[y * width + x], button)
                        or blocked_side(grid[ny * width + nx], OPPOSITE[button])
                        or not (self.passable(grid[ny * width + nx], surf=surf)
                                or can_cut and grid[ny * width + nx] in (0x12, 0x1A))):
                    continue
                # Ice commits the player to a direction until a wall, an object or dry ground.
                if grid[ny * width + nx] in ice.ICE:
                    nx, ny = ice.slide(grid, width, height, (nx, ny), button, lambda tile: self.passable(tile, surf=surf),
                                       occupied | warps | bumped, targets & doors)
                point = (nx, ny)
                if point in paths:
                    continue
                paths[point] = paths[(x, y)] + [button]
                queue.append(point)
        if distant_objects:
            return self.local(snapshot, targets, memory, surf=surf, avoid_warps=avoid_warps, distant_objects=False)
        return None

    def edges(self, mid):
        entry = self.data.maps[mid]
        for warp in entry['warps']:
            if warp['map'] != mid and not (entry.get('constant', '').endswith('MAGNET_TRAIN_STATION')
                    and self.data.maps[warp['map']]['constant'].endswith('MAGNET_TRAIN_STATION')):
                yield warp['map'], [(warp['x'], warp['y'])], 'warp'
        width, height = entry['width'], entry['height']
        for connection in entry['connections']:
            target = self.data.maps[connection['map']]
            direction = connection['direction']
            offset = connection['offset'] * 2
            if direction in {'north', 'south'}:
                points = [(x, -1 if direction == 'north' else height)
                          for x in range(max(0, offset), min(width, offset + target['width']))]
            else:
                points = [(-1 if direction == 'west' else width, y)
                          for y in range(max(0, offset), min(height, offset + target['height']))]
            yield connection['map'], points, direction

    def route(self, start, target, excluded=()):
        excluded, failed = frozenset(excluded), frozenset(self.failed_edges)
        key = (start, excluded, failed)
        search = self.searches.get(key)
        if search is None:
            def expand(mid):
                for destination, points, kind in self.edges(mid):
                    if destination not in excluded and (mid, destination) not in failed:
                        yield destination, (mid, destination, points, kind)
            if len(self.searches) > 512:
                self.searches = {}
            search = self.searches[key] = Search([start], expand)
        return search.find({target})

    def explore(self, snapshot, memory=None, *, surf=False):
        """Head for the least visited way out of the current region, keeping to one choice until it is reached."""
        cut = bool(snapshot.badges & 2) and any(15 in mon.moves for mon in snapshot.party)
        grid = self.collision(snapshot, memory)
        self.regions.observe(snapshot.map, grid)
        here = {(snapshot.map, region) for region in
                self.regions.memberships(snapshot.map, (snapshot.x, snapshot.y), cut, surf, arrive=True)}
        for node in here:
            self.explored[node] = self.explored.get(node, 0) + (node != self.exploring)
        if self.exploring in here:
            self.exploring = None
        options = []
        for node in here:
            for destination, points, kind in self.regions.edges(node, cut, surf):
                options.append((destination != self.exploring,
                                self.explored.get(destination, 0), len(options), destination, points, kind))
        for _, _, _, destination, points, kind in sorted(options):
            path = self.local(snapshot, points, memory, surf=surf)
            if path is None:
                continue
            if not path:
                path = next(([direction] for direction, (dx, dy) in DIRS.items()
                             if self.local(snapshot, [(snapshot.x + dx, snapshot.y + dy)], memory,
                                           surf=surf) == [direction]), None)
                if path is None:
                    continue
            self.exploring = destination
            return path
        return None

    def toward(self, snapshot, target_map, targets, memory=None, *, surf=False, excluded=()):
        grid = self.collision(snapshot, memory)
        self.regions.observe(snapshot.map, grid)
        cut = bool(snapshot.badges & 2) and any(15 in mon.moves for mon in snapshot.party)
        self.region_failures = {edge: until for edge, until in self.region_failures.items() if until > snapshot.frame}
        for _ in range(30):
            route = self.regions.route(snapshot, target_map, targets, cut=cut, surf=surf,
                                       excluded=self.region_failures)
            if route is None:
                return None
            if route == []:
                return self.local(snapshot, targets, memory, surf=surf)
            origin, destination, points, kind = route[0]
            path = self.local(snapshot, points, memory, surf=surf)
            if path == [] and kind in DIRS:
                return [kind]
            if path == []:
                entry = self.data.maps[snapshot.map]
                tile = grid[snapshot.y * entry['width'] + snapshot.x]
                button = {0x70: 'down', 0x76: 'left', 0x78: 'up', 0x7E: 'right'}.get(tile)
                if button:
                    return [button]
                path = next(([direction] for direction, (dx, dy) in DIRS.items()
                             if self.local(snapshot, [(snapshot.x + dx, snapshot.y + dy)], memory,
                                           surf=surf) == [direction]), None)
            if path is not None:
                return path
            self.region_failures[(origin, destination)] = snapshot.frame + 1200
        return None
