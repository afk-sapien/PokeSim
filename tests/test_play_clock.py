import json
from unittest.mock import Mock

from pokesim.emulator import Emulator
from pokesim.play_clock import PlayClock
from pokesim.store import Store
from test_events import snap


def test_clock_passes_cartridge_limit_and_survives_serialization():
    clock = PlayClock()
    clock.seed(254 * 3600)
    clock.advance(3 * 3600 * 60 + 59)
    restored = PlayClock(json.loads(json.dumps(clock.state_dict())))
    assert restored.status() == {'seconds': 257 * 3600, 'display': '257:00:00',
                                 'lower_bound': False, 'source': 'app'}
    restored.advance(1)
    assert restored.status()['display'] == '257:00:01'


def test_migration_marks_previously_capped_time_as_a_lower_bound():
    clock = PlayClock()
    clock.seed(255 * 3600)
    clock.advance(3600 * 60)
    clock.seed(255 * 3600)
    assert clock.status()['display'] == '256:00:00'
    assert clock.status()['lower_bound']


def test_unstarted_clock_does_not_count_boot_or_menu_frames():
    clock = PlayClock()
    clock.advance(600)
    assert clock.status()['seconds'] == 0
    clock.seed(0)
    clock.advance(60)
    assert clock.status()['seconds'] == 1


def test_loading_older_checkpoints_never_rewinds_played_time():
    clock = PlayClock()
    clock.seed(100)
    checkpoint = clock.state_dict()
    clock.advance(600)
    clock.restore(checkpoint)
    assert clock.status()['seconds'] == 110
    recovered = PlayClock()
    recovered.restore(clock.state_dict())
    assert recovered.status() == clock.status()


def test_emulator_ticks_count_simulated_frames_including_manual_play():
    emu = Emulator.__new__(Emulator)
    emu.play_clock = PlayClock()
    emu.play_clock.seed(0)
    emu.frame = 0
    emu.stopping = False
    emu.pb = Mock()
    emu._publish_frame = Mock()
    emu._observe = Mock()
    emu._pace = Mock()
    for speed, manual in [(1, False), (16, False), (0, False), (1, True)]:
        emu.speed, emu.manual_mode = speed, manual
        emu._tick(60)
    assert emu.play_clock.status()['seconds'] == 4
    emu.stopping = True
    emu._tick(60)
    assert emu.play_clock.status()['seconds'] == 4


def test_autosave_persists_clock_in_store_and_checkpoint(tmp_path):
    from pokesim.legendary import LegendaryRecovery
    store = Store(tmp_path)
    emu = Emulator.__new__(Emulator)
    emu.store = store
    emu.snapshot = snap()
    emu.play_clock = PlayClock()
    emu.play_clock.seed(256 * 3600)
    emu.policy = Mock()
    emu.policy.state_dict.return_value = {}
    emu.mem = Mock()
    emu.mem.to_dict.return_value = {}
    emu.rom_sha1 = 'test-rom'
    emu.frame = 0
    emu.legendary_recovery = LegendaryRecovery({'pending': {'150': 1234}, 'attempts': {'150': 1}})
    emu._state_bytes = lambda: b'save'
    emu._autosave()
    assert store.checkpoint_metadata(store.latest_state())['play_clock'] == emu.play_clock.state_dict()
    assert store.checkpoint_metadata(store.latest_state())['legendary_recovery'] == emu.legendary_recovery.state_dict()
    store.close()
    reopened = Store(tmp_path)
    assert PlayClock(reopened.get('play_clock')).status() == emu.play_clock.status()
    reopened.close()


def test_restart_resets_clock_for_a_new_adventure(tmp_path):
    emu = Emulator.__new__(Emulator)
    emu.store = Store(tmp_path)
    emu.pb = Mock()
    emu.policy = Mock()
    emu._boot = Mock()
    emu.input_epoch = 0
    emu.play_clock = PlayClock()
    emu.play_clock.seed(900000)
    emu._handle_command('restart', None)
    assert emu.play_clock.status()['seconds'] == 0
    assert not emu.play_clock.initialized
    assert emu.snapshot is None
    assert emu.store.get('play_clock')['frames'] == 0
    emu.store.close()


def test_checkpoint_reload_preserves_announced_playtime(tmp_path, monkeypatch):
    from importlib.metadata import version
    from pokesim import config
    from pokesim.events import RunMemory
    emu = Emulator.__new__(Emulator)
    emu.store = Store(tmp_path)
    emu.mem = RunMemory(playtime_milestones={250})
    emu.store.set('run_memory', RunMemory(playtime_milestones={240}).to_dict())
    emu.pb = Mock()
    emu.policy = Mock()
    emu.rom_sha1 = 'rom'
    emu.input_epoch = 0
    emu.frame = 0
    emu.play_clock = PlayClock()
    path = emu.store.write_checkpoint(b'save', {'rom_sha1': 'rom', 'pyboy_version': version('pyboy'),
        'policy': config.POLICY, 'policy_state': {}, 'run_memory': RunMemory().to_dict()})
    monkeypatch.setattr('pokesim.emulator.read_snapshot', lambda memory, frame: snap())
    emu._load_state_file(path)
    assert emu.mem.playtime_milestones == {240, 250}
    assert emu.store.get('run_memory')['playtime_milestones'] == [240, 250]
    emu.store.close()
