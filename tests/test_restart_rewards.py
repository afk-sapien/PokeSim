"""Undoing a restart never pays the League gifts of the old run out again."""
from types import SimpleNamespace
from unittest.mock import Mock

from pokesim import rewards
from test_events import snap
from test_rewind_barriers import restartable


def test_a_gen1_game_loaded_after_a_restart_counts_only_new_league_wins(tmp_path, monkeypatch):
    emu = restartable(tmp_path, 1)
    try:
        emu.store.set('trade_barrier', None)
        rewards.earn(emu.store, 3, enabled=True)
        emu._handle_command('restart', None)
        # A game from before the restart, three League wins in. Without a manifest the run memory stays.
        emu.mem.championships = 3
        monkeypatch.setattr('pokesim.emulator.read_snapshot', lambda *args: snap(frame=900))
        emu.audio = None
        path = emu.store.states / 'legacy.state'
        path.write_bytes(b'past')
        emu._load_state_file(path)
        rewards.earn(emu.store, 4, enabled=True)
        assert rewards.status(emu.store)['pending'] == 1
    finally:
        emu.store.close()


def test_a_gen2_game_loaded_after_a_restart_counts_only_new_league_wins(tmp_path, monkeypatch):
    from pokesim.gen2 import emulator as module
    monkeypatch.setattr(module, 'Policy', lambda *args, **kwargs: SimpleNamespace(trade_preferences=None))
    monkeypatch.setattr(module, 'validate_runtime', lambda metadata: None)
    emu = restartable(tmp_path, 2)
    try:
        rewards.earn(emu.store, 3, enabled=True)
        emu._handle_command('restart', None)
        emu.rom_sha1, emu.policy = 'sha1', Mock()
        emu._clock_reading, emu._sync_clock = Mock(return_value=None), Mock()
        emu.history, emu.audio = {}, Mock()
        emu._reset_watch, emu._publish_frame = Mock(), Mock()
        emu._read = Mock(return_value=SimpleNamespace(hall_of_fame_count=3))
        emu.store.write_checkpoint(b'past', {'rom_sha1': 'sha1', 'generation': 2, 'trade_id': 't1',
                                             'reward_id': 'r1', 'policy_state': {}, 'run_memory': {}},
                                    'league-entry.state')
        emu._load_state_file(emu.store.states / 'league-entry.state')
        rewards.earn(emu.store, 4, enabled=True)
        assert rewards.status(emu.store)['pending'] == 1
    finally:
        emu.store.close()
