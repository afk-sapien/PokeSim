"""The goal catalogue, shared by both generations (docs/design/typed-goals.md section 4).

The catalogue is plain data. It lists the kinds of goal a director can ask for, with their params, and
the goals open now or waiting, each with why it waits. Each generation's planner draws the goals from the
same offers draw that feeds the decide pipeline, on a copy of the RNG, and writes no state. Cost and worth
are the candidate's own ``expected_frames`` and ``value``, so a goal its source left out before pricing
it sends None for both.
"""
from __future__ import annotations

import math

# The most goals one answer holds. A director finds the rest by searching for their name.
LIMIT = 200


def tier_name(tier):
    """A tier's lower case name, such as 'progress', or None."""
    if tier is None:
        return None
    return getattr(tier, 'name', str(tier)).lower()


def why(failure):
    """A planning.decide.Failure as plain data, or None."""
    return None if failure is None else {'kind': failure.kind, 'detail': failure.detail}


def _number(value):
    if value is None or not math.isfinite(value):
        return None
    return round(value, 3)


def kind(name, about, params=()):
    """One kind of goal: its name, plain words for it and its params, each ``(name, type, about)``."""
    return {'kind': name, 'about': about,
            'params': [{'name': param, 'type': type_, 'about': words} for param, type_, words in params]}


def goal(key, kind_name, params, title, tier=None, failure=None, cost=None, worth=None):
    """One goal: its key, kind, params and title, its tier, why it cannot run now, and its cost in frames
    and worth from the candidate that priced it."""
    return {'key': key, 'kind': kind_name, 'params': dict(params), 'title': title, 'tier': tier_name(tier),
            'feasible': failure is None, 'why_not': why(failure), 'cost': _number(cost), 'worth': _number(worth)}


def body(generation, kinds, goals, pin, reason=None, query=None, limit=LIMIT):
    """The ``api/catalogue`` payload. ``query`` keeps the goals whose title holds it and ``limit`` the
    first of them. ``reason`` says why the list is empty and is None when it is not."""
    needle = (query or '').strip().casefold()
    found = [row for row in goals if needle in row['title'].casefold()] if needle else list(goals)
    if limit is not None:
        found = found[:limit]
    if found:
        reason = None
    elif needle and goals:
        reason = 'No goal matches that name'
    return {'generation': generation, 'kinds': kinds, 'goals': found,
            'pin': pin.to_dict() if pin else None, 'reason': reason}
