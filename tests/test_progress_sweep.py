"""The progress sweep: a game is stalled only after too long without real progress for its stage.

The rows come from the original games' progress tables and journals.
"""
import sqlite3
from types import SimpleNamespace

import pytest

from pokesim import progress
from pokesim.app import progress_sweep
from pokesim.app.watchdog import Limits, Watchdog
from pokesim.store import SCHEMA
from test_watchdog import AID, Clock, FakeRegistry, Process, game, status

HOUR = 3600
# Red, 7 badges to the League: Victory Road and the Elite Four took 4.4 hours with no new progress row.
RED_STORY = [(1789857822.1669958, 7, 59, None, 0, None, None), (1789857955.821814, 7, 60, None, 0, None, None),
             (1789857971.118649, 8, 60, None, 0, None, None), (1789859537.870777, 8, 64, None, 0, None, None)]
RED_LAST_AREA = 1789859427.5016992
RED_LEAGUE = (1789875222.0901506, 8, 64, None, 1, None, None)
# Silver Cave, training BEEFSCOUT (collection_train) after its last Pokédex change.
SILVER = (1794230405.0635643, 16, 251, 251, 2383, 166, 0)


class Adventure:
    def __init__(self, root, aid=AID):
        folder = root / 'adventures' / aid
        folder.mkdir(parents=True)
        self.db = sqlite3.connect(folder / 'pokesim.sqlite', isolation_level=None)
        self.db.executescript(SCHEMA + progress.SCHEMA)

    def row(self, row):
        self.db.execute('INSERT INTO progress(ts, badges, owned, seen, league, level100, perfect) '
                        'VALUES (?,?,?,?,?,?,?)', row)

    def event(self, ts, kind, title='entry', place=''):
        self.db.execute('INSERT INTO events(ts, type, title, map) VALUES (?,?,?,?)', (ts, kind, title, place))


@pytest.fixture
def sweep(tmp_path):
    clock = Clock()
    registry = FakeRegistry()
    sent = []
    manager = SimpleNamespace(
        registry=registry, closing=False, suspended=False, root=tmp_path,
        supervisor=SimpleNamespace(children={}, worker_output=None),
        coordinator=SimpleNamespace(reserved=lambda aid: False),
        notifications=SimpleNamespace(alert=lambda title, body, adventure_id=None: sent.append((title, body)) and None))
    # Only the sweep may speak here: the hour-long quiet check reads worker summaries these tests keep still.
    watchdog = Watchdog(manager, clock=clock, limits=Limits(no_progress=10 ** 9, sweep=0), environ={})
    adventure = Adventure(tmp_path)

    def start(now, version='red', seen=None):
        clock.now = now
        watchdog.started = now - Limits().grace - 1
        registry.rows = [game(version=version)]
        manager.supervisor.children[AID] = SimpleNamespace(process=Process(), watch=(now, seen or status()))

    def at(now, seen=None):
        clock.now = now
        child = manager.supervisor.children[AID]
        child.watch = (now, seen or child.watch[1])
        watchdog.tick()
        return [row for row in watchdog.public()['problems'] if row['kind'] == 'stalled']

    def kinds():
        return sorted(row['kind'] for row in watchdog.public()['problems'])
    return SimpleNamespace(adventure=adventure, start=start, at=at, sent=sent, kinds=kinds)


def test_the_story_limit_is_twice_the_slowest_stage_with_a_three_hour_floor():
    assert progress_sweep.limit(1, 8, 0) == 2 * 15684
    assert progress_sweep.limit(1, 3, 0) == 3 * HOUR
    # Gold, Silver and Crystal keep playing the story in Kanto after their first League win.
    assert progress_sweep.limit(2, 8, 5) == 3 * HOUR
    assert progress_sweep.limit(2, 16, 1) == progress_sweep.limit(1, 8, 1) == 24 * HOUR


def test_red_at_the_league_is_not_stalled_for_as_long_as_the_original_took(sweep):
    for row in RED_STORY:
        sweep.adventure.row(row)
    sweep.adventure.event(RED_LAST_AREA, 'map')
    last = RED_STORY[-1][0]
    sweep.start(last)
    assert sweep.at(RED_LEAGUE[0]) == []
    assert sweep.at(last + 2 * 15684 - 60) == []
    stalled = sweep.at(last + 2 * 15684 + 60)
    assert [row['message'] for row in stalled] == [
        'Mischievous Badge Hunt has gone 8 hours and 43 minutes without a badge, a new area, a new Pokédex entry '
        'or a League win, at 8 badges.']
    sweep.adventure.row(RED_LEAGUE)
    assert sweep.at(last + 2 * 15684 + 120) == []
    assert [title for title, _ in sweep.sent] == ['Needs attention', 'Recovered']


def test_a_gen2_postgame_that_only_gains_trainee_levels_is_not_stalled(sweep):
    sweep.adventure.row(SILVER)
    start = SILVER[0]
    sweep.start(start, 'silver')
    level = 60
    for minute in range(25, 40 * 60, 25):
        if minute % 50 == 0:
            level += 1
            sweep.adventure.event(start + minute * 60, 'level', f'BEEFSCOUT grew to level {level}')
        if minute % 60 < 25:
            assert sweep.at(start + minute * 60) == []
    assert sweep.at(start + 40 * HOUR) == []
    assert sweep.sent == []


