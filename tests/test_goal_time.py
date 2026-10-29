"""The goal panel counts play per goal and notes each stand-down once."""
from contextlib import closing

from pokesim import goal_time
from pokesim.planning.monitor import STAND_DOWNS, STOOD_DOWN
from pokesim.store import Store

HEAL, HUNT = ('heal', 'Heal'), ('hunt', 'Catch Pikachu')


def test_an_empty_adventure_has_nothing_counted(tmp_path):
    with closing(Store(tmp_path)) as store:
        assert goal_time.status(store) == {'available': False, 'since': None, 'current': None, 'frames': 0,
                                           'shares': [], 'other_frames': 0, 'stand_downs': []}


def test_counts_survive_a_restart_and_a_long_gap_is_not_counted(tmp_path):
    with closing(Store(tmp_path)) as store:
        tracker = goal_time.GoalTime(store)
        tracker.observe(HEAL, {}, 100, now=10)
        tracker.observe(HUNT, {}, 130, now=11)
        tracker.flush(now=12)
        tracker = goal_time.GoalTime(store)
        # The first observation after a restart has nothing to count against.
        tracker.observe(HUNT, {}, 5000, now=20)
        tracker.observe(HUNT, {}, 5090, now=21)
        tracker.observe(HUNT, {}, 5090 + goal_time.LONGEST_GAP + 1, now=22)
        tracker.flush(now=23)
        result = goal_time.status(store)
    assert result['since'] == 10 and result['frames'] == 120
    assert [(row['key'], row['frames']) for row in result['shares']] == [('hunt', 90), ('heal', 30)]
    assert result['current'] == {'key': 'hunt', 'label': 'Catch Pikachu', 'since': 11}


def test_each_stand_down_is_noted_once_and_a_rewind_is_not_one(tmp_path):
    with closing(Store(tmp_path)) as store:
        tracker = goal_time.GoalTime(store)
        # Stand-downs already on record when counting starts are not new.
        record = {STOOD_DOWN: {'old': 5}, STAND_DOWNS: {'old': 1}}
        tracker.observe(HUNT, record, 100, now=10)
        record = {STOOD_DOWN: {'old': 5, 'hunt:25': 120}, STAND_DOWNS: {'old': 1, 'hunt:25': 1}}
        tracker.observe(HEAL, record, 130, now=11)
        # A reload restores older times and drops the newest entry, then it stands down again.
        tracker.observe(HEAL, {STOOD_DOWN: {'old': 2}, STAND_DOWNS: {'old': 1}}, 160, now=12)
        tracker.observe(HEAL, {STOOD_DOWN: {'old': 2, 'hunt:25': 110}, STAND_DOWNS: {'old': 1, 'hunt:25': 2}},
                        190, now=13)
        tracker.flush(now=14)
        result = goal_time.status(store)
    # The newest is listed first. Each is named after the goal that was running.
    assert result['stand_downs'] == [{'key': 'hunt:25', 'label': 'Heal', 'at': 13, 'in_a_row': 2},
                                     {'key': 'hunt:25', 'label': 'Catch Pikachu', 'at': 11, 'in_a_row': 1}]


def test_only_the_largest_goals_are_kept_and_shown(tmp_path, monkeypatch):
    monkeypatch.setattr(goal_time, 'KEPT_GOALS', 3)
    monkeypatch.setattr(goal_time, 'SHOWN_GOALS', 2)
    with closing(Store(tmp_path)) as store:
        tracker = goal_time.GoalTime(store)
        frame = 0
        for index, frames in enumerate((10, 40, 30, 20)):
            tracker.observe((f'goal{index}', f'Goal {index}'), {}, frame, now=1)
            frame += frames
            tracker.observe((f'goal{index}', f'Goal {index}'), {}, frame, now=1)
        tracker.flush(now=2)
        result = goal_time.status(store)
        kept = sorted(goal_time.GoalTime(store).value['goals'])
    assert kept == ['goal1', 'goal2', 'goal3']
    assert [row['key'] for row in result['shares']] == ['goal1', 'goal2'] and result['other_frames'] == 20
