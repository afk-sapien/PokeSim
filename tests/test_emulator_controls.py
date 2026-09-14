import queue
from unittest.mock import Mock

from pokesim.emulator import Emulator
from pokesim.play_clock import PlayClock
from pokesim.policies.base import Action
from test_events import snap


def test_manual_input_runs_while_paused_without_policy_input():
    emu = Emulator.__new__(Emulator)
    emu.input_epoch = 0
    emu.commands = queue.Queue()
    emu.manual = queue.Queue()
    emu.manual.put(Action('right', 8, 2))
    emu.paused = True
    emu.manual_mode = False
    emu.policy = Mock()
    emu.pb = Mock()
    emu._autosave = Mock()
    emu._check_guards = Mock()
    ticks = []

    def tick(frames):
        ticks.append(frames)
        if len(ticks) == 2:
            emu.commands.put(('stop', None))
    emu._tick = tick
    emu._run()
    emu.policy.step.assert_not_called()
    emu.policy.on_restore.assert_not_called()
    emu.pb.button_press.assert_called_once_with('right')
    emu.pb.button_release.assert_called_once_with('right')
    assert ticks == [8, 2]


def test_restore_discards_policy_intent_and_refreshes_snapshot(tmp_path, monkeypatch):
    path = tmp_path / 'checkpoint.state'
    path.write_bytes(b'checkpoint')
    emu = Emulator.__new__(Emulator)
    emu.pb = Mock()
    emu.policy = Mock()
    from pokesim.store import Store
    emu.store = Store(tmp_path)
    emu.input_epoch = 7
    emu.frame = 900
    emu.play_clock = PlayClock()
    emu.pending = ['obsolete event']
    expected = snap(frame=900)
    monkeypatch.setattr('pokesim.emulator.read_snapshot', lambda memory, frame: expected)
    emu._load_state_file(path)
    assert emu.snapshot == expected and emu.input_epoch == 8
    assert emu.pending == [] and emu.prev_snapshot is None
    emu.policy.on_restore.assert_called_once()


def test_manual_takeover_stops_ai_and_keeps_idle_frames_running():
    emu = Emulator.__new__(Emulator)
    emu.input_epoch = 0
    emu.commands = queue.Queue()
    emu.manual = queue.Queue(maxsize=2)
    emu.paused = False
    emu.manual_mode = False
    emu.policy = Mock(spec=['on_restore', 'step'])
    emu.pb = Mock()
    emu._autosave = Mock()
    emu._check_guards = Mock()
    ticks = []

    def tick(frames):
        ticks.append(frames)
        if len(ticks) == 4:
            emu.commands.put(('stop', None))
    emu._tick = tick
    emu.press('right')
    emu._run()
    assert emu.manual_mode and emu.paused
    assert ticks == [6, 2, 0, 4]
    emu.policy.step.assert_not_called()
    emu.policy.on_restore.assert_called_once()
    emu.pb.button_press.assert_called_once_with('right')
    emu.pb.button_release.assert_called_once_with('right')
    emu._check_guards.assert_not_called()


def test_resume_clears_queued_manual_input_and_resets_ai():
    emu = Emulator.__new__(Emulator)
    emu.manual_mode = True
    emu.paused = True
    emu.manual = queue.Queue()
    emu.manual.put(Action('a', 6, 2))
    emu.policy = Mock()
    assert emu._handle_command('resume', None)
    assert not emu.manual_mode and not emu.paused and emu.manual.empty()
    emu.policy.on_restore.assert_called_once()


def test_failed_tick_releases_button_before_worker_retries(monkeypatch):
    emu = Emulator.__new__(Emulator)
    emu.input_epoch = 0
    emu.commands = queue.Queue()
    emu.manual = queue.Queue()
    emu.manual.put(Action('right', 8, 2))
    emu.paused = True
    emu.manual_mode = False
    emu.policy = Mock()
    emu.pb = Mock()
    emu._autosave = Mock()
    emu._check_guards = Mock()

    def fail_tick(frames):
        emu.commands.put(('stop', None))
        raise RuntimeError('render failed')

    def retry_delay(seconds):
        emu.pb.button_release.assert_called_once_with('right')

    emu._tick = fail_tick
    monkeypatch.setattr('pokesim.emulator.time.sleep', retry_delay)
    emu._run()
    emu.pb.button_press.assert_called_once_with('right')
    emu.pb.button_release.assert_called_once_with('right')
    emu.pb.stop.assert_called_once_with(save=False)


def test_stationary_strategic_run_replans_without_rewinding(monkeypatch):
    from pokesim import config
    from pokesim.policies.strategic import StrategicPolicy
    emu = Emulator.__new__(Emulator)
    emu.policy = StrategicPolicy(7)
    emu.snapshot = snap(frame=1000)
    emu.last_reload = 0
    emu.stuck_since = 1
    emu.invalid_since = None
    emu.battle_since = None
    emu.input_epoch = 0
    emu._unstick = Mock()
    monkeypatch.setattr('pokesim.emulator.time.time', lambda: config.STUCK_RELOAD_SECONDS + 2)
    emu._check_guards()
    emu._unstick.assert_not_called()
    assert emu.policy.recoveries == 1
    assert emu.input_epoch == 1


def test_live_progress_uses_achievement_age_and_recovery_state(monkeypatch):
    from pokesim.policies.strategic import StrategicPolicy
    emu = Emulator.__new__(Emulator)
    emu.policy = StrategicPolicy(7)
    emu.last_achievement = {'id': 1, 'title': 'Caught Ditto', 'ts': 1000}
    emu.invalid_since = None
    emu.last_reload = 0
    monkeypatch.setattr('pokesim.emulator.time.time', lambda: 1050)
    assert emu.progress_status()['state'] == 'making_progress'
    monkeypatch.setattr('pokesim.emulator.time.time', lambda: 1500)
    assert emu.progress_status()['state'] == 'exploring'
    assert emu.progress_status()['last_achievement']['age_seconds'] == 500
    emu.policy.recover_stall(snap(frame=100))
    assert emu.progress_status()['state'] == 'recovering'
