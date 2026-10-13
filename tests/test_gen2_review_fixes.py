"""Pre-beta review fixes: a restarted run watches itself again, and broken saves never end a run."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pokesim.stalls import StallWatch
from pokesim.store import Store


@pytest.fixture
def gen2_emu(tmp_path, monkeypatch):
    from pokesim.gen2 import emulator as module
    monkeypatch.setattr(module, 'Policy', lambda *args, **kwargs: SimpleNamespace(trade_preferences=None))
    emu = module.Emulator.__new__(module.Emulator)
    emu.store = Store(tmp_path)
    emu.data = None
    emu.pb = Mock()
    emu._boot = Mock(return_value=Mock())
    emu._sync_clock = Mock()
    emu._autosave = Mock()
    emu.tracker, emu.steps = Mock(), Mock()
    emu.statistics = SimpleNamespace(previous=None, records=Mock())
    emu.policy = Mock()
    emu.paused = emu.manual_mode = False
    yield emu
    emu.store.close()


def test_restart_clears_the_old_runs_watch_and_bests(gen2_emu):
    """The new run starts at frame 0, so the old frames and bests kept guards off and the run stalled."""
    from pokesim.gen2.emulator import STALL_RELOADS
    emu = gen2_emu
    emu.frame = 500000
    emu.last_reload_frame = emu._reward_check_frame = emu._guard_frame = 499000
    emu.best_progress = (8, 900, 120, 40, 400000)
    emu.best_experience = {(1, (), 7): 400000}
    emu.best_egg_cycles = {'egg': 3}
    emu.unstick_streak, emu.reloads_exhausted = STALL_RELOADS + 5, True
    emu.stall = StallWatch()
    emu.stall.progress(400000, 0.0)
    emu.stall.alerted = 1.0
    emu._handle_command('restart', None)
    assert emu.frame == 0 and emu.last_reload_frame == 0
    assert emu._reward_check_frame == 0 and emu._guard_frame == 0
    assert emu.best_progress == (0,) * 5 and emu.best_experience == {} and emu.best_egg_cycles == {}
    assert emu.unstick_streak == 0 and not emu.reloads_exhausted
    assert emu.stall.frame is None and emu.stall.alerted is None


@pytest.mark.parametrize('error', [ValueError('refused'), OSError('unreadable'), EOFError('truncated')])
def test_a_broken_rewind_never_ends_the_run(gen2_emu, error):
    emu = gen2_emu
    (emu.store.states / 'event-1.state').write_bytes(b'x')
    emu._load_state_file = Mock(side_effect=error)
    assert emu._handle_command('load_state', 'event-1.state') is True


def test_a_truncated_autosave_falls_back_to_an_older_one(gen2_emu, monkeypatch):
    emu = gen2_emu
    older, newer = emu.store.states / 'auto-1.state', emu.store.states / 'auto-2.state'
    loaded = []

    def load(path):
        if path == newer:
            raise EOFError('truncated')
        loaded.append(path)
    emu._load_state_file = load
    emu.store.autosaves = lambda: [older, newer]
    monkeypatch.setattr('pokesim.rewards.initialize', lambda *args: None)
    emu.snapshot = None
    emu._clear_stale_hold = Mock(side_effect=StopIteration)
    with pytest.raises(StopIteration):
        emu.start()
    assert loaded == [older]
