"""Both generations time autosaves, guards and reload targets by the emulator frame, never real time."""
from types import SimpleNamespace
from unittest.mock import Mock

from pokesim import config
from pokesim.emulator import Emulator
from pokesim.runtime.reload import FRAMES_PER_SECOND, LOOKBACK_FRAMES, Cadence, reload_target, settled


def test_the_autosave_cadence_counts_game_frames_and_restarts_after_a_rewind():
    cadence = Cadence(3600, frame=1000)
    assert not cadence.due(4599)
    assert cadence.due(4600)
    assert not cadence.due(4601)
    # A reload rewinds the frame. The count starts again from there, not from the frame before it.
    assert not cadence.due(2000)
    assert not cadence.due(5599)
    assert cadence.due(5600)


def test_a_reload_goes_to_the_newest_settled_save_old_enough_in_game_time():
    meta = {'a': {'frame': 0}, 'b': {'frame': 5000}, 'c': {'frame': 9000, 'settled': False},
            'd': {'frame': 20000}, 'e': {}}
    store = SimpleNamespace(checkpoint_metadata=meta.get)
    saves = ['a', 'b', 'c', 'd', 'e']
    # A save inside a menu is passed over while a settled one is old enough.
    assert reload_target(store, saves, 9000 + LOOKBACK_FRAMES + 1) == 'b'
    assert reload_target(store, saves, 20000 + LOOKBACK_FRAMES + 1) == 'd'
    # It is used when it is the only save old enough. A save with no frame is never picked by frame.
    assert reload_target(store, ['c', 'd', 'e'], 9000 + LOOKBACK_FRAMES + 1) == 'c'
    # With nothing old enough the oldest save is the fallback.
    assert reload_target(store, saves, 1000) == 'a'
    assert reload_target(store, [], 1000) is None


def test_a_save_inside_a_menu_is_not_settled():
    assert settled({'settled': True}) and not settled({'settled': False})
    assert not settled({'policy_state': {'menu': {'task': 'pc'}}})
    assert settled({}) and settled({'policy_state': {}})


def gen1_game(frame):
    return SimpleNamespace(frame=frame, last_reload_frame=-10 ** 9, stuck_frame=frame, invalid_frame=None,
                           battle_frame=frame, policy=SimpleNamespace(hopeless_battle=lambda snapshot: False),
                           snapshot=None,
                           _unstick=Mock(), _check_stall=Mock())


def test_gen1_guards_wait_for_game_time_however_much_real_time_passes(monkeypatch):
    start = 10 ** 6
    game = gen1_game(start)
    # A day of real time on a paused game is neither stuck nor a battle that never ends.
    monkeypatch.setattr('pokesim.emulator.time.time', lambda: 10 ** 10)
    Emulator._check_guards(game)
    game._unstick.assert_not_called()
    # The battle limit is game seconds. The run kept moving in it, so only the battle guard fires.
    game.frame = game.stuck_frame = start + config.BATTLE_TIMEOUT_SECONDS * FRAMES_PER_SECOND + 1
    Emulator._check_guards(game)
    game._unstick.assert_called_once_with(start, 'battle never ended')


def test_gen1_stuck_guard_fires_on_the_same_frame_at_any_pace(monkeypatch):
    limit = config.STUCK_RELOAD_SECONDS * FRAMES_PER_SECOND
    for wall in (0, 10 ** 9):
        monkeypatch.setattr('pokesim.emulator.time.time', lambda: wall)
        game = gen1_game(5000)
        game.battle_frame = None
        game.frame = 5000 + limit
        Emulator._check_guards(game)
        game._unstick.assert_not_called()
        game.frame += 1
        Emulator._check_guards(game)
        game._unstick.assert_called_once_with(5000, 'stuck')
