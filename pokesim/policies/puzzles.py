"""Plan through the Mansion while accounting for the shared statue switch."""
import re
from collections import deque
from dataclasses import replace

from .gates import BOULDER_SWITCHES
from .navigation import DIRS, FORCED, MANSION_FALLS, PAIR_COLLISIONS, SEAFOAM_HOLES, Navigator
from ..strategy_data import MAPS, WORLD, event_set

BOULDER_NAME = re.compile(r'BOULDER\d*$')

MANSION_MAPS = {MAPS[n] for n in ('POKEMON_MANSION_1F', 'POKEMON_MANSION_2F',
                                  'POKEMON_MANSION_3F', 'POKEMON_MANSION_B1F')}
STATUES = {(MAPS[name], x, y + 1) for name, points in (
    ('POKEMON_MANSION_1F', [(2, 5)]), ('POKEMON_MANSION_2F', [(2, 11)]),
    ('POKEMON_MANSION_3F', [(10, 5)]), ('POKEMON_MANSION_B1F', [(20, 3), (18, 25)]))
    for x, y in points}
FALLS = MANSION_FALLS


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


def seafoam_current_task(snapshot, navigation):
    """Clear space, then push each designated boulder into the hole below Articuno."""
    if snapshot.map != MAPS['SEAFOAM_ISLANDS_B3F']:
        return None
    if not event_set(snapshot.event_flags, 'EVENT_SEAFOAM4_BOULDER1_DOWN_HOLE'):
        if navigation.live_positions[0] != (2, 14):
            return 'BOULDER1', (2, 14)
        return 'BOULDER2', (3, 16)
    if not event_set(snapshot.event_flags, 'EVENT_SEAFOAM4_BOULDER2_DOWN_HOLE'):
        if navigation.live_positions[3] != (9, 12):
            return 'BOULDER4', (9, 12)
        return 'BOULDER3', (6, 16)
    return None


def open_switches(snapshot):
    """The squares of this floor's boulder switches whose flags are still clear."""
    return tuple((x, y) for name, flag, x, y in BOULDER_SWITCHES
                 if MAPS[name] == snapshot.map and not event_set(snapshot.event_flags, flag))


def loose_boulders(snapshot, navigation):
    """The names of this floor's shown boulders that do not already rest on one of its switches."""
    world = WORLD.get(snapshot.map, {})
    switches = {(x, y) for name, _, x, y in BOULDER_SWITCHES if MAPS[name] == snapshot.map}
    found = []
    for index, obj in enumerate(world.get('objects', ())):
        name = BOULDER_NAME.search(obj[4])
        if (obj[2] != 'SPRITE_BOULDER' or not name or index >= len(navigation.live_positions)
                or (snapshot.map, obj[0], obj[1]) in navigation.cleared_objects
                or navigation.live_positions[index] in switches):
            continue
        found.append(name[0])
    return tuple(found)


