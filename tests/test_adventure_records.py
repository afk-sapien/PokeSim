"""First records distinguish new achievements from incomplete historical evidence."""
from dataclasses import replace

from pokesim.adventure_records import RecordTracker, status
from pokesim.events import Event
from pokesim.store import Store
from pokesim import shiny, statistics
from test_events import snap


def confirm(tracker, snapshot, now=100, seconds=3600, lower_bound=False):
    for _ in range(2):
        tracker.observe(snapshot, {'seconds': seconds, 'lower_bound': lower_bound}, now=now)


def records(store):
    return {row['key']: row for row in status(store)['milestones']}


def test_new_achievement_uses_app_clock_and_survives_pruning_rewind_and_restart(tmp_path):
    store = Store(tmp_path)
    tracker = RecordTracker(store)
    confirm(tracker, snap())
    confirm(tracker, snap(badges=1), now=200, seconds=7200)
    first = records(store)['first_badge']
    assert first['source'] == 'tracked' and first['seconds'] == 7200 and first['at'] == 200
    store.add_event(Event('badge', 'Badge'), snap(badges=1), None, None)
    with store.db:
        store.db.execute('UPDATE events SET ts=0')
    store.prune_events(1)
    assert store.events() == []
    reopened = RecordTracker(store)
    confirm(reopened, snap(), now=300)
    confirm(reopened, snap(badges=1), now=400, seconds=9000)
    assert records(store)['first_badge'] == first


def test_existing_save_does_not_get_a_fabricated_time(tmp_path):
    store = Store(tmp_path)
    with store.db:
        store.db.execute('INSERT INTO progress(ts,badges,owned,league,level100,perfect) VALUES (50,8,151,1,1,1)')
    tracker = RecordTracker(store)
    confirm(tracker, snap(badges=255, hall_of_fame_count=1), seconds=999999)
    rows = records(store)
    for key in ('first_badge', 'all_badges', 'champion', 'pokedex', 'level100', 'perfect'):
        assert rows[key]['achieved'] and rows[key]['seconds'] is None
        assert rows[key]['source'] == 'first_recorded' and rows[key]['at'] == 50


def test_existing_current_achievement_without_history_has_unknown_time(tmp_path):
    store = Store(tmp_path)
    tracker = RecordTracker(store)
    confirm(tracker, snap(badges=255), now=200)
    assert records(store)['all_badges']['seconds'] is None
    assert records(store)['all_badges']['source'] == 'first_recorded'


def test_new_run_resets_records_without_reimporting_old_progress(tmp_path):
    store = Store(tmp_path)
    store.add_event(Event('badge', 'Badge'), snap(badges=255), None, None)
    tracker = RecordTracker(store)
    tracker.reset(now=100)
    confirm(tracker, snap())
    tracker = RecordTracker(store)
    assert not records(store)['all_badges']['achieved']
    confirm(tracker, snap(badges=1), seconds=60)
    assert records(store)['first_badge']['seconds'] == 60


def test_invalid_transient_and_trade_observations_do_not_award_records(tmp_path):
    store = Store(tmp_path)
    tracker = RecordTracker(store)
    confirm(tracker, snap())
    tracker.observe(snap(badges=1))
    confirm(tracker, snap())
    store.set('trade_hold', True)
    confirm(tracker, snap(badges=1))
    assert not records(store)['first_badge']['achieved']


def test_shiny_sighting_is_not_acquisition_and_lower_bound_clock_is_preserved(tmp_path):
    store = Store(tmp_path)
    tracker = RecordTracker(store)
    confirm(tracker, snap())
    store.set(shiny.KEY, {**shiny.empty(), 'seen': 1})
    confirm(tracker, snap())
    assert not records(store)['shiny']['achieved']
    store.set(shiny.KEY, {**shiny.empty(), 'acquired': 1})
    confirm(tracker, snap(), lower_bound=True)
    assert records(store)['shiny']['seconds'] == 3600
    assert records(store)['shiny']['lower_bound']


def test_recent_changes_use_original_records_not_sampled_chart(tmp_path):
    from pokesim.catches import CatchTracker, SUPPORTED
    store = Store(tmp_path)
    tracker = CatchTracker(store, next(iter(SUPPORTED)), fresh=True)
    tracker.record('one', 1)
    from pokesim.catches import KEY
    store.set(KEY, {**store.get(KEY), 'started_at': 100000})
    with store.db:
        store.db.execute('UPDATE capture_receipts SET recorded_at=100001')
        store.db.executemany('INSERT INTO progress(ts,badges,owned,league,level100) VALUES (?,0,?,?,?)',
                             [(100000, 20, 2, 3), (110000, 22, 4, 5), (120000, 21, 5, 5)])
    result = statistics.recent(store, now=130000)['day']
    assert result['registered'] == 1 and result['league'] == 3 and result['level100'] == 2
    assert result['partial'] and result['catches'] == 1
    assert result['progress_since'] == 100000


def test_highlights_rate_known_moves_and_link_to_matching_pc_species():
    from test_statistics import individual
    from dataclasses import asdict
    first = asdict(replace(individual(), nick='A', moves=(33,)))
    second = asdict(replace(individual(), nick='B', level=100, moves=(57,)))
    result = statistics.highlights({'party': [first, second]})
    assert result['battle']['name'] == 'B'
    assert result['dvs']['value'] == 75
    assert 'q=%23' in result['battle']['url']
    assert statistics.highlights(None) == {'battle': None, 'dvs': None}


def test_recent_gifts_use_event_dates_and_flag_missing_history(tmp_path):
    from pokesim.catches import CatchTracker, SUPPORTED, KEY, record_gift
    store = Store(tmp_path)
    CatchTracker(store, next(iter(SUPPORTED)), fresh=True)
    store.set(KEY, {**store.get(KEY), 'started_at': 1})
    event = store.add_event(Event('obtain', 'Gift'), snap(), None, None)
    with store.db:
        store.db.execute('UPDATE events SET ts=10')
        record_gift(store.db, event, 153)
        store.db.execute('UPDATE capture_receipts SET recorded_at=190000')
    assert statistics.recent(store, now=200000)['day']['catches'] == 0
    with store.db:
        store.db.execute('UPDATE events SET ts=190000')
    assert statistics.recent(store, now=200000)['day']['catches'] == 1
    with store.db:
        store.db.execute('DELETE FROM events')
    result = statistics.recent(store, now=200000)['day']
    assert result['catches'] == 0 and result['undated_gifts'] and result['partial']


def test_matching_legacy_event_preserves_uncapped_cartridge_time(tmp_path):
    store = Store(tmp_path)
    store.add_event(Event('badge', 'First badge'), snap(badges=1, playtime=(3, 12, 4)), None, None)
    store.add_event(Event('champion', 'Champion! League victory #1'),
                    snap(badges=255, playtime=(255, 0, 0)), None, None)
    RecordTracker(store)
    rows = records(store)
    assert rows['first_badge']['seconds'] == 11524
    assert rows['first_badge']['clock_source'] == 'cartridge'
    assert rows['first_badge']['source'] == 'first_recorded'
    assert rows['all_badges']['seconds'] is None
