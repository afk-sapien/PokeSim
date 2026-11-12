"""Walk the Generation II policy toward its goal and handle missing routes."""
from __future__ import annotations

from dataclasses import replace

from ...runtime.policy import Action
from ..navigation import DIRS
from .reads import Reads
from .state import STUCK_WAITS, Goal


class NavigationPart:
    """Walking, waiting and the approach to people and goals."""

    STRANDED_LIMIT = 60

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
                 and self.nav.collision(snapshot, memory)[ny * entry['width'] + nx] in (0x21, 0x29)
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
        self.nav.issued(snapshot, path[0])
        return Action(path[0], 16, 16)
