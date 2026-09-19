"""Directed journeys reuse ordinary battle, menu, and field-move controls."""
from .battle import Decision
from .navigation import Navigator
from .progression import Goal
from .puzzles import MANSION_MAPS, VICTORY_MAPS, boulder_task
from .strategic import FACING, W_FACING, StrategicPolicy, tap, wait
from ..strategy_data import MAPS, WORLD, event_set


class TravelNavigator(Navigator):
    def __init__(self):
        super().__init__()
        self.journey = Navigator()

    def update_story(self, snapshot):
        super().update_story(snapshot)
        self.tile_overrides = {(m, x, y): tile for m, world in WORLD.items()
                               for flag, x, y, tile in world.get('opened_tiles', [])
                               if event_set(snapshot.event_flags, flag)}
        self.closed_passages = {(m, x, y) for m, world in WORLD.items()
                                for _, x, y, _ in world.get('opened_tiles', [])
                                if self.active_tile(world, x, y) not in world['passable']}

    def approach_next_map(self, snapshot, targets):
        """Approach a remote puzzle without pretending its gate is already open."""
        journey = self.journey
        journey.update_story(snapshot)
        journey.live_map = self.live_map
        journey.live_positions = self.live_positions
        journey.edges = self.edges
        journey.blocked = self.blocked
        pos = (snapshot.map, snapshot.x, snapshot.y)
        if journey.route(pos, targets, snapshot.frame) is None:
            return None
        entry = next((target for _, _, target in journey.path
                      if target[0] != snapshot.map), None)
        return self.route(pos, (entry,), snapshot.frame) if entry else None


class TravelPolicy(StrategicPolicy):
    """Stay on an external destination instead of choosing collecting projects."""

    def __init__(self, targets, seed=0):
        super().__init__(seed)
        self.nav = TravelNavigator()
        self.targets = tuple(targets)

    def _overworld(self, s, mem):
        self.goal = Goal('cable_travel', 'Travel to the Cable Club',
                         'Reach the Pokémon Center for the agreed exchange', self.targets)
        self.reason = self.goal.reason
        self.intent = None
        pos = (s.map, s.x, s.y)
        if pos in self.targets:
            return wait()
        if s.map in MANSION_MAPS:
            direction = self.mansion.route(s, self.targets, self.nav)
            if direction == 'switch':
                return tap('up', 4, 12) if mem[W_FACING] != FACING['up'] else tap('a')
        else:
            direction = self.nav.route(pos, self.targets, s.frame)
        # A usable exit takes precedence over resetting a dungeon's puzzle switches.
        if direction is not None:
            return self._move(s, mem, direction)
        if s.map in VICTORY_MAPS:
            task = boulder_task(s)
            direction = self.boulders.route(s, self.nav, task) if task else None
            if not direction and s.map == MAPS['VICTORY_ROAD_2F'] and event_set(
                    s.event_flags, 'EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH2'):
                direction = self.boulders.route(s, self.nav, ('BOULDER3', (9, 16)))
            if not direction and s.map == MAPS['VICTORY_ROAD_3F'] and s.x >= 24 and s.y >= 7:
                direction = self.boulders.route(s, self.nav, ('BOULDER3', (22, 10)))
            if direction:
                if not mem[0xD728] & 1:
                    partner = next((i for i, mon in enumerate(s.party) if 70 in mon.moves), None)
                    if partner is None:
                        raise ValueError('The route to the Cable Club needs a partner with Strength')
                    self.field_move = 'STRENGTH'
                    self.intent = Decision('field', partner, reason='Open the route to the Cable Club with Strength')
                    self.intent_since = s.frame
                    return tap('start')
                self.nav.issued(pos, direction, s.frame)
                return tap(direction, 16, 16)
            if s.map == MAPS['VICTORY_ROAD_2F']:
                targets = ((MAPS['VICTORY_ROAD_3F'], 27, 15),
                    (MAPS['VICTORY_ROAD_3F'], 23, 7),)
            elif s.map == MAPS['VICTORY_ROAD_3F']:
                targets = ((MAPS['VICTORY_ROAD_2F'], 22, 16),)
            else:
                targets = ()
            direction = self.nav.route(pos, targets, s.frame) if targets else None
            if direction:
                return self._move(s, mem, direction)
        direction = self.nav.approach_next_map(s, self.targets)
        if direction is not None:
            return self._move(s, mem, direction)
        if any(until > s.frame for (source, _), until in self.nav.blocked.items() if source[0] == s.map):
            self.reason = 'Wait for a temporary obstacle before retrying the route'
            return wait()
        raise ValueError('The route to the Cable Club is blocked by an unresolved obstacle')
