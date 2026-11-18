"""Checks every test runs under."""
from copy import deepcopy

import pytest

from pokesim.gen2 import collection

_SCALARS = (int, float, complex, str, bytes, bool, type(None))


def _held(policy):
    """Each object the state holds before a build, beside a copy of it: the collection's values, the rows
    of each monitor table and the milestones' values."""
    held = [(('collection', key), value) for key, value in policy.collection.items()]
    for name, table in getattr(policy, 'monitor_tables', {}).items():
        if isinstance(table, dict):
            held.extend((('monitor', name, key), value) for key, value in table.items())
    completed = getattr(policy, 'completed', None)
    if isinstance(completed, dict):
        held.extend((('completed', key), value) for key, value in completed.items())
    return [(where, value, deepcopy(value)) for where, value in held if not isinstance(value, _SCALARS)]


@pytest.fixture(autouse=True)
def builds_replace_what_they_change(monkeypatch):
    """A Gen II rung's build replaces a value it changes and never edits one the state held before it.

    The draft that takes a build's writes back then puts the old state back with a one-level copy.
    """
    drafted = collection.draft

    def checked(policy, build, *args, **kwargs):
        def run():
            held = _held(policy)
            result = build()
            edited = [where for where, value, copy in held if value != copy]
            assert not edited, f'a build edited {edited} in place, where it must replace the value'
            return result
        return drafted(policy, run, *args, **kwargs)
    monkeypatch.setattr(collection, 'draft', checked)
