"""A rung's draft takes its writes back with a one-level copy, since a build replaces what it changes."""
import pickle
from types import SimpleNamespace

import pytest

from pokesim.gen2 import collection, kinds
from pokesim.planning.goals import GoalRun


def policy():
    hunt = GoalRun.from_dict({'species': 63, 'method': 'walk', 'expected': 3}, kinds.HUNT)
    return SimpleNamespace(
        collection={'phase': 'hunt', 'target': hunt, 'failures': {'Abra': [1, 2]}, 'order': {'a': 1, 'b': 2}},
        monitor_tables={'no_route': {'route-1': [4, 5]}}, menu=None, completed={'badge_1': True})


def state(p):
    """The policy's draft state as pickle bytes, which see order and sharing as well as values."""
    slots = collection._slots(p)
    slots.pop('menu')
    return pickle.dumps(slots, 4)


@pytest.fixture
def no_deep_copy(monkeypatch):
    def refused(*args):
        raise AssertionError('a draft takes no deep copy')
    monkeypatch.setattr(collection, 'deepcopy', refused)


def edit(p):
    """A build that replaces slots, adds one and removes one, and adds a stand-down and a milestone, as a
    rung's build may."""
    p.collection['failures'] = {**p.collection['failures'], 'Abra': [1, 2, 3]}
    p.collection['phase'] = 'train'
    p.collection['new'] = [1]
    del p.collection['order']
    p.monitor_tables['no_route']['route-2'] = [6]
    p.completed['badge_2'] = True
    return 'goal'


def test_a_rejected_draft_leaves_the_live_state_untouched(no_deep_copy):
    p = policy()
    before, completed, hunt = state(p), p.completed, p.collection['target']
    result, writes = collection.draft(p, lambda: edit(p))
    assert result == 'goal'
    assert set(writes) == {('collection', 'failures'), ('collection', 'phase'), ('collection', 'new'),
                           ('collection', 'order'), ('monitor', 'no_route'), 'completed'}
    assert writes[('collection', 'order')] is collection._MISSING
    # Not landing the writes leaves the state as it was, with the slots no build touched kept as they were.
    assert state(p) == before
    assert p.completed is completed and p.collection['target'] is hunt
    collection.write(p, writes)
    assert p.collection['failures'] is writes[('collection', 'failures')] and 'order' not in p.collection
    assert p.monitor_tables['no_route'] == {'route-1': [4, 5], 'route-2': [6]}
    assert p.completed is completed and p.completed == {'badge_1': True, 'badge_2': True}


def test_a_new_object_is_a_write_even_when_equal(no_deep_copy):
    p = policy()
    order = p.collection['order']
    assert collection.draft(p, lambda: p.collection.get('phase')) == ('hunt', {})
    _, writes = collection.draft(p, lambda: p.collection.update(order=dict(order)))
    assert writes == {('collection', 'order'): order} and writes[('collection', 'order')] is not order
    assert p.collection['order'] is order


def test_a_table_the_build_makes_is_a_write(no_deep_copy):
    p = policy()
    # The monitor makes a missing table as it reads, as standing_down does.
    _, writes = collection.draft(p, lambda: p.monitor_tables.setdefault('stood_down', {}))
    assert writes == {('monitor', 'stood_down'): {}} and 'stood_down' not in p.monitor_tables
