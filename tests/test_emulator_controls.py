import queue
from unittest.mock import Mock
import pytest

from pokesim.emulator import Emulator
from pokesim.play_clock import PlayClock
from pokesim.policies.base import Action
from pokesim.runtime.reward_delivery import RETRY_FRAMES, SPACING_FRAMES, reward_due, schedule
from pokesim.runtime.supervision import Supervisor
from test_events import snap


@pytest.mark.parametrize('delivered, interval', [(None, RETRY_FRAMES), ({'phase': 'complete'}, SPACING_FRAMES)])
def test_reward_retries_soon_but_success_keeps_gifts_spaced(monkeypatch, delivered, interval):
    emu = Emulator.__new__(Emulator)
    emu.frame = 100
    emu.input_epoch = 0
    emu.commands = queue.Queue()
    emu.manual = queue.Queue()
    emu.manual.put(Action('right', 8, 2))
    emu.paused = False
    emu.manual_mode = False
    emu.isolated_ram = True
    emu.policy = Mock(tm_plan=None)
    emu.pb = Mock()
    emu._autosave = Mock()
    emu._check_guards = Mock()
    monkeypatch.setattr('pokesim.emulator.time.time', lambda: 100)
    delivery = Mock(return_value=delivered)
    monkeypatch.setattr('pokesim.runtime.reward_delivery.deliver', delivery)
    emu._tick = lambda _: emu.commands.put(('stop', None))
    emu._run()
    delivery.assert_called_once()
    assert (emu._reward_frame, emu._reward_wait) == (100, interval)


def test_gift_pacing_counts_frames_not_wall_seconds(monkeypatch):
    """An uncapped run must not starve gifts, and a reload that rewinds frames must not stall them."""
    emu = Emulator.__new__(Emulator)
    emu.frame = 1000
    assert reward_due(emu)
    schedule(emu, {'phase': 'complete'})
    monkeypatch.setattr('pokesim.emulator.time.time', lambda: 10 ** 9)
    emu.frame = 1000 + SPACING_FRAMES - 1
    assert not reward_due(emu)
    emu.frame += 1
    assert reward_due(emu)
    schedule(emu, None)
    emu.frame += RETRY_FRAMES
    assert reward_due(emu)
    schedule(emu, {'phase': 'complete'})
    emu.frame = 10
    assert reward_due(emu)


def test_manual_input_runs_while_paused_without_policy_input():
    emu = Emulator.__new__(Emulator)
    emu.input_epoch = 0
    emu.commands = queue.Queue()
    emu.manual = queue.Queue()
    emu.manual.put(Action('right', 8, 2))
    emu.paused = True
    emu.manual_mode = False
    emu.policy = Mock(tm_plan=None)
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
    emu.policy = Mock(tm_plan=None)
    from pokesim.store import Store
    emu.store = Store(tmp_path)
    emu.input_epoch = 7
    emu.frame = 900
    emu.play_clock = PlayClock()
    emu.pending = ['obsolete event']
    expected = snap(frame=900)
    monkeypatch.setattr('pokesim.emulator.read_snapshot', lambda memory, frame: expected)
    monkeypatch.setattr('pokesim.emulator.repair_party_nicknames', lambda memory: [])
    emu._load_state_file(path)
    assert emu.snapshot == expected and emu.input_epoch == 8
    assert emu.pending == [] and emu.prev_snapshot is None
    emu.policy.on_restore.assert_called_once()
    from pokesim.policies.base import BUTTONS
    from unittest.mock import call
    assert emu.pb.button_release.call_args_list == [call(button) for button in BUTTONS]
    assert emu.pb.method_calls[0][0] == 'load_state'


