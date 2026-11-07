"""The next activity a manager sets, shared by both generations.

A pin names one key from the planner's own candidate list. The arbiter ranks it first after upkeep for
one run of that goal. The pin lives in memory only. It clears when the goal ends, when a manager
cancels it, when a save loads and when the game restarts. Nothing is queued behind it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

# Why a key cannot be pinned when the planner knows no better reason.
UNAVAILABLE = 'not available now'
STUCK = 'stuck'


@dataclass
class Pin:
    key: str
    label: str
    # True once the planner picked the pinned goal. Its end then clears the pin.
    started: bool = False

    def to_dict(self):
        return asdict(self)


def entry(key, label, tier):
    """One row of the goal list a manager picks from."""
    return {'key': key, 'label': label, 'tier': getattr(tier, 'name', str(tier)).lower()}


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
