from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pokesim.policies.base import PolicyContext
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
