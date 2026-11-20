"""Walk the Generation II policy toward its goal and handle missing routes."""
from __future__ import annotations

from dataclasses import replace

from ...runtime.policy import Action, Hold
from ..menus import Register, registered
from ..navigation import DIRS, HeldWalk
from .reads import Reads
from .state import STUCK_WAITS, Goal


class NavigationPart:
    """Walking, waiting and the approach to people and goals."""

    STRANDED_LIMIT = 60
    # Water collision, which Surf crosses and the Bicycle cannot.
    WATER = (0x21, 0x29)

    def unloaded(self, snapshot):
        """Whether the cartridge restarted to its opening while memory still shows the save it read.

        The main menu reads the save's party and place to describe it, so the run looks started.
        No map is loaded until Continue, though, and every loaded map has a width. A live Crystal run
        reset in the Battle Tower walked into the blank walls of that unloaded map for hours.
        """
        return snapshot.started and not snapshot.in_battle and snapshot.map_width == 0

    def battle_starting(self, snapshot):
        """Whether the wild battle script has begun while the battle itself has not.

        The battle transition draws over the map blocks the plan reads, so a plan made then sees no
        encounter tiles. A postgame hunt took that for an unloaded map and waited, and the goal stayed
        on that wait through the whole battle, so most of a Gold or Silver postgame hunt was counted
        as waiting. The goal that walked into the battle carries on through it instead.
        """
        return bool(snapshot.script_running and snapshot.wild_pending)

    # Goals that wait on purpose for game time to pass: the clock-wait patrol, and a Crystal phone wait
    # by a Pokémon Center PC (item_sources.phones), which ends with the call or its own budget.
    WAIT_GOALS = frozenset(('collection_idle', 'collection_phone_wait'))

    def idle(self, snapshot):
        """Whether the run stands on its wait tile: the clock-wait tile between two patrol steps, or the
        spot by the PC where a phone wait stands.

        The emulator does not treat this pause as a stuck run, since the wait only ends when enough game
        time has passed. Reloading cannot hurry a call and rewinds the phone's call timer.
        """
        goal = self.goal
        return (self.waiting(snapshot) and not snapshot.in_battle
                and (goal.x, goal.y) == (snapshot.x, snapshot.y))

    def waiting(self, snapshot):
        """Whether the run waits on its goal's map on purpose, walking the grass until the cartridge clock
        opens new work or walking to the phone wait's spot.

        The wait earns no new progress, so the emulator does not reload it for lack of progress, but a
        wait that stops moving away from its tile is still caught by the stuck and frozen screen checks.
        """
        goal = self.goal
        return (goal is not None and goal.key in self.WAIT_GOALS and self.menu is None
                and self.data.map_ids.get(goal.map_name) == snapshot.map)

    def person(self, snapshot, key, label, map_name, script):
        mid = self.data.map_ids[map_name]
        entry = self.data.maps[mid]
        matches = [(i, obj) for i, obj in enumerate(entry['objects'], 1) if obj['script'] == script]
        index, obj = next(((i, obj) for i, obj in matches
                           if obj['event'] not in self.data.events or not snapshot.event(obj['event'])), matches[0])
        x, y = next(((x, y) for i, x, y in snapshot.objects if i == index), (obj['x'], obj['y'])) if snapshot.map == mid else (obj['x'], obj['y'])
        grid = self.nav.collision(replace(snapshot, map=mid), self.memory if snapshot.map == mid else None)
        choices, approaches = [], []
        for face, (dx, dy) in DIRS.items():
            for distance in (1, 2):
                point = (x - dx * distance, y - dy * distance)
                if not (0 <= point[0] < entry['width'] and 0 <= point[1] < entry['height']):
                    continue
                if distance == 2 and grid[(y - dy) * entry['width'] + x - dx] not in (0x90, 0x98):
                    continue
                if not self.nav.passable(grid[point[1] * entry['width'] + point[0]]):
                    continue
                approaches.append((*point, face))
                path = self.reachable_path(snapshot, mid, point)
                if path is not None:
                    choices.append((len(path), point[0], point[1], face))
        if not choices:
            # Every approach is blocked for now. The walk takes one the map regions join, so it waits on the
            # people in the way. The tile below is the last resort, and a walk with no route to it is recorded.
            cut, surf = bool(snapshot.badges & 2), bool(snapshot.badges & 8)
            x, y, face = next(((px, py, face) for px, py, face in approaches
                               if self.nav.regions.route(snapshot, mid, [(px, py)], cut=cut, surf=surf) is not None),
                              (x, y + 1, 'up'))
            return Goal(key, label, map_name, x, y, face)
        _, x, y, face = min(choices)
        return Goal(key, label, map_name, x, y, face)

    def reachable_path(self, snapshot, mid, point):
        """Path to a tile, or None when it cannot be reached right now.

        On the current map, a failed local search means the tile is blocked (for example by a
        person standing on it). regions.route then answers [] for 'same region, use local nav',
        which must not be read as 'already there'.
        """
        same_map = snapshot.map == mid
        path = self.nav.local(snapshot, [point], self.memory) if same_map else None
        if path is not None:
            return path
        route = self.nav.regions.route(snapshot, mid, [point], cut=bool(snapshot.badges & 2),
                                       surf=bool(snapshot.badges & 8))
        if same_map and route == []:
            return None
        return route

    def detour(self, snapshot, mem, memory, target, surf):
        """A path for a goal with no walking route, and whether it only leads to a waypoint."""
        from ..flight import outside
        # Fly only works outside and within one region, so a goal with no walking route is reached by
        # walking out, or on into the other region, first.
        exit_point = outside(self, snapshot, mem, target)
        if exit_point is not None:
            path = self.nav.toward(snapshot, exit_point[0], [exit_point[1]], memory, surf=surf)
            if path is not None:
                return path, True
        if (self.goal.key != 'sudowoodo' and snapshot.event('EVENT_FOUGHT_SUDOWOODO')
                and not snapshot.event('EVENT_ROUTE_36_SUDOWOODO')):
            # A returned Sudowoodo walls off Route 36. With no other way round, battle it even without a ball.
            tree = self.nav.toward(snapshot, self.data.map_ids['ROUTE_36'], [(35, 10)], memory, surf=surf)
            if tree is not None:
                goal = Goal('sudowoodo', 'Clear the moving tree off Route 36', 'ROUTE_36', 35, 10, 'up')
                ballot = getattr(self, 'ballot', None)
                self.goal = goal if ballot is None else ballot.errand(goal, 'sudowoodo')
                return tree, False
        if snapshot.map == self.data.map_ids.get('SLOWPOKE_WELL_B1F'):
            # The Slowpoke Well boulder can shut the player in on the ladder side, so push it out of the way
            # of the walk's first warp.
            from ..quests import well_boulder
            walk = self.nav.walk(snapshot, target)
            push = well_boulder(self, snapshot, Goal, walk[0][2][0]) if walk else None
            stand = None if push is None else self.nav.toward(snapshot, snapshot.map, [(push.x, push.y)], memory, surf=surf)
            if stand is not None:
                ballot = getattr(self, 'ballot', None)
                self.goal = push if ballot is None else ballot.errand(push, 'well_boulder')
                return stand, False
        return None, False

    def follow(self, snapshot, memory, path, waypoint, surf):
        """Walk the path, or handle having none. None once the goal itself is reached."""
        if path is not None:
            self.unreachable_waits = 0
        if path:
            # Walking toward a waypoint is not progress toward the goal. Stepping back out of a door the
            # stranded search walked into must not restart the count, or the policy never reports it.
            if not waypoint:
                self.stranded = 0
            return self.walk(snapshot, memory, path)
        if path is None or waypoint:
            # Standing on a waypoint Fly did not leave from is no better than having no route.
            return self.stranded_action(snapshot, memory, surf)
        return None

    def stranded_action(self, snapshot, memory, surf):
        """No route to the goal exists from here, so end the turn and record a failed attempt on it.

        When the map's regions still join the goal, only a person or a screen is in the way, so the walk
        looks around for a while first. Neither case asks for a reload, which replayed the same missing
        route after a full stall timeout and fed the stall watchdog.
        """
        self.stranded += 1
        if self.stranded >= self.STRANDED_LIMIT or not self.joined(snapshot, surf):
            self.stranded = 0
            return self.no_route(snapshot)
        path = self.nav.explore(snapshot, memory, surf=surf)
        if path:
            self.mode = 'finding another approach'
            return self.walk(snapshot, memory, path)
        # Briefly wait for moving people or map transitions before replanning, but do not wait
        # silently forever: after a long run of waits the objective is reported as stuck.
        self.unreachable_waits += 1
        if self.unreachable_waits >= STUCK_WAITS:
            self.mode = f'Stuck: cannot reach {self.goal.label}'
        return Action(None, 0, 24)

    def joined(self, snapshot, surf):
        """Whether the map regions join the player to the goal's tile, people and screens aside.

        A player in no region is between tiles. In a ledge jump the coordinates read the wall tile jumped
        over until the player lands. The regions say nothing about the route from there, so the walk looks
        around and counts as stranded rather than record a missing route that is there one step later.
        """
        cut = bool(snapshot.badges & 2) and any(15 in mon.moves for mon in snapshot.party)
        regions = self.nav.regions
        if not regions.memberships(snapshot.map, (snapshot.x, snapshot.y), cut, surf, arrive=True):
            return True
        return regions.route(snapshot, self.data.map_ids[self.goal.map_name], [(self.goal.x, self.goal.y)],
                             cut=cut, surf=surf) is not None

    def unreachable(self):
        """The walks that found no route lately (planning/unreachable.py), kept in the monitor's tables."""
        from ...planning.unreachable import FRAMES, NoRoute
        return NoRoute(self.monitor_tables, FRAMES)

    def no_route_waiting(self, goal):
        """Whether ``goal`` found no route lately and waits before it is walked again."""
        return goal is not None and self.unreachable().waiting(goal.key, goal.map_name, [(goal.x, goal.y)], self.clock)

    def no_route(self, snapshot):
        """End the turn of a walk with no route and record the failed attempt, with its map and target."""
        goal = self.goal
        self.unreachable().record(goal.key, goal.map_name, [(goal.x, goal.y)], self.clock, snapshot.map_name)
        self.unreachable_waits = 0
        self.mode = f'No route to {goal.label}'
        return Action(None, 0, 24)

    def step_off(self, snapshot, memory, surf):
        """Step off the tile the player stands on, or None when every side is blocked."""
        # Standing on stairs does not take them. A cancelled trade can leave the player on the
        # Pokémon Center 2F stairs, and pressing A there changes nothing. The next step walks back on.
        step = next((direction for direction, (dx, dy) in DIRS.items()
                     if self.nav.local(snapshot, [(snapshot.x + dx, snapshot.y + dy)], memory, surf=surf) == [direction]),
                    None)
        return self.walk(snapshot, memory, [step]) if step else None

    def walk(self, snapshot, memory, path):
        # A Tower preparation walks outside a decision, with memory of its own.
        reads = getattr(self, 'reads', None)
        if reads is None or reads.memory is not memory:
            reads = Reads(memory, self.data.game)
        surf = bool(snapshot.badges & 8) and any(57 in mon.moves for mon in snapshot.party)
        dx, dy = DIRS[path[0]]
        entry = self.data.maps[snapshot.map]
        nx, ny = snapshot.x + dx, snapshot.y + dy
        cut_tree = (0 <= nx < entry['width'] and 0 <= ny < entry['height']
                    and self.nav.collision(snapshot, memory)[ny * entry['width'] + nx] in (0x12, 0x1A))
        # The screen state is read last, only for a step onto water.
        water = (surf and 0 <= nx < entry['width'] and 0 <= ny < entry['height']
                 and self.nav.collision(snapshot, memory)[ny * entry['width'] + nx] in self.WATER
                 and reads.ui.movement_state not in (4, 8))
        obstacle = (surf and 0 <= nx < entry['width'] and 0 <= ny < entry['height']
                    and self.nav.collision(snapshot, memory)[ny * entry['width'] + nx] in ((0x24, 0x2C, 0x33) if path[0] == 'up' else (0x24, 0x2C)))
        if cut_tree or water or obstacle or (nx, ny) in {(x, y) for _, x, y in snapshot.objects}:
            key = (snapshot.map, snapshot.x + dx, snapshot.y + dy)
            if self.interaction == key and reads.ui.facing == path[0]:
                return Action('a', 8, 36)
            self.interaction = key
            return Action(path[0], 8, 16)
        self.interaction = None
        state = reads.ui.movement_state
        ride = self.mount(snapshot, memory, path) if state == 0 else None
        if ride:
            return ride
        self.nav.issued(snapshot, path[0])
        tiles = self.held_tiles(snapshot, memory, path, reads)
        if tiles:
            stop = HeldWalk(self.nav, memory, self.data.game, snapshot.frame, path[0], tiles)
            return Hold(path[0], 16 * tiles + 32, 16, stop=stop)
        # The Bicycle covers a tile in 8 frames, so a 16-frame press would start a second step. A press in a
        # new direction turns the rider first, and an 8-frame press ends in that turn.
        if state == 1 and reads.ui.facing == path[0]:
            return Action(path[0], 8, 8)
        return Action(path[0], 16, 16)

    # The map environments the game lets the Bicycle out in (BikeFunction).
    BIKE_ENVIRONMENTS = frozenset(('ROUTE', 'TOWN', 'CAVE', 'GATE'))
    # Getting on costs about what the Bicycle saves over this many steps, so a shorter walk goes on foot.
    MOUNT_STEPS = 20

    def mount(self, snapshot, memory, path):
        """The press that gets on an owned Bicycle when the walk ahead on this map keeps to land for
        MOUNT_STEPS, or None to walk.

        The game also wants the player on plain floor, not grass. Puzzle maps are walked, as their pushes
        and slides were planned one walking step at a time. The Bicycle is registered to SELECT once, so
        each later mount is one press with no message. A press that leaves the player on foot is not
        repeated on the same tile.
        """
        from ..errands import puzzle_maps
        bike = self.data.items.get('BICYCLE')
        entry = self.data.maps[snapshot.map]
        if (len(path) < self.MOUNT_STEPS or bike not in dict(snapshot.items)
                or entry.get('environment') not in self.BIKE_ENVIRONMENTS or snapshot.map in puzzle_maps(self.data)):
            return None
        grid = self.nav.collision(snapshot, memory)
        width, height = entry['width'], entry['height']
        x, y = snapshot.x, snapshot.y
        if grid[y * width + x] & 0x0F:
            return None
        for button in path[:self.MOUNT_STEPS]:
            dx, dy = DIRS[button]
            x, y = x + dx, y + dy
            if not (0 <= x < width and 0 <= y < height) or grid[y * width + x] in self.WATER:
                return None
        if registered(memory, self.data) == bike:
            spot = (snapshot.map, snapshot.x, snapshot.y)
            if getattr(self, 'select_spot', None) == spot:
                return None
            self.select_spot = spot
            return Action('select', 8, 24)
        task = Register(bike)
        if not self.allowed(task, snapshot):
            return None
        self.menu = task
        return Action(None, 0, 24)

    # A straight run of at least HELD_MIN tiles is walked with one held press, at most HELD_TILES long.
    HELD_MIN, HELD_TILES = 3, 8
    # Floor and both grasses, the only tiles a held press walks onto.
    PLAIN = frozenset((0x00, 0x14, 0x18))

    def held_tiles(self, snapshot, memory, path, reads):
        """How many of the path's first tiles one held press walks, or 0 where each tile is its own press.

        Only a walk on foot or on the Bicycle outdoors or in a cave holds, and never on a puzzle or ice map.
        A held press ends on coordinates, so the Bicycle's 8-frame tiles stop in the same place. Each tile held
        onto is floor or grass with no warp, person or known wall, and so is the tile past it in bounds
        with no warp, person or ledge, so a press that comes up a tile late still lands somewhere plain.
        """
        from ..errands import puzzle_maps
        entry = self.data.maps[snapshot.map]
        run = 0
        while run < min(len(path), self.HELD_TILES) and path[run] == path[0]:
            run += 1
        if (run < self.HELD_MIN or entry.get('environment') in ('INDOOR', 'GATE')
                or snapshot.map in puzzle_maps(self.data) or reads.ui.movement_state not in (0, 1)):
            return 0
        dx, dy = DIRS[path[0]]
        width, height = entry['width'], entry['height']
        grid = self.nav.collision(snapshot, memory)
        warps = {(warp['x'], warp['y']) for warp in entry['warps']}
        people = {(x, y) for _, x, y in snapshot.objects}
        tiles = 0
        for k in range(1, run + 1):
            x, y = snapshot.x + dx * k, snapshot.y + dy * k
            past = (x + dx, y + dy)
            if (not (0 <= x < width and 0 <= y < height and 0 <= past[0] < width and 0 <= past[1] < height)
                    or grid[y * width + x] not in self.PLAIN or (x, y) in warps or (x, y) in people
                    or (snapshot.map, x, y) in self.nav.blocked or past in warps or past in people
                    or 0xA0 <= grid[past[1] * width + past[0]] <= 0xAF):
                break
            tiles = k
        return tiles if tiles >= self.HELD_MIN else 0
