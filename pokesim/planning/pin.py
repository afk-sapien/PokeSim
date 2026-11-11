"""The next activity a manager sets, shared by both generations.

A pin names one key from the goal catalogue (planning/catalogue.py). A goal that can run now runs next,
and the decide pipeline ranks it after upkeep and before every other source's goals for one run of that
goal. A goal that cannot run now waits with why (``Pin.parked``) and starts once that clears. The pin
lives in memory only. It clears when the goal ends, when a manager cancels it, when a save loads and
when the game restarts. Nothing is queued behind it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .catalogue import tier_name, why

# Why a key cannot be pinned when the planner knows no better reason.
UNAVAILABLE = 'not available now'
STUCK = 'stuck'
# Why a key that is not in the catalogue cannot be pinned.
CHOOSE = 'Choose a goal from the list'
# The most goals the picker shows. The rest are found by searching for their name.
LIMIT = 30


@dataclass
class Pin:
    key: str
    label: str
    # True once the planner picked the pinned goal. Its end then clears the pin.
    started: bool = False
    # Why the pinned goal cannot run now, a planning.decide.Failure, None when it can. The API state
    # carries its kind and detail, so the manager sees why the pin waits.
    parked: object = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        """The pin ``to_dict`` gave, as a replay sets the one a trace segment began with."""
        from .decide import Failure
        parked = data.get('parked')
        return cls(data['key'], data['label'], bool(data.get('started')),
                   None if parked is None else Failure(parked['kind'], parked['detail']))


def entry(key, label, tier, failure=None):
    """One row of the goal list a manager picks from. A goal that waits has ``feasible`` False and why
    in ``why_not``, and a goal its source left out before pricing it has no tier."""
    return {'key': key, 'label': label, 'tier': tier_name(tier), 'feasible': failure is None, 'why_not': why(failure)}


def grouped(rows, query=None, limit=LIMIT):
    """The picker's rows from the planner's ranked options, best first, and then the goals that wait.

    ``rows`` holds ``(key, group, label, tier)`` for each option, best first, and then ``(key, group,
    label, tier, failure)`` for each goal that waits. Options that serve one thing a manager wants, such as
    every place a species can be caught, share a group. Each group is listed once, under its best option's
    key and label, so pinning it runs that option. A label already listed is not listed again. ``query``
    keeps the groups whose label holds it, and ``limit`` keeps the best of them.
    """
    seen, labels, goals = set(), set(), []
    needle = (query or '').strip().casefold()
    for key, group, label, tier, *failure in rows:
        if group in seen or label in labels:
            continue
        seen.add(group)
        labels.add(label)
        if needle and needle not in label.casefold():
            continue
        goals.append(entry(key, label, tier, *failure))
    return goals if limit is None else goals[:limit]


def listing(goals, pin, reason=None):
    """The ``api/goals`` payload: the current candidates, the active pin and why the list is empty."""
    body = {'goals': goals, 'pin': pin.to_dict() if pin else None}
    if reason and not goals:
        body['reason'] = reason
    return body


def gave_up(label, reason):
    """The journal row for a pin the planner dropped."""
    return {'type': 'plan', 'title': f'Gave up on {label}: {reason}',
            'body': 'The planner goes back to its own order.', 'priority': 2, 'tags': 'pushpin'}