class BoulderPlanner:
    """Search legal pushes while preserving room to walk around the boulder."""
    def __init__(self):
        self.path = deque()
        self.task = None
        # Searches that found no push plan, by task. Victory Road tries several tasks per step.
        self.failed = {}
        # Walks, square classes and steps of the last search, valid while their inputs match.
        self._context, self._walks, self._squares = None, {}, ({}, {}, {})
        # Exits of a floor that lead on to the goal, by the floor, story, boulders and goal.
        self._exits = (None, ())
        # A navigator per floor an exit leads to, with that floor's gates as its flags leave them.
        self._ahead = {}

    def best(self, snapshot, navigation, tasks):
        """(task, direction) for the shortest push plan among tasks, or (None, None).

        A plan under way stays chosen while it still applies, so the run does not switch
        boulders halfway through.
        """
        tasks = tuple(tasks)
        current = self.task[1] if self.task and self.task[0] == snapshot.map else None
        if current in tasks and self.path:
            direction = self.route(snapshot, navigation, current)
            if direction:
                return current, direction
        found = None
        for task in tasks:
            direction = self.route(snapshot, navigation, task)
            if direction and (found is None or len(self.path) < len(found[2])):
                found = (task, direction, deque(self.path))
        if found is None:
            return None, None
        self.task, self.path = (snapshot.map, found[0]), found[2]
        return found[0], found[1]

    def switch_push(self, snapshot, navigation):
        """(task, direction) to put any loose boulder on any switch of this floor still open.

        The cartridge accepts any boulder on any switch in any order, so every pair is planned and
        the shortest plan wins. A floor with no plan from here may still have a boulder in the way,
        so a push that brings an open switch within reach comes next.
        """
        switches = open_switches(snapshot)
        boulders = loose_boulders(snapshot, navigation) if switches else ()
        if not boulders:
            return None, None
        task, direction = self.best(snapshot, navigation, ((name, square) for square in switches for name in boulders))
        if direction:
            return task, direction
        return self.best(snapshot, navigation, ((name, frozenset(switches), True) for name in boulders))

    def exit_push(self, snapshot, navigation, targets):
        """(task, direction) for a push that opens an exit toward targets when none is in reach."""
        squares = self.exits(snapshot, navigation, targets)
        boulders = loose_boulders(snapshot, navigation) if squares else ()
        return self.best(snapshot, navigation, ((name, squares, False) for name in boulders))

    def exits(self, snapshot, navigation, targets):
        """Squares of this floor that are targets, or ladders and holes the targets can be reached from."""
        key = (snapshot.map, frozenset(targets), navigation._story_key, tuple(navigation.live_positions))
        if self._exits[0] == key:
            return self._exits[1]
        world = WORLD.get(snapshot.map, {})
        squares = {(x, y) for m, x, y in targets if m == snapshot.map}
        leaving = [((x, y), Navigator._warp(snapshot.map, warp)) for warp in world.get('warps', ()) for x, y in (warp[:2],)]
        leaving += [((x, y), q) for (m, x, y), q in FORCED.items() if m == snapshot.map]
        for square, destination in leaving:
            if destination and destination[0] != snapshot.map and self._onward(
                    snapshot, navigation, destination, targets):
                squares.add(square)
        self._exits = (key, frozenset(squares))
        return self._exits[1]

    def _onward(self, snapshot, navigation, destination, targets):
        """True when targets can be reached from destination past its own floor's gates as they are.

        Ordinary navigation assumes every other floor's switches can be solved on the way. The
        floor an exit leads to is judged by its flags instead, so an exit into a pocket whose
        gate is shut does not count. The east corridor's ladders lead only to such a pocket, and
        counting them sent the run back and forth between the two without pushing its boulder.
        """
        there = self._ahead.get(destination[0])
        if there is None:
            there = self._ahead[destination[0]] = Navigator()
        there.update_story(replace(snapshot, map=destination[0]))
        # Boulders off this floor go back where they started and can be pushed again, so they
        # do not wall off a corridor. Only the gates decide.
        there.cleared_objects |= {(m, obj[0], obj[1]) for m in VICTORY_MAPS if m != snapshot.map
                                  for obj in WORLD[m]['objects'] if obj[2] == 'SPRITE_BOULDER'}
        there.use_world = navigation.use_world
        there.live_map, there.live_positions = navigation.live_map, navigation.live_positions
        there.edges, there.blocked = navigation.edges, navigation.blocked
        return there.distance_lookup(destination, snapshot.frame)(targets) is not None

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
        # A push plan that does not exist stays missing while the player walks inside the area
        # the search started from and no boulder or tile moves, so it is not searched again.
        overrides = frozenset(item for item in navigation.tile_overrides.items() if item[0][0] == snapshot.map)
        failure = (task_key, rock, id(world), frozenset(occupied), overrides)
        known = self.failed.get(task_key)
        if known is not None and known[0] == failure and player in known[1]:
            return None
        # The tiles, objects and warps stay the same for the whole search, so each square is
        # classified once instead of once per walk; the search runs thousands of walks. They also
        # stay the same across searches while nothing but the pushed boulder moves, and every push
        # starts a new search that walks most of the same squares again, so the walks are kept
        # until any of their inputs changes.
        context = (task_key, id(world), frozenset(occupied), overrides)
        if self._context != context or len(self._walks) > 4096:
            self._context, self._walks, self._squares = context, {}, ({}, {}, {})
        walks = self._walks
        tiles, floors, steps_between = self._squares
        def tile(pos):
            if pos not in tiles:
                tiles[pos] = navigation.active_tile(world, *pos)
            return tiles[pos]
        def floor(pos):
            if pos not in floors:
                floors[pos] = (pos not in occupied and pos not in warps and
                               (tile(pos) in world['passable'] or pos == task[1]))
            return floors[pos]
        def open_step(point, dest):
            key = (point, dest)
            if key not in steps_between:
                here, there = tile(point), tile(dest)
                steps_between[key] = (floor(dest) and (snapshot.map, *dest) not in SEAFOAM_HOLES
                                      and (world['tileset'], here, there) not in PAIR_COLLISIONS
                                      and (world['tileset'], there, here) not in PAIR_COLLISIONS)
            return steps_between[key]
        def walk(origin, stone):
            if (origin, stone) in walks:
                return walks[origin, stone]
            previous = walks[origin, stone] = {origin: None}
            queue = deque([origin])
            while queue:
                point = queue.popleft()
                for direction, (dx, dy) in DIRS.items():
                    dest = (point[0] + dx, point[1] + dy)
                    if dest != stone and dest not in previous and open_step(point, dest):
                        previous[dest] = (point, direction)
                        queue.append(dest)
            return previous
        squares = task[1] if isinstance(task[1], frozenset) else None
        def arrives(point, reachable):
            # A ladder or a hole is never floor for the walk, so standing beside it counts.
            return point in reachable or not floor(point) and any(
                (point[0] + dx, point[1] + dy) in reachable for dx, dy in DIRS.values())
        queue = deque([(player, rock, ())])
        seen = set()
        area = None
        while queue and len(seen) < 8000:
            person, stone, path = queue.popleft()
            if stone == task[1]:
                self.path.extend(path)
                return self.path[0][1] if self.path else None
            reachable = walk(person, stone)
            if area is None:
                area = frozenset(reachable)
                if squares is not None:
                    # A clearing push is for squares the player cannot reach yet. With fresh unset
                    # it is only for a player who can reach none of them.
                    missing = frozenset(p for p in squares if not arrives(p, reachable))
                    if missing != squares and not task[2]:
                        return None
                    squares = missing
                    if not squares:
                        return None
            elif squares is not None and any(arrives(p, reachable) for p in squares):
                self.path.extend(path)
                return self.path[0][1] if self.path else None
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
        # Every push from the area was tried, so any other square of it fails the same way. A
        # search cut short by its limit is only known to fail from this exact square.
        self.failed[task_key] = (failure, area if not queue and area else frozenset({player}))
        return None
