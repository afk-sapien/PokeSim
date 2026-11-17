"""A rung's draft takes its writes back and holds its copy of the old state for the next draft."""
import pickle
from copy import deepcopy
from types import SimpleNamespace

import pytest

from pokesim.gen2 import collection, kinds
from pokesim.planning.goals import GoalRun, GoalSpec


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
def copies(monkeypatch):
    """The deep copies of the whole state drafts take, counted."""
    count = []

    def counted(value, *args):
        if isinstance(value, dict) and 'completed' in value:
            count.append(1)
        return deepcopy(value, *args)
    monkeypatch.setattr(collection, 'deepcopy', counted)
    return count


@pytest.fixture
def fingerprints(monkeypatch):
    """The fingerprints drafts take, counted."""
    count = []
    fingerprint = collection._fingerprint

    def counted(slots):
        count.append(1)
        return fingerprint(slots)
    monkeypatch.setattr(collection, '_fingerprint', counted)
    return count


def edit(p):
    """A build that edits slots in place, adds one and removes one, as a rung's build may."""
    p.collection['failures']['Abra'].append(3)
    p.collection['phase'] = 'train'
    p.collection['new'] = [1]
    del p.collection['order']
    p.monitor_tables['no_route']['route-2'] = [6]
    p.completed['badge_2'] = True
    return 'goal'


def test_a_rejected_draft_leaves_the_live_state_untouched(copies):
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
    assert p.collection['failures'] == {'Abra': [1, 2, 3]} and 'order' not in p.collection
    assert p.completed is completed and p.completed == {'badge_1': True, 'badge_2': True}


def test_drafts_that_write_nothing_share_one_copy(copies):
    p = policy()
    for _ in range(3):
        assert collection.draft(p, lambda: p.collection.get('phase')) == ('hunt', {})
    assert len(copies) == 1
    # A change between drafts takes a new copy, and a rejected draft puts back the changed state.
    p.collection['failures']['Abra'].append(9)
    changed = state(p)
    collection.draft(p, lambda: edit(p))
    assert len(copies) == 2 and state(p) == changed


def test_one_decision_takes_one_fingerprint_until_a_rung_writes(copies, fingerprints):
    p = policy()
    token = object()
    for _ in range(3):
        assert collection.draft(p, lambda: p.collection.get('phase'), token) == ('hunt', {})
    # A build that puts an equal object in a slot wrote nothing, and the next rung checks that object.
    collection.draft(p, lambda: p.collection.update(order=dict(p.collection['order'])), token)
    collection.draft(p, lambda: None, token)
    assert len(fingerprints) == 1 and len(copies) == 1
    # A rung that writes takes the held copy too, and its draft still puts the old state back.
    before = state(p)
    _, writes = collection.draft(p, lambda: edit(p), token)
    assert len(fingerprints) == 1 and writes and state(p) == before
    # Putting the old state back handed copied objects to the policy, so the next rung takes a new copy.
    collection.draft(p, lambda: None, token)
    assert len(fingerprints) == 2 and len(copies) == 2
    # The next decision takes one fingerprint, and the copy while the state is unchanged.
    collection.draft(p, lambda: None, object())
    assert len(fingerprints) == 3 and len(copies) == 2


def test_a_slot_that_changes_between_rungs_takes_a_fingerprint(copies, fingerprints):
    p = policy()
    token = object()
    collection.draft(p, lambda: None, token)
    # The monitor makes a missing table as it reads, as standing_down does between two rungs.
    p.monitor_tables['stood_down'] = {}
    _, writes = collection.draft(p, lambda: None, token)
    assert len(fingerprints) == 2 and len(copies) == 2 and not writes
    # An equal object in place of a slot's own is not the object the copy was checked against.
    p.collection['order'] = dict(p.collection['order'])
    collection.draft(p, lambda: None, token)
    assert len(fingerprints) == 3 and len(copies) == 2


def test_an_order_change_equality_misses_takes_a_new_copy(copies):
    p = policy()
    collection.draft(p, lambda: None)
    p.collection['order'] = {'b': 2, 'a': 1}
    _, writes = collection.draft(p, lambda: p.collection['order'].update(c=3))
    assert len(copies) == 2 and writes
    assert list(p.collection['order']) == ['b', 'a']


def test_a_draft_that_puts_copies_back_drops_its_copy(copies):
    p = policy()
    collection.draft(p, lambda: None)
    collection.draft(p, lambda: p.collection['failures'].update(Abra=[7]))
    assert len(copies) == 1
    # The live failures are now the held copy's own object, so an edit in place must still be seen.
    _, writes = collection.draft(p, lambda: p.collection['failures']['Abra'].append(8))
    assert len(copies) == 2
    assert writes == {('collection', 'failures'): {'Abra': [1, 2, 8]}}
    assert p.collection['failures'] == {'Abra': [1, 2]}


def test_a_failed_build_drops_the_copy(copies):
    p = policy()
    collection.draft(p, lambda: None)

    def failing():
        p.collection['failures']['Abra'].append(3)
        raise RuntimeError('build failed')
    with pytest.raises(RuntimeError):
        collection.draft(p, failing)
    assert p.draft_copy is None
    del p.collection['failures']['Abra'][-1]
    collection.draft(p, lambda: None)
    assert len(copies) == 2


def test_a_goal_spec_matches_only_by_identity(copies):
    p = policy()
    hunt = p.collection['target']
    collection.draft(p, lambda: None)
    # An equal spec that is another object is what a fresh copy would keep, so the held copy is not used.
    spec = GoalSpec.make(hunt.spec.kind, dict(hunt.spec.params), hunt.spec.key)
    hunt.spec = spec
    _, writes = collection.draft(p, lambda: p.collection['target'].__setitem__('expected', 4))
    assert len(copies) == 2 and writes
    assert p.collection['target'].spec is spec and p.collection['target']['expected'] == 3


class OwnCopy(list):
    def __deepcopy__(self, memo):
        return OwnCopy(self)


@pytest.mark.parametrize('value', [[float('nan')], float('inf'), [complex(float('nan'), 1)], OwnCopy([1]),
                                   lambda: None])
def test_a_state_a_pickle_cannot_vouch_for_is_copied_every_draft(copies, value):
    p = policy()
    p.collection['odd'] = value
    for _ in range(2):
        collection.draft(p, lambda: None)
    assert len(copies) == 2


def test_finite_floats_and_gen2_rules_keep_a_fingerprint():
    p = policy()
    p.collection['rate'] = [0.5, -2.0, 1e300]
    slots = collection._slots(p)
    slots.pop('menu')
    assert collection._fingerprint(slots) is not None
