"""Short, verified ground-item detours that preserve the main expedition."""
from copy import deepcopy

from .progression import object_goal
from ..ground_items import ground_item
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

    def load(self, data):
        for key in self.state_dict():
            if key in data:
                setattr(self, key, deepcopy(data[key]))

    @staticmethod
    def has_space(s, item):
        bag = dict(s.items)
        if item in bag:
            return bag[item] < 99
        return len(bag) < 20

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

    def observe(self, s, elapsed):
        self.retry = {key: until for key, until in self.retry.items() if until > elapsed}
        if not self.active:
            return
        target = self.active
        if self.hidden(s, target):
            self.completed = list(dict.fromkeys(self.completed + [target['key']]))
            self.history = (self.history + ['Collected ' + target['name']])[-8:]
            self.active = None
        elif elapsed >= target['expires'] or s.map != target['map'] or not self.has_space(s, target['item']):
            self.defer(elapsed, 'Pickup unavailable or detour budget reached')

    def defer(self, elapsed, reason):
        if self.active:
            self.retry[self.active['key']] = elapsed + 18000
            self.history = (self.history + [reason + ': ' + self.active['name']])[-8:]
            self.active = None

    def goal(self, target):
        return object_goal('collect_pickup', 'Pick up ' + target['name'],
                           'Collect a nearby ground item, then resume the expedition',
                           WORLD[target['map']]['symbol'], target['fragment'])

    def choose(self, s, nav, main, elapsed):
        if (not nav.use_world or not s.party or s.in_battle
                or main.key.startswith(('heal', 'restock', 'party_', 'teach_', 'league', 'champion'))):
            return None
        if self.active:
            return self.goal(self.active)
        if elapsed < self.next_scan:
            return None
        self.next_scan = elapsed + 300
        world = WORLD.get(s.map, {})
        candidates = []
        for index, obj in enumerate(world.get('objects', [])):
            item = ground_item(obj)
            if not item or abs(obj[0] - s.x) + abs(obj[1] - s.y) > 10:
                continue
            target = dict(item, map=s.map, object=index, fragment=obj[4], key=f'{s.map}:{index}')
            if target['key'] in self.completed or self.retry.get(target['key'], 0) > elapsed:
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
        self.active = min(candidates, key=lambda row: row[:2])[2]
        self.active['expires'] = elapsed + 1800
        nav.path.clear()
        return self.goal(self.active)
