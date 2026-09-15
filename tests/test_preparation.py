from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pokesim.policies.base import Action, PolicyContext
from pokesim.runtime import preparation
from pokesim.store import Store
from pokesim.trade.preferences import identity
from test_duplicates import snapshot, stored
from test_strategy import mon


@pytest.fixture
def participant(tmp_path, monkeypatch):
    candidate = stored(0, trainer_id=101)
    snap = replace(snapshot([candidate], party=(mon(trainer_id=202, dvs=(3,) * 5),)),
                   map=89, x=13, y=4)
    store = Store(tmp_path)
    memory = bytearray(65536)
    emu = SimpleNamespace(store=store, paused=False, manual_mode=False, frame=snap.frame,
                          input_epoch=0, preparation=None, policy=Mock(), pb=SimpleNamespace(memory=memory))
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: snap)
    yield emu, snap, candidate
    store.close()


def test_preparation_reservation_is_durable_and_idempotent(participant):
    emu, _, candidate = participant
    key = identity(asdict(candidate))
    result = preparation.begin(emu, key, 'transaction-1')
    assert result['phase'] == 'travelling'
    assert result['selected_key'] == key
    assert preparation.begin(emu, key, 'transaction-1') == result
    with pytest.raises(ValueError, match='reserved'):
        preparation.begin(emu, key, 'transaction-2')
    assert emu.store.get(preparation.KEY)['id'] == 'transaction-1'


def test_restart_pauses_preparation_until_coordinator_recovery(participant):
    emu, _, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    preparation.restore(emu)
    assert emu.paused
    assert emu.preparation is None
    assert preparation.cancel(emu, 'transaction-1')['phase'] == 'cancelled'
    assert not emu.paused
    emu.policy.on_restore.assert_called_once()


def test_protection_change_cancels_before_pc_input(participant):
    emu, snap, candidate = participant
    key = identity(asdict(candidate))
    preparation.begin(emu, key, 'transaction-1')
    emu.store.set_trade_preference(key, {'state': 'locked'})
    actions = emu.preparation.step(PolicyContext(snap, 0, 0, emu.pb.memory))
    assert all(action.button is None for action in actions)
    assert emu.store.get(preparation.KEY)['phase'] == 'failed'
    assert emu.preparation is None


def test_active_party_and_ambiguous_individuals_are_not_reserved(participant, monkeypatch):
    emu, snap, candidate = participant
    party_key = identity(asdict(snap.party[0]))
    with pytest.raises(ValueError, match='Active party'):
        preparation.begin(emu, party_key, 'party')
    repeated = replace(snap, stored_details=(candidate, replace(candidate, position=1)))
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: repeated)
    with pytest.raises(ValueError, match='uniquely'):
        preparation.begin(emu, identity(asdict(candidate)), 'ambiguous')
    assert emu.store.get(preparation.KEY) is None


def test_arrival_holds_exact_withdrawn_partner_before_export(participant):
    emu, snap, candidate = participant
    key = identity(asdict(candidate))
    preparation.begin(emu, key, 'transaction-1')
    partner = mon(trainer_id=candidate.trainer_id, dvs=candidate.dvs)
    arrived = replace(snapshot([], party=(snap.party[0], partner)), map=89, x=11, y=3)
    calls = []

    def hold(action, transaction):
        calls.append((action, transaction))
        emu.paused = True

    emu._trade = hold
    assert emu.preparation.step(PolicyContext(arrived, 0, 0, emu.pb.memory)) == []
    assert calls == [('prepare', 'transaction-1')]
    assert emu.store.get(preparation.KEY)['party_slot'] == 1
    assert emu.store.get(preparation.KEY)['phase'] == 'ready'
    assert emu.paused


@pytest.mark.parametrize('busy', [{'in_battle': True}, {'textbox': True}, {'start_menu': True}])
def test_preparation_waits_for_natural_safe_point(participant, monkeypatch, busy):
    emu, snap, candidate = participant
    active = replace(snap, **busy)
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: active)
    ordinary_actions = [Action('a', 4, 8)]
    emu.policy.step.return_value = ordinary_actions
    memory = bytes(emu.pb.memory)
    result = preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    assert result['phase'] == 'travelling'
    assert result['waiting_for'] == 'overworld'
    assert emu.input_epoch == 0
    assert not emu.paused
    controller = emu.preparation
    assert controller.step(PolicyContext(active, 0, 0, emu.pb.memory)) == ordinary_actions
    later = replace(active, frame=active.frame + 4000)
    emu.frame = later.frame
    assert controller.step(PolicyContext(later, 0, 0, emu.pb.memory)) == ordinary_actions
    assert emu.store.get(preparation.KEY)['waiting_for'] == 'overworld'
    safe = replace(snap, frame=later.frame + 1)
    emu.frame = safe.frame
    actions = controller.step(PolicyContext(safe, 0, 0, emu.pb.memory))
    assert actions == [Action('up', 4, 8)]
    assert emu.policy.step.call_count == 2
    assert 'waiting_for' not in emu.store.get(preparation.KEY)
    assert emu.store.get(preparation.KEY)['phase'] == 'storage'
    assert emu.store.get('trade_hold') is None
    assert bytes(emu.pb.memory) == memory


