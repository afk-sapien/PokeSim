"""Plan through the Mansion while accounting for the shared statue switch."""
from collections import deque

from .navigation import DIRS, PAIR_COLLISIONS, Navigator
from ..strategy_data import MAPS, WORLD, event_set

MANSION_MAPS = {MAPS[n] for n in ('POKEMON_MANSION_1F', 'POKEMON_MANSION_2F',
                                  'POKEMON_MANSION_3F', 'POKEMON_MANSION_B1F')}
STATUES = {(MAPS[name], x, y + 1) for name, points in (
    ('POKEMON_MANSION_1F', [(2, 5)]), ('POKEMON_MANSION_2F', [(2, 11)]),
    ('POKEMON_MANSION_3F', [(10, 5)]), ('POKEMON_MANSION_B1F', [(20, 3), (18, 25)]))
    for x, y in points}
FALLS = {(MAPS['POKEMON_MANSION_3F'], x, 14): (MAPS['POKEMON_MANSION_1F'], 16, 14)
         for x in (16, 17)}


class MansionPlanner:
    def __init__(self):
        self.path = deque()
        self.targets = None
        self.mode = False
        self.nav = Navigator()
        self.tiles = [{(m, x, y): tile for m in MANSION_MAPS
                       for x, y, tile in WORLD[m]['switch_tiles'][mode]} for mode in range(2)]
        self.nav._tile = self.tile

    def tile(self, world, x, y):
        m = MAPS[world['symbol']]
        return self.tiles[int(self.mode)].get((m, x, y), Navigator._tile(world, x, y))

    def neighbors(self, state, frame):
        pos, mode = state[:3], state[3]
        self.mode = mode
        for dr, q in self.nav.neighbors(pos, frame):
            yield dr, (*FALLS.get(q, q), mode)
        for dr, (dx, dy) in DIRS.items():
            q = (pos[0], pos[1] + dx, pos[2] + dy)
            if q in FALLS and self.nav.blocked.get((pos, dr), 0) <= frame:
                yield dr, (*FALLS[q], mode)
        if pos in STATUES:
            yield 'switch', (*pos, not mode)

    def route(self, snapshot, targets, navigation):
        start = (snapshot.map, snapshot.x, snapshot.y, event_set(snapshot.event_flags, 'EVENT_MANSION_SWITCH_ON'))
        targets = frozenset(targets)
        self.nav.blocked = navigation.blocked
        self.nav.cleared_objects = navigation.cleared_objects
        if self.targets == targets:
            while self.path and self.path[0][0] != start:
                self.path.popleft()
            if self.path:
                _, direction, target = self.path[0]
                if (direction, target) in self.neighbors(start, snapshot.frame):
                    return direction
        self.path.clear()
        self.targets = targets
        local_goal = any(p[0] in MANSION_MAPS for p in targets)
        queue = deque([start])
        previous = {start: None}
        found = None
        while queue:
            state = queue.popleft()
            if state[:3] in targets or (not local_goal and state[0] not in MANSION_MAPS):
                found = state
                break
            if state[0] not in MANSION_MAPS:
                continue
            for direction, target in self.neighbors(state, snapshot.frame):
                if target not in previous:
                    previous[target] = (state, direction)
                    queue.append(target)
        while found is not None and previous[found] is not None:
            pos, direction = previous[found]
            self.path.appendleft((pos, direction, found))
            found = pos
        return self.path[0][1] if self.path else None


VICTORY_MAPS = {MAPS[n] for n in ('VICTORY_ROAD_1F', 'VICTORY_ROAD_2F', 'VICTORY_ROAD_3F')}


def boulder_task(snapshot):
    done = lambda flag: event_set(snapshot.event_flags, flag)
    if snapshot.map == MAPS['VICTORY_ROAD_1F'] and not done('EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH'):
        return 'BOULDER1', (17, 13)
    if snapshot.map == MAPS['VICTORY_ROAD_2F']:
        if not done('EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH1'):
            return 'BOULDER1', (1, 16)
        if done('EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH2') and not done('EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH2'):
            return 'BOULDER3', (9, 16)
    if snapshot.map == MAPS['VICTORY_ROAD_3F']:
        if not done('EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH1'):
            return 'BOULDER1', (3, 5)
        if not done('EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH2'):
            return 'BOULDER4', (23, 15)
    return None


class BoulderPlanner:
    """Search legal pushes while preserving room to walk around the boulder."""
    def __init__(self):
        self.path = deque()
        self.task = None

    def route(self, snapshot, navigation, task):
        world = WORLD[snapshot.map]
        index = next(i for i, obj in enumerate(world['objects']) if obj[4].endswith(task[0]))
        rock = navigation.live_positions[index]
        player = (snapshot.x, snapshot.y)
        start = (*player, *rock)
        task_key = (snapshot.map, task)
        if self.task == task_key:
            while self.path and self.path[0][0] != start:
                self.path.popleft()
            if self.path:
                return self.path[0][1]
        self.path.clear()
        self.task = task_key
        occupied = {navigation.live_positions[i] for i, obj in enumerate(world['objects'])
                    if i != index and i < len(navigation.live_positions)
                    and (snapshot.map, obj[0], obj[1]) not in navigation.cleared_objects}
        warps = {tuple(w[:2]) for w in world['warps'] if w[1] != world['height'] - 1}
        def floor(pos):
            return (pos not in occupied and pos not in warps and
                    (navigation.active_tile(world, *pos) in world['passable'] or pos == task[1]))
        def walk(origin, stone):
            previous = {origin: None}
            queue = deque([origin])
            while queue:
                point = queue.popleft()
                for direction, (dx, dy) in DIRS.items():
                    dest = (point[0] + dx, point[1] + dy)
                    here = navigation.active_tile(world, *point)
                    there = navigation.active_tile(world, *dest)
                    pair_blocked = ((world['tileset'], here, there) in PAIR_COLLISIONS
                                    or (world['tileset'], there, here) in PAIR_COLLISIONS)
                    if dest != stone and dest not in previous and floor(dest) and not pair_blocked:
                        previous[dest] = (point, direction)
                        queue.append(dest)
            return previous
        queue = deque([(player, rock, ())])
        seen = set()
        while queue and len(seen) < 8000:
            person, stone, path = queue.popleft()
            if stone == task[1]:
                self.path.extend(path)
                return self.path[0][1] if self.path else None
            reachable = walk(person, stone)
            key = (min(reachable), stone)
            if key in seen:
                continue
            seen.add(key)
            for direction, (dx, dy) in DIRS.items():
                behind = (stone[0] - dx, stone[1] - dy)
                ahead = (stone[0] + dx, stone[1] + dy)
                if behind not in reachable or not floor(ahead):
                    continue
                steps = []
                point = behind
                while reachable[point] is not None:
                    origin, action = reachable[point]
                    steps.append(((*origin, *stone), action))
                    point = origin
                steps.reverse()
                steps.append(((*behind, *stone), direction))
                queue.append((stone, ahead, path + tuple(steps)))
        return None
