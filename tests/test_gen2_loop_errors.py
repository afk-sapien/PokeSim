"""An error in one pass of the Gen II loop is logged and the run goes on, the same way Gen I recovers."""
import queue
from unittest.mock import Mock

import pytest

from pokesim.gen2.emulator import Emulator
from pokesim.gen2.policy import Action


@pytest.fixture
def emu(monkeypatch):
    monkeypatch.setattr('pokesim.loop_errors.time.sleep', lambda _: None)
    emu = object.__new__(Emulator)
    emu.commands, emu.manual = queue.Queue(), queue.Queue()
    emu.store = Mock(get=Mock(return_value=None))
    emu.frame = emu._reward_check_frame = 0
    emu._guard_frame = 10 ** 9
    emu.preparation, emu.paused, emu.manual_mode = None, False, False
    emu.fatal_error, emu.stopping = None, False
    emu.pb, emu.steps, emu.policy = Mock(), Mock(), Mock(backing_out=False)
    emu._read, emu._tick, emu._autosave, emu._report_missed_shiny = Mock(), Mock(), Mock(), Mock()
    return emu


def test_a_step_that_raises_once_does_not_end_the_run(emu):
    def step(snapshot, memory):
        if emu.policy.step.call_count == 1:
            raise RuntimeError('one bad step')
        emu.commands.put(('stop', None))
        return Action('a', 6, 24)
    emu.policy.step.side_effect = step
    emu._run()
    assert emu.policy.step.call_count == 2
    emu.pb.button_press.assert_called_once_with('a')
    assert emu.fatal_error is None and emu.consecutive_errors == 0
    emu._autosave.assert_called_once_with()
    emu.pb.stop.assert_called_once_with(save=False)


def test_ten_failures_in_a_row_stop_without_overwriting_good_saves(emu):
    emu.policy.step.side_effect = RuntimeError('always broken')
    emu._run()
    assert emu.policy.step.call_count == 10
    assert '10 consecutive errors' in emu.fatal_error
    emu._autosave.assert_not_called()
    emu.pb.stop.assert_called_once_with(save=False)


def test_a_committed_reward_that_needs_recovery_stops_at_once(emu):
    def step(snapshot, memory):
        emu.fatal_error = 'A committed Gen II gift needs recovery. Restart this adventure.'
        raise RuntimeError('recovery failed')
    emu.policy.step.side_effect = step
    emu._run()
    assert emu.policy.step.call_count == 1
    assert 'needs recovery' in emu.fatal_error
    emu._autosave.assert_not_called()