def test_restore_keeps_total_victories_separate_from_reward_count(tmp_path, monkeypatch):
    from importlib.metadata import version
    from pokesim import config, rewards
    from pokesim.store import Store

    path = tmp_path / 'checkpoint.state'
    path.write_bytes(b'checkpoint')
    emu = Emulator.__new__(Emulator)
    emu.pb = Mock()
    emu.policy = Mock(tm_plan=None)
    emu.store = Store(tmp_path)
    emu.rom_sha1 = 'test-rom'
    emu.play_clock = PlayClock()
    emu.input_epoch = 0
    emu.frame = 0
    metadata = {'rom_sha1': emu.rom_sha1, 'pyboy_version': '2.7.0',
                'policy': config.POLICY, 'policy_state': {}, 'run_memory': {'championships': 100}}
    monkeypatch.setattr(emu.store, 'checkpoint_metadata', lambda _: metadata)
    monkeypatch.setattr('pokesim.emulator.read_snapshot', lambda *_: snap())
    monkeypatch.setattr('pokesim.emulator.repair_party_nicknames', lambda memory: [])
    try:
        rewards.initialize(emu.store, 107)
        rewards.earn(emu.store, 108, enabled=True)
        emu._load_state_file(path)
        assert emu.mem.championships == 108
        assert rewards.status(emu.store)['earned'] == 1
        rewards.earn(emu.store, emu.mem.championships, enabled=True)
        assert rewards.status(emu.store)['pending'] == 1
    finally:
        emu.store.close()


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
    emu.policy = Mock(tm_plan=None)
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
    emu.policy = Mock(tm_plan=None)
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


def test_stationary_strategic_run_replans_without_rewinding():
    from pokesim import config
    from pokesim.policies.strategic import StrategicPolicy
    from pokesim.runtime.reload import FRAMES_PER_SECOND
    emu = Emulator.__new__(Emulator)
    emu.policy = StrategicPolicy(7)
    emu.snapshot = snap(frame=1000)
    # The stuck limit is in game seconds, so it counts emulator frames.
    emu.frame = 10 ** 6
    emu.stuck_frame = emu.frame - (config.STUCK_RELOAD_SECONDS + 1) * FRAMES_PER_SECOND
    emu.play_clock = PlayClock()
    emu.input_epoch = 0
    emu._unstick = Mock()
    emu._check_guards()
    emu._unstick.assert_not_called()
    assert emu.policy.recoveries == 1
    assert emu.input_epoch == 1


def test_live_progress_uses_achievement_age_and_recovery_state(monkeypatch):
    from pokesim.policies.strategic import StrategicPolicy
    emu = Emulator.__new__(Emulator)
    emu.policy = StrategicPolicy(7)
    emu.last_achievement = {'id': 1, 'title': 'Caught Ditto', 'ts': 1000}
    emu.invalid_frame = None
    emu.last_reload = 0
    emu.supervisor = Supervisor()
    emu.play_clock = PlayClock()
    monkeypatch.setattr('pokesim.emulator.time.time', lambda: 1050)
    assert emu.progress_status()['state'] == 'making_progress'
    monkeypatch.setattr('pokesim.emulator.time.time', lambda: 1500)
    assert emu.progress_status()['state'] == 'exploring'
    assert emu.progress_status()['last_achievement']['age_seconds'] == 500
    emu.policy.recover_stall(snap(frame=100))
    assert emu.progress_status()['state'] == 'recovering'


def _stuck_emulator():
    from pokesim.policies.strategic import StrategicPolicy
    from pokesim.runtime.supervision import MAX_RELOADS
    from test_supervision import ladder
    emu = Emulator.__new__(Emulator)
    emu.policy = StrategicPolicy(7)
    emu.snapshot = snap(frame=1000)
    emu.supervisor = ladder(MAX_RELOADS)
    emu.play_clock = PlayClock()
    emu.input_epoch = 0
    emu.events = []
    emu._handle_events = lambda events, snapshot: emu.events.extend(events)
    emu.store = Mock()
    return emu


def test_exhausted_reloads_give_up_the_collection_project():
    from test_collection import sid
    emu = _stuck_emulator()
    emu.policy.collection.project = {'method': 'gift', 'species': sid(133)}
    Emulator._unstick(emu, 0, 'stuck')
    emu.store.autosaves.assert_not_called()
    assert emu.policy.collection.project is None
    assert emu.supervisor.reloads == 0 and not emu.supervisor.stalled
    assert [event.title for event in emu.events][-1].startswith('Gave up on')


def test_exhausted_reloads_without_a_project_stop_reloading_and_stall(caplog, monkeypatch):
    emu = _stuck_emulator()
    emu.policy.collection.project = None
    emu.last_achievement, emu.frame = None, 1000
    monkeypatch.setattr('pokesim.emulator.time.time', lambda: 5000)
    with caplog.at_level('ERROR', logger='pokesim.emu'):
        for _ in range(3):
            Emulator._unstick(emu, 0, 'stuck')
    emu.store.autosaves.assert_not_called()
    assert sum('not reloading again' in record.getMessage() for record in caplog.records) == 1
    assert emu.progress_status()['state'] == 'stalled'
