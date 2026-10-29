"""Money earned and spent, by source, as both generations count it."""
from contextlib import closing
from dataclasses import replace
import json

from pokesim import money_flow
from pokesim.statistics import KEY, StatisticsTracker
from pokesim.store import Store
from test_events import snap


def purse(frame, money, in_battle=0, fainted=False):
    party = snap().party
    if fainted:
        party = tuple(replace(mon, hp=0) for mon in party)
    return snap(frame=frame, money=money, in_battle=in_battle, party=party)


# A trainer battle pays 500, a shop takes 200, a sale gives 100 and a blackout halves the purse.
DAY = [purse(100, 3000), purse(130, 3000, 2), purse(160, 3500, 2), purse(190, 3500), purse(220, 3300),
       purse(250, 3400), purse(280, 3400, fainted=True), purse(310, 1700), purse(400, 1700)]


def test_each_change_is_counted_once_by_its_source():
    flow, value = money_flow.MoneyFlow(), {}
    for before, after in zip(DAY, DAY[1:]):
        flow.observe(value, before, after, 50.0)
    assert value['money'] == {'since': 50.0, 'battles': 500, 'other': 100, 'shops': 200, 'blackouts': 1700}


def test_a_drop_long_after_a_blackout_is_a_shop():
    flow, value = money_flow.MoneyFlow(), {}
    flow.observe(value, purse(0, 1000, fainted=True), purse(30, 500), 1.0)
    flow.observe(value, purse(30, 500), purse(30 + money_flow.BLACKOUT_FRAMES + 30, 400), 1.0)
    assert (value['money']['blackouts'], value['money']['shops']) == (500, 100)
    # A reload breaks the run of observations, so a later drop is not blamed on the old blackout.
    flow.observe(value, purse(0, 1000, fainted=True), purse(30, 1000), 1.0)
    flow.reset()
    flow.observe(value, purse(60, 1000), purse(90, 900), 1.0)
    assert value['money']['shops'] == 200


def test_the_tracker_keeps_counts_across_a_restart(tmp_path):
    with closing(Store(tmp_path)) as store:
        assert money_flow.status(store)['available'] is False
        tracker = StatisticsTracker(store)
        for index, snapshot in enumerate(DAY[:5]):
            tracker.observe(snapshot, now=100 + index)
        tracker.flush(now=200)
        tracker = StatisticsTracker(store)
        for index, snapshot in enumerate(DAY[4:]):
            tracker.observe(snapshot, now=300 + index)
        tracker.flush(now=400)
        result = money_flow.status(store)
    assert result == {'available': True, 'since': 101, 'complete_history': True, 'earned': 600, 'spent': 1900,
                      'net': -1300, 'sources': {'battles': 500, 'other': 100, 'shops': 200, 'blackouts': 1700}}


def test_an_adventure_from_before_counting_says_from_when(tmp_path):
    with closing(Store(tmp_path)) as store:
        # Statistics from an older version have no money record.
        store.set(KEY, {'started_at': 10.0, 'current': {}, 'counters': {
            'steps': 4, 'battles': 1, 'damage_dealt': 0, 'damage_taken': 0, 'active_frames': 60}})
        tracker = StatisticsTracker(store)
        tracker.observe(purse(0, 100), now=5000)
        tracker.observe(purse(30, 300, 1), now=5001)
        tracker.flush(now=5002)
        result = money_flow.status(store)
        saved = json.loads(store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()[0])
    assert saved['counters']['steps'] == 4 and saved['started_at'] == 10.0
    assert (result['since'], result['complete_history'], result['earned']) == (5001, False, 200)
