"""Short, verified ground-item detours that preserve the main expedition."""
from copy import deepcopy
from functools import partial

from .progression import object_goal
from .shopping import DUNGEON_KEY_SLOTS, DUNGEONS, SAFARI_INTERIOR, SAFARI_PRIZE_SLOTS
from ..ground_items import ground_item
from ..runtime.supervision import PICKUP_DETOUR, PICKUP_RETRY, PICKUP_SCAN
from ..strategy_data import DATA, WORLD, object_hidden




class Pickups:
    def __init__(self):
        self.active = None
        self.completed = []
        self.retry = {}
        self.next_scan = 0
        self.history = []

    def state_dict(self):
        return deepcopy({key: getattr(self, key) for key in
                         ('active', 'completed', 'retry', 'next_scan', 'history')})

    def load(self, data, shift=0):
        """``shift`` moves an older save's times onto the PlayClock (Collection.clock_shift)."""
        for key in self.state_dict():
            if key in data:
                setattr(self, key, deepcopy(data[key]))
        if shift:
            self.retry = {key: until + shift for key, until in self.retry.items()}
            self.next_scan += shift
            if self.active and 'expires' in self.active:
                self.active['expires'] += shift

    @staticmethod
    def has_space(s, item):
        bag = dict(s.items)
        if item in bag:
            return bag[item] < 99
        # The Safari Zone keeps two entries free for its prizes, so a pickup never forces a trip out to sell.
        # A dungeon keeps two free for its story items the same way.
        if s.map in SAFARI_INTERIOR:
            return len(bag) < 20 - SAFARI_PRIZE_SLOTS
        return len(bag) < (20 - DUNGEON_KEY_SLOTS if s.map in DUNGEONS else 20)

    @staticmethod
    def hidden(s, target):
        try:
            offset = DATA['toggle_objects'].index([target['map'], target['object']])
            if offset // 8 >= len(s.hidden_objects):
                return None
            return object_hidden(s, target['map'], target['object'])
        except ValueError:
            # An untracked object cannot provide reliable pickup confirmation.
            return None

    def observe(self, s, now):
        """``now`` is the PlayClock frame, which a reload never moves back."""
        self.retry = {key: until for key, until in self.retry.items() if until > now}
        if not self.active:
            return
        target = self.active
        if self.hidden(s, target):
            self.completed = list(dict.fromkeys(self.completed + [target['key']]))
            self.history = (self.history + ['Collected ' + target['name']])[-8:]
            self.active = None
        elif now >= target['expires'] or s.map != target['map'] or not self.has_space(s, target['item']):
            self.defer(now, 'Pickup unavailable or detour budget reached')

    def defer(self, now, reason):
        if self.active:
            self.retry[self.active['key']] = PICKUP_RETRY.until(now)
            self.history = (self.history + [reason + ': ' + self.active['name']])[-8:]
            self.active = None

    def goal(self, target):
        return object_goal('collect_pickup', 'Pick up ' + target['name'],
                           'Collect a nearby ground item, then resume the expedition',
                           WORLD[target['map']]['symbol'], target['fragment'])

    def choose(self, s, nav, main, now):
        """The pickup goal against ``main``, starting a new pickup at once."""
        picked = self.pick(s, nav, main, now)
        if picked is None:
            return None
        goal, start = picked
        if start is not None:
            start()
        return goal

    def pick(self, s, nav, main, now):
        """The pickup against ``main``, the goal it is handed, as ``(goal, start)``, or None.

        A new pickup is found here but not started: ``start`` makes it the pickup under way, which the
        overworld decision runs only when the step ends with the pickup running (decide pipeline rule A).
        The scan and its wait are observations, so they are written here. A pickup under way has nothing
        to start.
        """
        if (not nav.use_world or not s.party or s.in_battle
                or main.key.startswith(('heal', 'restock', 'party_', 'teach_', 'league', 'champion'))):
            return None
        if self.active:
            return self.goal(self.active), None
        if now < self.next_scan:
            return None
        self.next_scan = PICKUP_SCAN.until(now)
        world = WORLD.get(s.map, {})
        candidates = []
        for index, obj in enumerate(world.get('objects', [])):
            item = ground_item(obj)
            if not item or abs(obj[0] - s.x) + abs(obj[1] - s.y) > 10:
                continue
            target = dict(item, map=s.map, object=index, fragment=obj[4], key=f'{s.map}:{index}')
            if target['key'] in self.completed or self.retry.get(target['key'], 0) > now:
                continue
            if self.hidden(s, target) is not False or not self.has_space(s, item['item']):
                continue
            goal = self.goal(target)
            pos = (s.map, s.x, s.y)
            direction = nav.route(pos, goal.targets, s.frame)
            if pos in goal.targets or (direction and len(nav.path) <= 16
                                      and all(start[0] == s.map and end[0] == s.map for start, _, end in nav.path)):
                candidates.append((0 if pos in goal.targets else len(nav.path), index, target))
        if not candidates:
            return None
        target = min(candidates, key=lambda row: row[:2])[2]
        return self.goal(target), partial(self._start, target, nav, now)

    def _start(self, target, nav, now):
        self.active = target
        target['expires'] = PICKUP_DETOUR.until(now)
        nav.path.clear()
