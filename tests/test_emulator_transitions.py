"""Restart, restore, and resume preserve different durable state intentionally."""
import queue
from unittest.mock import Mock

import pytest

from pokesim.emulator import Emulator
from pokesim.events import RunMemory
from pokesim.play_clock import PlayClock
from pokesim.store import Store
from test_events import snap


@pytest.fixture
def emu(tmp_path):
    value = Emulator.__new__(Emulator)
    value.store = Store(tmp_path)
    value.pb = Mock()
    value._boot = Mock(return_value=Mock())
    value.policy = Mock()
    value.mem = RunMemory()
    value.play_clock = PlayClock()
    value.frame = 900
    value.input_epoch = 7
    value.speed = 4
    value.paused = value.manual_mode = True
    value.battle_since = value.invalid_since = 1
    value.last_pos = (1, 2, 3)
    value.manual = queue.Queue()
    value.manual.put('old input')
    value.pending = ['pending event']
    value.snapshot = value.prev_snapshot = snap(frame=900)
    yield value
    value.store.close()


def test_resume_discards_input_but_preserves_game_and_event_observations(emu):
    memory, clock, previous = emu.mem, emu.play_clock, emu.prev_snapshot
    emu._handle_command('resume', None)
    assert emu.frame == 900 and emu.speed == 4
    assert emu.mem is memory and emu.play_clock is clock
    assert emu.prev_snapshot is previous and emu.pending == ['pending event']
    assert emu.manual.empty() and emu.input_epoch == 8
    assert emu.battle_since is None and emu.invalid_since is None
    assert not emu.paused and not emu.manual_mode


def test_restore_discards_stale_observations_and_timers_without_changing_controls(emu, monkeypatch):
    path = emu.store.states / 'legacy.state'
    path.write_bytes(b'checkpoint')
    current = snap(frame=900)
    monkeypatch.setattr('pokesim.emulator.read_snapshot', lambda *args: current)
    emu._load_state_file(path)
    assert emu.snapshot is current and emu.prev_snapshot is None and emu.pending == []
    assert emu.battle_since is None and emu.invalid_since is None and emu.last_pos is None
    assert emu.manual.empty() and emu.input_epoch == 8
    assert emu.paused and emu.manual_mode and emu.speed == 4


def test_restart_resets_the_adventure_and_input_but_keeps_event_history(emu):
    from pokesim.events import Event
    eid = emu.store.add_event(Event('catch', 'Kept in journal'), snap(), None, None)
    emu.store.set('trade_barrier', '123')
    emu.store.set('trade_offer:partner', {'state': 'locked'})
    emu.store.set('policy_state', {'old': True})
    path = emu.store.states / 'auto-old.state'
    path.write_bytes(b'old')
    emu._handle_command('restart', None)
    assert emu.frame == 0 and emu.snapshot is None and emu.prev_snapshot is None
    assert emu.pending == [] and emu.manual.empty() and emu.input_epoch == 8
    assert emu.battle_since is None and emu.invalid_since is None
    assert not emu.paused and not emu.manual_mode and emu.speed == 4
    assert emu.store.get('trade_barrier') is None
    assert emu.store.trade_preferences() == {} and emu.store.get('policy_state') == {}
    assert emu.store.event(eid)['title'] == 'Kept in journal'
    assert not path.exists()
    emu.policy.reset.assert_called_once()


@pytest.mark.parametrize('command', ['restart', 'resume', 'load_state', 'take_control'])
def test_trade_hold_blocks_game_transitions_at_execution_time(emu, command):
    emu.store.set('trade_hold', {'id': '123'})
    emu._handle_command(command, 'missing.state')
    assert emu.frame == 900 and emu.input_epoch == 7
    emu.pb.stop.assert_not_called()
    emu.policy.on_restore.assert_not_called()
