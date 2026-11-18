"""The check every test runs under (tests/conftest.py) fails a Gen II build that edits a held value in place."""
from types import SimpleNamespace

import pytest

from pokesim.gen2 import collection


def policy():
    return SimpleNamespace(collection={'failures': {'Abra': [1]}}, monitor_tables={'no_route': {'route-1': [4]}},
                           menu=None, completed={'badge_1': 10})


@pytest.mark.parametrize('edit', [lambda p: p.collection['failures']['Abra'].append(2),
                                  lambda p: p.monitor_tables['no_route']['route-1'].append(5)])
def test_a_build_that_edits_a_held_value_fails(edit):
    p = policy()
    with pytest.raises(AssertionError, match='in place'):
        collection.draft(p, lambda: edit(p))


def test_a_build_that_replaces_values_passes():
    p = policy()

    def build():
        p.collection['failures'] = {**p.collection['failures'], 'Abra': [1, 2]}
        p.monitor_tables['no_route']['route-2'] = [6]
        p.completed['badge_2'] = 20
    _, writes = collection.draft(p, build)
    assert set(writes) == {('collection', 'failures'), ('monitor', 'no_route'), 'completed'}
    assert p.collection['failures'] == {'Abra': [1]} and p.completed == {'badge_1': 10}
