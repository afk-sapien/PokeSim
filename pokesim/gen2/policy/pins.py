"""List, pin and describe the goals a manager can set for the Generation II policy."""
from __future__ import annotations

from ...planning import catalogue as listing
from pokecore.gen2.ram import Memory
from .state import STUCK_WAITS, Goal


class PinPart:
    """Pinned goals, the goal catalogue and the policy's details."""

    def describe(self):
        return f'strategic ({self.mode})'

    def goals(self, snapshot, query=None, every=False):
        """The goals a manager can set as the next activity, and why the list is empty. ``query`` is as
        in pin.grouped. The list keeps the picker's limit unless ``every`` asks for all of it."""
        from ...planning.pin import LIMIT
        from ..collection import goal_list
        if snapshot is None or self.memory is None:
            return [], 'Not available now'
        return goal_list(self, snapshot, Memory(self.memory, self.data), Goal, query, None if every else LIMIT)

    def pin_goal(self, snapshot, key):
        """Set ``key``, a catalogue goal's key, as the next activity. A goal that cannot run now waits with
        why in ``Pin.parked``. A ValueError says why ``key`` cannot be set."""
        from ...planning.decide import Failure
        from ...planning.pin import CHOOSE, Pin
        from ..collection import catalogue
        if snapshot is None or self.memory is None:
            raise ValueError('Not available now')
        rows, reason = catalogue(self, snapshot, Memory(self.memory, self.data), Goal)
        match = next((row for row in rows if row['key'] == key), None)
        if match is None:
            raise ValueError(reason or CHOOSE)
        why = match['why_not']
        parked = None if why is None else Failure(why['kind'], why['detail'])
        self.pin = Pin(key, match['title'], started=parked is None and getattr(self, 'ladder_pick', None) == key,
                       parked=parked)
        return self.pin

    def unpin_goal(self):
        self.pin = None

    def restore_pin(self, pin):
        self.pin = pin

    def drop_pin(self):
        """Drop the pin. Returns the label dropped, or None with no pin."""
        label = self.pin.label if self.pin else None
        self.pin = None
        return label

    def catalogue(self, snapshot, query=None, limit=listing.LIMIT):
        """The goal catalogue (planning/catalogue.py). The survey behind it undoes every write."""
        from ..collection import GOAL_PARAM, RUNGS, catalogue
        kinds = [listing.kind(name, about, [GOAL_PARAM]) for name, about in RUNGS.items()]
        if snapshot is None or self.memory is None:
            rows, reason = [], 'Not available now'
        else:
            rows, reason = catalogue(self, snapshot, Memory(self.memory, self.data), Goal)
        return listing.body(2, kinds, rows, self.pin, reason, query, limit)

    def goal_record(self):
        """The goal that runs now in the shape both generations share (docs/design/typed-goals.md
        section 4). The offer's kind and tier count only while the goal is still the one its ballot chose."""
        goal = self.goal
        if goal is None:
            return None
        offer = getattr(self, 'goal_offer', None)
        offer = offer if offer is not None and offer.goal is goal else None
        return {'key': goal.key, 'kind': None if offer is None else offer.kind, 'title': goal.label,
                'tier': None if offer is None else listing.tier_name(offer.candidate.tier),
                'done': False, 'stop': None, 'parked': None if offer is None else listing.why(offer.parked)}

    def details(self):
        from ..collection import active_target
        from ..marathon import details as marathon_details
        return {'action': self.mode, 'decisions': self.decisions, 'starter': self.starter,
                'pin': self.pin.to_dict() if self.pin else None, 'goal': self.goal_record(),
                'milestones': dict(self.completed), 'recoveries': self.recoveries, 'visited_tiles': len(self.nav.visits),
                'objective': {'key': self.goal.key, 'label': self.goal.label, 'reason': self.goal.label} if self.goal else {},
                'collection': {'version': self.data.game, 'dex_total': 251,
                               'phase': self.collection.get('phase', 'journey'),
                               'hunting': (active_target(self) or {}).get('species'),
                               'npc_trades': [row['index'] for row in self.collection.get('npc_trades', [])],
                               'marathon': marathon_details(self)},
                'blocked': self.unreachable_waits >= STUCK_WAITS,
                'reason': self.goal.label if self.goal else 'Start the adventure'}
