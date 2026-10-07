"""Rewinding past a completed trade or custom reward is refused, and never ends the adventure."""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from pokesim import config
from pokesim.events import Event
from pokesim.store import Store
from pokesim.web.app import create_app
from test_events import snap

BARRIERS = ['trade_barrier', 'custom-reward-barrier-v1']


@pytest.mark.parametrize('barrier', BARRIERS)
def test_either_barrier_hides_rewind_and_refuses_the_load(tmp_path, monkeypatch, barrier):
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    store = Store(tmp_path)
    emu = Mock()
    try:
        eid = store.add_event(Event('catch', 'A partner', priority=4), snap(), None, b'state')
        with TestClient(create_app(emu, store)) as client:
            assert 'id="rewind"' in client.get(f'/events/{eid}').text
            store.set(barrier, 'b1')
            assert 'id="rewind"' not in client.get(f'/events/{eid}').text
            result = client.post('/api/control', json={'action': 'load_state', 'value': f'event-{eid}.state'})
            assert result.status_code == 409
            emu.command.assert_not_called()
    finally:
        store.close()


def test_a_save_taken_after_the_reward_barrier_may_still_be_loaded(tmp_path):
    store = Store(tmp_path)
    try:
        store.set('custom-reward-barrier-v1', 'r1')
        store.write_checkpoint(b'x', {'reward_id': 'r1', 'policy_state': {}, 'run_memory': {}}, 'new.state')
        store.write_checkpoint(b'x', {'reward_id': 'older', 'policy_state': {}, 'run_memory': {}}, 'old.state')
        from pokesim.web.app import rewind_refusal
        assert rewind_refusal(store, 'new.state') is None
        assert 'custom reward' in rewind_refusal(store, 'old.state')
    finally:
        store.close()


@pytest.mark.parametrize('barrier', BARRIERS)
def test_gen2_load_state_command_refused_by_a_barrier_is_not_fatal(tmp_path, barrier):
    from pokesim.gen2.emulator import Emulator
    store = Store(tmp_path)
    try:
        store.write_checkpoint(b'x', {}, 'old.state')
        store.set(barrier, 'b1')
        emu = object.__new__(Emulator)
        emu.store, emu.pb, emu.fatal_error = store, Mock(), None
        assert emu._handle_command('load_state', 'old.state') is True
        emu.pb.load_state.assert_not_called()
        assert emu.fatal_error is None
    finally:
        store.close()
