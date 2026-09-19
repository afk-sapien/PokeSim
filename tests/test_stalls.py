"""A run that plays on without achieving anything is reported once, then at a slow repeat."""
from types import SimpleNamespace

from pokesim.emulator import Emulator
from pokesim.stalls import FRAMES_PER_GAME_MINUTE as MINUTE, PROGRESS_EVENTS, StallWatch


def test_alert_needs_both_game_time_and_real_time():
    watch = StallWatch(game_minutes=120, real_minutes=15, repeat_hours=6)
    assert watch.check(0, 1000) is None
    assert watch.check(120 * MINUTE, 1000 + 60) is None          # Max pace: game time alone is not enough
    assert watch.check(10 * MINUTE, 1000 + 3600) is None         # slow pace: real time alone is not enough
    assert watch.check(125 * MINUTE, 1000 + 16 * 60) == (125, 16)


def test_alert_repeats_slowly_and_progress_starts_a_new_episode():
    watch = StallWatch(game_minutes=120, real_minutes=15, repeat_hours=6)
    watch.progress(0, 0)
    assert watch.check(200 * MINUTE, 3600)
    assert watch.check(400 * MINUTE, 2 * 3600) is None and watch.stalled(400 * MINUTE, 2 * 3600)
    assert watch.check(900 * MINUTE, 7 * 3600 + 1)
    watch.progress(900 * MINUTE, 8 * 3600)
    assert not watch.stalled(901 * MINUTE, 8 * 3600 + 60)
    assert watch.check(1100 * MINUTE, 9 * 3600)


def test_zero_game_minutes_disables_and_a_restore_restarts_the_clock():
    assert StallWatch(game_minutes=0).check(10 ** 9, 10 ** 9) is None
    watch = StallWatch(game_minutes=120, real_minutes=0)
    watch.progress(500 * MINUTE, 0)
    assert watch.check(100 * MINUTE, 50000) is None             # frame went backwards: a save was reloaded
    assert watch.quiet(101 * MINUTE, 50060) == (1, 1)


def test_managed_trades_do_not_count_as_progress():
    assert 'trade' not in PROGRESS_EVENTS and 'stall' not in PROGRESS_EVENTS and 'badge' in PROGRESS_EVENTS


def test_emulator_reports_a_stall_as_a_notable_event_with_the_objective():
    seen = []
    game = SimpleNamespace(
        stall=StallWatch(game_minutes=120, real_minutes=0), frame=130 * MINUTE,
        snapshot=SimpleNamespace(valid=True, started=True, map_name='Safari Zone Gate'),
        policy=SimpleNamespace(details=lambda: {'objective': {'title': 'Find the secret house'}, 'recoveries': 9}),
        _handle_events=lambda events, snap: seen.extend(events))
    game.stall.progress(0, 0)
    Emulator._check_stall(game, 600)
    Emulator._check_stall(game, 660)
    assert len(seen) == 1 and seen[0].type == 'stall' and seen[0].notable and seen[0].priority == 4
    assert 'Find the secret house' in seen[0].body and 'Safari Zone Gate' in seen[0].body and '9 recoveries' in seen[0].body
