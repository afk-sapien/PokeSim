"""Directed navigation with observed actions, static geometry, and temporary obstacles."""
from collections import deque

from ..strategy_data import DATA, ITEMS, MAPS, WORLD, event_set

DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
PAIR_COLLISIONS = {(ts, a, b) for ts, a, b in DATA["collision_pairs"]}
WATER_TILESETS = {"OVERWORLD", "PLATEAU", "FOREST", "CAVERN", "SHIP_PORT"}
OPTIONAL_LIFTS = {MAPS["CELADON_MART_ELEVATOR"], MAPS["SILPH_CO_ELEVATOR"]}
FORCED = {(m, x, y): (m, tx, ty) for m, w in WORLD.items() for x, y, tx, ty in w.get("forced_moves", [])}
FORCED[(MAPS["VICTORY_ROAD_3F"], 23, 15)] = (MAPS["VICTORY_ROAD_2F"], 22, 16)
LEDGES = {(dr, a, b) for dr, a, b in DATA["ledges"]}


class Navigator:
    def __init__(self):
        self.visits = {}
        self.edges = {}
        self.blocked = {}
        self.failures = {}
        self.attempt = None
        self.last_pos = None
        self.path = deque()
        self.target = None
        self.use_world = True
        self.cleared_objects = set()
        self.tile_overrides = {}
        self.can_surf = False
        self.can_cut = False
        self.story_blocks = set()
        self.live_map = None
        self.live_positions = []

    def update_live(self, snapshot, memory):
        self.live_map = snapshot.map
        self.live_positions = [(memory[0xC215 + i * 16] - 4, memory[0xC214 + i * 16] - 4)
                               for i in range(min(15, len(WORLD.get(snapshot.map, {}).get("objects", []))))]

    def update_story(self, snapshot):
        can_strength = any(70 in p.moves for p in snapshot.party)
        self.tile_overrides = {(m, x, y): tile for m, w in WORLD.items() for flag, x, y, tile in w.get("opened_tiles", [])
                               if event_set(snapshot.event_flags, flag) or (m != snapshot.map and can_strength)}
        self.can_surf = bool(snapshot.badges & 16 and any(57 in p.moves for p in snapshot.party))
        self.can_cut = bool(snapshot.badges & 2 and any(15 in p.moves for p in snapshot.party))
        drinks = {ITEMS[n] for n in ("FRESH_WATER", "SODA_POP", "LEMONADE")}
        self.story_blocks = set()
        if not all(event_set(snapshot.event_flags, flag) for flag in
                   ('EVENT_SEAFOAM3_BOULDER1_DOWN_HOLE', 'EVENT_SEAFOAM3_BOULDER2_DOWN_HOLE')):
            # The current pushes the player away from these apparent exits.
            self.story_blocks.add((MAPS['SEAFOAM_ISLANDS_B3F'], 15, 8))
            self.story_blocks.update((MAPS['SEAFOAM_ISLANDS_B4F'], x, y)
                                     for x in (20, 21) for y in (16, 17))
        if not snapshot.saffron_open and not any(item in drinks for item, qty in snapshot.items if qty):
            for name, coords in (("ROUTE_5_GATE", ((3, 3), (4, 3))),
                                 ("ROUTE_6_GATE", ((3, 2), (4, 2))),
                                 ("ROUTE_7_GATE", ((3, 3), (3, 4))),
                                 ("ROUTE_8_GATE", ((2, 3), (2, 4)))):
                self.story_blocks.update((MAPS[name], x, y) for x, y in coords)
        if not any(item == ITEMS["CARD_KEY"] and qty for item, qty in snapshot.items):
            for m, world in WORLD.items():
                for x, y, flag in world.get("locked_doors", []):
                    if not event_set(snapshot.event_flags, flag):
                        self.story_blocks.update((m, x + dx, y + dy) for dx in range(2) for dy in range(2))
        cleared = set()
        for index, (m, obj_id) in enumerate(DATA["toggle_objects"]):
            if obj_id >= len(WORLD[m]["objects"]):
                continue
            if index // 8 < len(snapshot.hidden_objects) and snapshot.hidden_objects[index // 8] & (1 << (index % 8)):
                obj = WORLD[m]["objects"][obj_id]
                cleared.add((m, obj[0], obj[1]))
        checks = (
            ("EVENT_GOT_DOME_FOSSIL", "MT_MOON_B2F", ("SUPER_NERD", "FOSSIL")),
            ("EVENT_GOT_HELIX_FOSSIL", "MT_MOON_B2F", ("SUPER_NERD", "FOSSIL")),
            ("EVENT_BEAT_ROUTE12_SNORLAX", "ROUTE_12", ("SNORLAX",)),
            ("EVENT_BEAT_ROUTE16_SNORLAX", "ROUTE_16", ("SNORLAX",)),
            ("EVENT_BEAT_CERULEAN_ROCKET_THIEF", "CERULEAN_CITY", ("ROCKET",)),
            ("EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI", "ROCKET_HIDEOUT_B4F", ("GIOVANNI",)),
            ("EVENT_BEAT_SILPH_CO_GIOVANNI", "SAFFRON_CITY", ("ROCKET",)),
        )
        for event, name, fragments in checks:
            if event_set(snapshot.event_flags, event):
                m = MAPS[name]
                cleared.update((m, o[0], o[1]) for o in WORLD[m]["objects"]
                               if any(fragment in o[4] for fragment in fragments))
        if cleared != self.cleared_objects:
            self.cleared_objects = cleared
            self.path.clear()

    def observe(self, pos, frame, walking=False, interrupted=False):
        if pos != self.last_pos:
            self.visits[pos] = self.visits.get(pos, 0) + 1
            self.last_pos = pos
        if not self.attempt or walking:
            return
        source, direction, started = self.attempt
        if interrupted:
            self.attempt = None
            return
        if pos != source:
            if self.use_world:
                world = WORLD.get(pos[0])
                if world and not (0 <= pos[1] < world["width"] and 0 <= pos[2] < world["height"]):
                    return
            if pos[0] == source[0] and abs(pos[1] - source[1]) + abs(pos[2] - source[2]) > 2:
                self.attempt = None
                return
            # Only record the observed direction. Ledges and warps are not reversible by assumption.
            self.edges.setdefault(source, {})[direction] = pos
            self.blocked.pop((source, direction), None)
            self.failures.pop((source, direction), None)
            self.attempt = None
        elif frame - started >= 20:
            key = (source, direction)
            self.failures[key] = self.failures.get(key, 0) + 1
            if self.failures[key] >= 2:
                self.blocked[key] = frame + 600
                self.path.clear()
            self.attempt = None

    def issued(self, pos, direction, frame):
        self.attempt = (pos, direction, frame)

    def restore(self):
        self.attempt = None
        self.last_pos = None
        self.path.clear()
        self.blocked.clear()
        self.failures.clear()

    def state_dict(self):
        return {"visits": [[list(p), n] for p, n in sorted(self.visits.items())],
                "edges": [[list(p), dr, list(q)] for p, edges in sorted(self.edges.items())
                          for dr, q in sorted(edges.items())]}

    def load_state_dict(self, data):
        self.visits = {tuple(p): n for p, n in data.get("visits", [])}
        self.edges = {}
        for p, dr, q in data.get("edges", []):
            if WORLD.get(p[0], {}).get("forced_moves"):
                continue
            self.edges.setdefault(tuple(p), {})[dr] = tuple(q)
        self.restore()

    @staticmethod
    def _tile(world, x, y):
        if 0 <= y < world["height"] and 0 <= x < world["width"]:
            return world["tiles"][y][x]
        return None

    @staticmethod
    def _warp(source, warp):
        x, y, destination, index = warp
        if [x, y] in WORLD.get(source, {}).get("inactive_warps", []):
            return None
        if destination == -1:
            parents = [m for m, w in WORLD.items() if index < len(w["warps"])
                       and w["warps"][index][2] == source]
            exterior = [m for m in parents if m < 37]
            parents = exterior or parents
            if len(parents) != 1:
                return None
            destination = parents[0]
        world = WORLD.get(destination)
        if world and 0 <= index < len(world["warps"]):
            wx, wy = world["warps"][index][:2]
            return destination, wx, wy
        return None

    def active_tile(self, world, x, y):
        return self.tile_overrides.get((MAPS[world["symbol"]], x, y), self._tile(world, x, y))

    def _directed_warp(self, source, warp, direction):
        world = WORLD[source]
        x, y = warp[:2]
        if world["tileset"] in ("MART", "POKECENTER") and y == world["height"] - 1:
            # The two exit mat squares only warp while facing out of the building.
            if direction != "down":
                return None
        return self._warp(source, warp)

    def neighbors(self, pos, frame):
        m, x, y = pos
        observed = self.edges.get(pos, {})
        for dr, q in sorted(observed.items()):
            dx, dy = DIRS[dr]
            current_world = WORLD.get(m) if self.use_world else None
            if current_world:
                here = self.active_tile(current_world, x, y)
                front = self.active_tile(current_world, x + dx, y + dy)
                ts = current_world["tileset"]
                if (ts, here, front) in PAIR_COLLISIONS or (ts, front, here) in PAIR_COLLISIONS:
                    continue
            q = FORCED.get((m, x + dx, y + dy), q)
            if q[0] != m and current_world:
                # Older samples can pair the new map with the indoor coordinates.
                for warp in current_world.get("warps", []):
                    if warp[:2] in ([x, y], [x + dx, y + dy]):
                        destination = self._directed_warp(m, warp, dr)
                        if destination and destination[0] == q[0]:
                            q = destination
                            break
            # A sampled step can land on a doorway before its map transition finishes.
            # Resolve those old observations through the doorway instead of creating a dead end.
            if q[0] == m and q != pos:
                target_world = WORLD.get(m, {})
                warp = next((w for w in target_world.get("warps", []) if w[:2] == list(q[1:])), None)
                if warp:
                    q = self._directed_warp(m, warp, dr) or q
            if self.blocked.get((pos, dr), 0) <= frame and q not in self.story_blocks and q[0] not in OPTIONAL_LIFTS:
                yield dr, q
        world = WORLD.get(m) if self.use_world else None
        if not world:
            return
        here = self.active_tile(world, x, y)
        positions = self.live_positions if self.live_map == m else []
        static_objects = {positions[i] if i < len(positions) else (o[0], o[1]) for i, o in enumerate(world["objects"])
                          if o[3] == "STAY" and o[2] not in ("SPRITE_POKE_BALL", "SPRITE_OAK", "SPRITE_BLUE")
                          and (m, o[0], o[1]) not in self.cleared_objects}
        for dr, (dx, dy) in DIRS.items():
            if dr in observed or self.blocked.get((pos, dr), 0) > frame:
                continue
            nx, ny = x + dx, y + dy
            if (m, nx, ny) in self.story_blocks:
                continue
            tile = self.active_tile(world, nx, ny)
            if tile is None:
                # Exit mats at an indoor map edge activate when walking outward.
                warp = next((w for w in world["warps"] if w[:2] == [x, y]), None)
                if warp:
                    target = self._directed_warp(m, warp, dr)
                    if target:
                        yield dr, target
                direction = {"up": "north", "down": "south", "left": "west", "right": "east"}[dr]
                for conn, dest, offset in world["connections"]:
                    if conn != direction or dest not in WORLD:
                        continue
                    other = WORLD[dest]
                    tx = x - offset * 2 if dx == 0 else other["width"] - 1 if dx < 0 else 0
                    ty = y - offset * 2 if dy == 0 else other["height"] - 1 if dy < 0 else 0
                    water = self.can_surf and other["tileset"] in WATER_TILESETS and self.active_tile(other, tx, ty) in (0x14, 0x32, 0x48)
                    if self.active_tile(other, tx, ty) in other["passable"] or water:
                        yield dr, (dest, tx, ty)
                continue
            if world["tileset"] == "OVERWORLD" and (dr, here, tile) in LEDGES:
                lx, ly = nx + dx, ny + dy
                if self.active_tile(world, lx, ly) in world["passable"]:
                    yield dr, (m, lx, ly)
                continue
            cuttable = self.can_cut and ((world["tileset"] == "OVERWORLD" and tile == 0x3D)
                                        or (world["tileset"] == "GYM" and tile == 0x50))
            water = self.can_surf and world["tileset"] in WATER_TILESETS and tile in (0x14, 0x32, 0x48)
            if (tile not in world["passable"] and not cuttable and not water) or (nx, ny) in static_objects:
                # Some exits activate by pressing into the boundary from the warp square.
                warp = next((w for w in world["warps"] if w[:2] == [x, y]), None)
                target = self._directed_warp(m, warp, dr) if warp else None
                if target:
                    yield dr, target
                continue
            ts = world["tileset"]
            if (ts, here, tile) in PAIR_COLLISIONS or (ts, tile, here) in PAIR_COLLISIONS:
                continue
            warp = next((w for w in world["warps"] if w[:2] == [nx, ny]), None)
            target = self._directed_warp(m, warp, dr) if warp else None
            if target and target[0] in OPTIONAL_LIFTS:
                continue
            yield dr, target or FORCED.get((m, nx, ny), (m, nx, ny))

    def distance_lookup(self, pos, frame, limit=60000):
        """Share one bounded search across goals while navigation state stays unchanged."""
        distances = {pos: 0}
        queue = deque([pos])
        expanded = 0

        def nearest(goals):
            nonlocal expanded
            goals = frozenset(goals)
            known = [distances[goal] for goal in goals if goal in distances]
            if known:
                return min(known)
            if not goals:
                return None
            while queue and expanded < limit:
                source = queue.popleft()
                depth = distances[source] + 1
                found = False
                for _, target in self.neighbors(source, frame):
                    if target not in distances:
                        distances[target] = depth
                        queue.append(target)
                        found |= target in goals
                expanded += 1
                if found:
                    return depth
            return None

        return nearest

    def route(self, pos, goals, frame, limit=60000):
        goals = frozenset(goals)
        if pos in goals:
            self.path.clear()
            return None
        if self.target == goals and self.path:
            while self.path and self.path[0][0] != pos:
                self.path.popleft()
            if self.path:
                source, dr, target = self.path[0]
                if (dr, target) in self.neighbors(pos, frame):
                    return dr
        self.target = goals
        self.path.clear()
        prev = {pos: None}
        queue = deque([pos])
        found = None
        while queue and len(prev) < limit:
            p = queue.popleft()
            if p in goals:
                found = p
                break
            for dr, q in self.neighbors(p, frame):
                if q not in prev:
                    prev[q] = (p, dr)
                    queue.append(q)
        while found is not None and prev[found] is not None:
            p, dr = prev[found]
            self.path.appendleft((p, dr, found))
            found = p
        return self.path[0][1] if self.path else None

    def explore(self, pos, frame, rng):
        options = list(self.neighbors(pos, frame))
        if options:
            least = min(self.visits.get(q, 0) for _, q in options)
            return rng.choice([dr for dr, q in options if self.visits.get(q, 0) == least])
        return rng.choice([dr for dr in DIRS if self.blocked.get((pos, dr), 0) <= frame] or list(DIRS))

    def guided(self, pos, goals, frame, rng, curiosity=0.12):
        """Follow the objective with occasional short, novelty-weighted detours."""
        forward = self.route(pos, goals, frame)
        if forward is None or curiosity <= 0 or rng.random() >= curiosity:
            return forward
        # Stay on this map during detours, avoiding accidental exits and warp loops.
        options = [(dr, q) for dr, q in self.neighbors(pos, frame)
                   if q[0] == pos[0] and dr != forward]
        if not options:
            return forward
        ahead = next((q for _, _, q in list(self.path)[6:12] if q[0] == pos[0]), None)
        if ahead is None:
            return forward
        distance = lambda q: abs(q[1] - ahead[1]) + abs(q[2] - ahead[2])
        weights = [(3 if distance(q) < distance(pos) else 1) / (1 + self.visits.get(q, 0))
                   for _, q in options]
        direction = rng.choices([dr for dr, _ in options], weights=weights, k=1)[0]
        self.path.clear()
        return direction
