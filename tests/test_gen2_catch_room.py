"""A Gen II catch asks the ledger for room, and finds none exactly when the former full-storage check did."""
import itertools
from types import SimpleNamespace

from pokesim.gen2.ledger import catch_need, catch_room
from pokesim.planning.ledger import Need


def former_no_room(snapshot, target):
    """policy.no_room, which clock_wait asked before the ledger did."""
    can_catch = len(snapshot.party) < 6 or snapshot.box_counts[snapshot.active_box] < 20
    return not can_catch and all(count >= 20 for count in snapshot.box_counts) and target is None


def test_a_catch_has_room_exactly_when_storage_was_not_sealed():
    boxes = [(20,) * 14, (20,) * 13 + (19,), (19,) + (20,) * 13, (5,) * 14]
    for party, counts, active, target in itertools.product((1, 5, 6), boxes, (0, 13), (None, 'spare')):
        snapshot = SimpleNamespace(party=(object(),) * party, box_counts=counts, active_box=active, pockets={}, money=0)
        policy = SimpleNamespace(data=None, storage_target=lambda snapshot, target=target: target)
        assert catch_room(policy, snapshot, 'clock_wait') is not former_no_room(snapshot, target)


def test_a_full_party_needs_one_box_slot():
    assert catch_need(SimpleNamespace(party=(object(),) * 6)) == Need(box_slots=1)
    assert catch_need(SimpleNamespace(party=(object(),) * 5)) == Need()
