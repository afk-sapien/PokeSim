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


def restartable(tmp_path, generation):
    """An emulator with its game mocked out, enough to restart and then try a rewind."""
    from types import SimpleNamespace
    if generation == 1:
        import queue
        from pokesim.emulator import Emulator
        from pokesim.events import RunMemory
        from pokesim.play_clock import PlayClock
        emu = Emulator.__new__(Emulator)
        emu.mem, emu.play_clock, emu.manual, emu.speed = RunMemory(), PlayClock(), queue.Queue(), 1
        emu.input_epoch = 0
    else:
        from pokesim.gen2.emulator import Emulator
        emu = Emulator.__new__(Emulator)
        emu.data, emu.fatal_error = None, None
        emu._sync_clock, emu._autosave = Mock(), Mock()
        emu.tracker, emu.steps = Mock(), Mock()
        emu.statistics = SimpleNamespace(previous=None, records=Mock(), flush=Mock())
        emu.snapshot = None
    emu.store = Store(tmp_path)
    emu.pb, emu._boot, emu.policy = Mock(), Mock(return_value=Mock()), Mock()
    emu.paused = emu.manual_mode = False
    emu._state_bytes = Mock(return_value=b'now')
    emu._manifest = Mock(return_value={'trade_id': 't1', 'reward_id': 'r1', 'policy_state': {}, 'run_memory': {}})
    return emu


@pytest.mark.parametrize('generation', [1, 2])
@pytest.mark.parametrize('barrier', BARRIERS)
def test_a_restart_keeps_the_barriers_so_an_older_checkpoint_stays_refused(tmp_path, monkeypatch, generation, barrier):
    """Restarting cleared them, so loading a checkpoint from before a trade brought the traded Pokemon back
    while the partner kept it too, and a custom reward could be undone the same way."""
    if generation == 2:
        from pokesim.gen2 import emulator as module
        from types import SimpleNamespace
        monkeypatch.setattr(module, 'Policy', lambda *args, **kwargs: SimpleNamespace(trade_preferences=None))
    from pokesim.web.app import rewind_refusal
    emu = restartable(tmp_path, generation)
    try:
        emu.store.set('trade_barrier', 't1')
        emu.store.set('custom-reward-barrier-v1', 'r1')
        older = {'trade_id': 't1', 'reward_id': 'r1', 'policy_state': {}, 'run_memory': {}}
        older[dict(BARRIER_FIELDS)[barrier]] = 'older'
        emu.store.write_checkpoint(b'old', older, 'league-entry.state')
        emu._handle_command('restart', None)
        assert emu.store.get('trade_barrier') == 't1' and emu.store.get('custom-reward-barrier-v1') == 'r1'
        assert rewind_refusal(emu.store, 'league-entry.state')
        emu.pb = Mock()
        emu._handle_command('load_state', 'league-entry.state')
        emu.pb.load_state.assert_not_called()
    finally:
        emu.store.close()


BARRIER_FIELDS = [('trade_barrier', 'trade_id'), ('custom-reward-barrier-v1', 'reward_id')]


@pytest.mark.parametrize('generation', [1, 2])
def test_a_rewind_to_a_damaged_save_is_refused_and_not_fatal(tmp_path, generation):
    """Red, Blue and Yellow caught only a refused rewind, so a damaged save raised out of the command."""
    if generation == 1:
        from pokesim.emulator import Emulator
    else:
        from pokesim.gen2.emulator import Emulator
    store = Store(tmp_path)
    try:
        store.write_checkpoint(b'x', {}, 'old.state')
        emu = object.__new__(Emulator)
        emu.store, emu.pb, emu.fatal_error = store, Mock(), None
        emu._load_state_file = Mock(side_effect=EOFError('truncated'))
        assert emu._handle_command('load_state', 'old.state') is True
        emu._load_state_file.assert_called_once()
        assert emu.fatal_error is None
    finally:
        store.close()


def test_gen1_unstick_keeps_playing_when_every_save_predates_a_trade():
    """Red, Blue and Yellow picked among every save, so the refused one spent a reload, and with no
    other save a power cycle fell back on the cartridge's own save, which can predate the trade too."""
    from pathlib import Path
    from types import SimpleNamespace
    from pokesim.emulator import Emulator
    from pokesim.play_clock import PlayClock
    from pokesim.runtime.supervision import Supervisor
    saves = {Path('auto-old'): {'frame': 300000, 'trade_id': 'trade-1'}}
    restored, boots = [], []
    game = SimpleNamespace(store=SimpleNamespace(autosaves=lambda: list(saves), checkpoint_metadata=saves.get,
                                                 get=lambda key: 'trade-2' if key == 'trade_barrier' else None,
                                                 state_path=lambda name: None),
                           snapshot=None, reloads=0, frame=500000, play_clock=PlayClock(), adventure_seed=7,
                           supervisor=Supervisor(), _restore_first_valid=restored.append, _tick=lambda n: None,
                           _boot=lambda **_: boots.append(1))
    game._behind_barrier = lambda metadata: Emulator._behind_barrier(game, metadata)
    Emulator._unstick(game, 495000, 'stuck')
    assert not restored and not boots and game.reloads == 0


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