def test_safe_point_wait_has_a_frame_deadline(participant, monkeypatch):
    emu, snap, candidate = participant
    active = replace(snap, in_battle=True)
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: active)
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1', max_frames=60)
    expired = replace(active, frame=active.frame + 61)
    actions = emu.preparation.step(PolicyContext(expired, 0, 0, emu.pb.memory))
    assert all(action.button is None for action in actions)
    assert emu.store.get(preparation.KEY)['phase'] == 'failed'
    assert 'deadline' in emu.store.get(preparation.KEY)['error']
    emu.policy.step.assert_not_called()
    assert emu.preparation is None


def test_safe_point_wait_rechecks_protection_before_policy_input(participant, monkeypatch):
    emu, snap, candidate = participant
    active = replace(snap, in_battle=True)
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: active)
    key = identity(asdict(candidate))
    preparation.begin(emu, key, 'transaction-1')
    emu.store.set_trade_preference(key, {'state': 'locked'})
    actions = emu.preparation.step(PolicyContext(active, 0, 0, emu.pb.memory))
    assert all(action.button is None for action in actions)
    assert emu.store.get(preparation.KEY)['phase'] == 'failed'
    emu.policy.step.assert_not_called()


def test_waiting_restart_and_cancellation_remain_recoverable(participant, monkeypatch):
    emu, snap, candidate = participant
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: replace(snap, in_battle=True))
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    preparation.restore(emu)
    assert emu.paused
    assert emu.preparation is None
    assert preparation.cancel(emu, 'transaction-1')['phase'] == 'cancelled'
    assert not emu.paused
    emu.policy.on_restore.assert_called_once()


def test_participant_reports_preparing_while_battle_finishes(participant, monkeypatch):
    from pokesim.app.registry import identifier
    from pokesim.runtime.participant import Participant

    emu, snap, candidate = participant
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: replace(snap, in_battle=True))
    key = identity(asdict(candidate))
    owner = Participant(SimpleNamespace(store=emu.store, emulator=emu), SimpleNamespace())
    monkeypatch.setattr(owner, 'inventory', lambda: {'offers': [{'trade_key': key}]})
    request = {'id': identifier(), 'plan_digest': 'unchanged-plan', 'selected_key': key}
    response = owner.prepare(request)
    assert response['phase'] == 'preparing'
    assert response['preparation']['waiting_for'] == 'overworld'
    assert owner.prepare(request) == response
    assert emu.store.get('trade_hold') is None


def test_waiting_does_not_adopt_an_unplanned_party_member(participant, monkeypatch):
    emu, snap, candidate = participant
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: replace(snap, start_menu=True))
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    partner = mon(trainer_id=candidate.trainer_id, dvs=candidate.dvs)
    moved = replace(snapshot([], party=(snap.party[0], partner)), map=89, x=11, y=3)
    actions = emu.preparation.step(PolicyContext(moved, 0, 0, emu.pb.memory))
    assert all(action.button is None for action in actions)
    assert emu.store.get(preparation.KEY)['phase'] == 'failed'
    assert 'moved before' in emu.store.get(preparation.KEY)['error']
    assert emu.store.get('trade_hold') is None
    emu.policy.step.assert_not_called()


def test_safe_point_wait_has_a_wall_clock_deadline(participant, monkeypatch):
    emu, snap, candidate = participant
    active = replace(snap, in_battle=True)
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: active)
    state = preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    monkeypatch.setattr(preparation.time, 'time', lambda: state['deadline'] + 1)
    actions = emu.preparation.step(PolicyContext(active, 0, 0, emu.pb.memory))
    assert all(action.button is None for action in actions)
    assert emu.store.get(preparation.KEY)['phase'] == 'failed'
    assert 'deadline' in emu.store.get(preparation.KEY)['error']
    emu.policy.step.assert_not_called()