def test_a_postgame_day_without_a_level_league_win_or_dex_change_is_one_alert(sweep):
    sweep.adventure.row(SILVER)
    start = SILVER[0]
    sweep.adventure.event(start + HOUR, 'level', 'BEEFSCOUT grew to level 83')
    sweep.start(start + HOUR, 'silver')
    # Exp, repeat catches and other entries keep coming, and none of them is progress.
    for hour in range(2, 25):
        sweep.adventure.event(start + hour * HOUR, 'catch', 'Caught Golbat!')
        sweep.adventure.event(start + hour * HOUR + 1, 'trainer', 'Beat Cooltrainer Nick')
        sweep.adventure.event(start + hour * HOUR + 2, 'release', 'Said goodbye to a spare Golbat')
        assert sweep.at(start + hour * HOUR + 3) == []
    stalled = sweep.at(start + 25 * HOUR + 60)
    assert [row['message'] for row in stalled] == [
        'Mischievous Badge Hunt has gone 24 hours and 1 minute without a League win, a Pokédex change or a level up.']
    for hour in range(26, 30):
        assert len(sweep.at(start + hour * HOUR)) == 1
    assert sweep.sent == [('Needs attention', stalled[0]['message'])]
    sweep.adventure.row((start + 30 * HOUR, *SILVER[1:5], 167, 0))
    assert sweep.at(start + 30 * HOUR + 60) == []
    assert [title for title, _ in sweep.sent] == ['Needs attention', 'Recovered']


def test_story_levels_do_not_count_and_a_new_area_does(sweep):
    for row in RED_STORY[:2]:
        sweep.adventure.row(row)
    last = RED_STORY[1][0]
    sweep.adventure.event(last + HOUR, 'level', 'SPOONMAYOR grew to level 40')
    sweep.start(last)
    assert len(sweep.at(last + 3 * HOUR + 60)) == 1
    sweep.adventure.event(last + 3 * HOUR + 90, 'map', 'Found Route 23')
    assert sweep.at(last + 3 * HOUR + 120) == []


def test_a_library_outside_the_app_reads_the_same_way(tmp_path):
    red = Adventure(tmp_path, 'a' * 32)
    for row in RED_STORY:
        red.row(row)
    (tmp_path / 'adventures' / ('a' * 32) / 'adventure.json').write_text('{"name": "Red", "version": "red"}')
    Adventure(tmp_path, 'b' * 32)
    (tmp_path / 'adventures' / ('b' * 32) / 'adventure.json').write_text('{"name": "Gold", "version": "gold"}')
    now = RED_STORY[-1][0] + 2 * 15684 + 360
    assert progress_sweep.library(tmp_path, now) == [
        f'{"a" * 32} Red: STALLED, 8.8 h without progress, limit 8.7 h, 8 badges',
        f'{"b" * 32} Gold: no progress yet']


def test_time_held_still_never_counts(sweep):
    sweep.adventure.row(SILVER)
    start = SILVER[0]
    sweep.start(start, 'silver')
    assert sweep.at(start + 20 * HOUR, status(paused=True)) == []
    assert sweep.at(start + 30 * HOUR, status(paused=True)) == []
    assert sweep.at(start + 53 * HOUR, status()) == []
    assert len(sweep.at(start + 54 * HOUR + 60)) == 1


# Gold at Violet Gym with 0 badges: the last progress row, then two reloads 34 minutes apart.
VIOLET_ROW = (1794247024.4673505, 0, 4, None, 0, None, None)
VIOLET_STALLS = (1794247332.24468, 1794249403.3313262)


def test_two_stalls_at_one_place_within_an_hour_alert_at_once(sweep):
    sweep.adventure.row(VIOLET_ROW)
    sweep.adventure.event(VIOLET_STALLS[0] - 600, 'stall', 'Stuck?', 'Route 31')
    sweep.adventure.event(VIOLET_STALLS[0], 'stall', 'Stuck? The adventure had to reload twice', 'Violet Gym')
    sweep.start(VIOLET_STALLS[0] + 60, 'gold')
    # One stall here and one somewhere else is the game's own recovery doing its job.
    assert sweep.at(VIOLET_STALLS[0] + 60) == [] and sweep.kinds() == []
    sweep.adventure.event(VIOLET_STALLS[1], 'stall', 'Stuck? The adventure had to reload twice', 'Violet Gym')
    sweep.at(VIOLET_STALLS[1] + 60)
    # The three hour floor is still far off, and the repeat does not wait for it.
    assert sweep.kinds() == ['repeat_stall']
    assert sweep.sent == [('Needs attention', 'Mischievous Badge Hunt got stuck 2 times at Violet Gym within 35 minutes.')]
    sweep.at(VIOLET_STALLS[0] + HOUR + 60)
    assert sweep.kinds() == [] and [title for title, _ in sweep.sent] == ['Needs attention', 'Recovered']


def test_full_boxes_and_a_day_without_a_catch_alert(sweep):
    sweep.adventure.row(SILVER)
    start = SILVER[0]
    sweep.adventure.event(start, 'catch', 'Caught Golbat!')
    full = status(watch={'map': 1, 'owned': 251, 'badges': 16, 'hall_of_fame': 3, 'boxes_full': True})
    sweep.start(start, 'silver')
    sweep.at(start + 23 * HOUR, full)
    assert 'boxes_full' not in sweep.kinds()
    sweep.at(start + 24 * HOUR + 60, full)
    assert 'boxes_full' in sweep.kinds()
    assert ('Needs attention', 'Mischievous Badge Hunt has full boxes and has caught nothing for 24 hours and 1 minute.') in sweep.sent
    sweep.at(start + 24 * HOUR + 120, status())
    assert 'boxes_full' not in sweep.kinds()


def test_the_supervisor_summary_says_when_every_box_is_full():
    from pokesim.web.app import status_summary
    def boxes(*counts):
        return status_summary({'game': {'storage': {'box_counts': list(counts), 'capacity': 20}}})['watch']['boxes_full']
    assert boxes(20, 20, 20) is True
    assert boxes(20, 19, 20) is False
    assert boxes() is False
