"""A restart that fails keeps one whole game: the old one before the commit, the new one after it."""
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pokesim.loop_errors import loop_failed
from pokesim.runtime.restart import UNFINISHED
from pokesim.state import domains
from pokesim.store import Store
from test_rewind_barriers import restartable

OLD_GOAL = {'goal': 'old'}


@pytest.fixture(params=[1, 2], ids=['gen1', 'gen2'])
def emu(request, tmp_path, monkeypatch):
    if request.param == 2:
        from pokesim.gen2 import emulator as module
        monkeypatch.setattr(module, 'Policy', lambda *args, **kwargs: SimpleNamespace(trade_preferences=None))
    emu = restartable(tmp_path, request.param)
    emu.fatal_error = None
    emu.store.set('policy_state', OLD_GOAL)
    for index in range(2):
        emu.store.write_checkpoint(b'state', {'index': index})
    emu.old_pb = emu.pb
    yield emu
    emu.store.close()


def stops_the_run(emu):
    """What the run loop does with the error: stop, so the final autosave never writes over the new game."""
    emu.consecutive_errors = 0
    try:
        raise RuntimeError('the restart command raised')
    except RuntimeError:
        return loop_failed(emu, logging.getLogger(__name__))


def test_a_failure_before_the_commit_keeps_the_old_game_playing(emu, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(emu.store, 'durable', broken)
    with pytest.raises(OSError):
        emu._handle_command('restart', None)
    assert emu.fatal_error is None and emu.pb is emu.old_pb
    emu.old_pb.stop.assert_not_called()
    assert emu.store.get('policy_state') == OLD_GOAL and len(emu.store.autosaves()) == 2


def test_a_failure_after_the_commit_stops_the_run_and_the_store_opens_on_the_new_game(emu, monkeypatch, tmp_path):
    def crash():
        raise OSError('power lost')
    monkeypatch.setattr(emu.store.checkpoints, 'drop_autosaves', crash)
    with pytest.raises(OSError):
        emu._handle_command('restart', None)
    assert emu.fatal_error == UNFINISHED and stops_the_run(emu)
    emu.old_pb.stop.assert_not_called()
    emu.store.close()
    reopened = Store(tmp_path)
    try:
        assert reopened.get('policy_state') == {} and reopened.get(domains.RESTART_PENDING) is None
        assert reopened.autosaves() == []
    finally:
        reopened.close()
        emu.store = Store(tmp_path)


def test_a_failure_to_boot_the_new_game_stops_the_run(emu):
    emu._boot = Mock(side_effect=OSError('cartridge missing'))
    with pytest.raises(OSError):
        emu._handle_command('restart', None)
    assert emu.fatal_error == UNFINISHED and stops_the_run(emu)
    assert emu.store.get('policy_state') == {} and emu.store.get(domains.RESTART_PENDING) is None
    assert emu.store.autosaves() == []
