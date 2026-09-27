"""Long-running stats survive saves without inventing historical activity."""
from dataclasses import replace
import json

from fastapi.testclient import TestClient
from types import SimpleNamespace

from pokesim import statistics
from pokesim.catches import CatchTracker, SUPPORTED
from pokesim.events import Event
from pokesim.pokemon import stored_strength
from pokesim.ram import PartyMon, StoredMon
from pokesim.screen import W_ENEMY_HP, W_ENEMY_MAX_HP
from pokesim.store import Store
from pokesim.web.app import create_app
from test_events import snap


def individual():
    return PartyMon(153, 30, 30, 15, 'LEAF', dvs=(15,) * 5, stat_exp=(0,) * 5, trainer_id=100)


def observe(tracker, frame, *, now=100, **kwargs):
    tracker.observe(snap(frame=frame, party=(individual(),), **kwargs), now=now)


def test_power_and_dvs_include_every_box_and_team_without_duplicates():
    mon = individual()
    box = StoredMon(4, 0, 153, 15, 'BUD', (), 3375, (0,) * 5, (0,) * 5, 100)
    snapshot = snap(party=(mon,), stored_details=(box,), stored_pokemon=((4, 153, 15, 'BUD'),))
    data = statistics.collection(snapshot)
    assert data['held'] == 2
    assert data['average_dv'] == 50
    assert data['high_quality_held'] == 1
    assert data['collection_power'] == stored_strength(vars(mon))['power'] + stored_strength(vars(box))['power']
    assert data['strongest_six_power'] == data['collection_power']
    assert statistics.collection(snap())['collection_power'] is None


def test_steps_reject_warps_invalid_gaps_restores_and_trade_holds(tmp_path):
    store = Store(tmp_path)
    tracker = statistics.StatisticsTracker(store)
    observe(tracker, 0)
    observe(tracker, 30, x=6)
    observe(tracker, 60, x=20)
    observe(tracker, 90, map=2, x=21)
    observe(tracker, 999, x=22)
    tracker.reset_baseline()
    observe(tracker, 1000, x=23)
    store.set('trade_hold', True)
    observe(tracker, 1030, x=24)
    store.set('trade_hold', None)
    observe(tracker, 1060, x=25)
    observe(tracker, 1090, x=26)
    tracker.flush(now=200)
    assert statistics.status(store)['current']['steps'] == 2
    reopened = statistics.StatisticsTracker(Store(tmp_path))
    observe(reopened, 1, x=0, now=300)
    observe(reopened, 31, x=1, now=301)
    reopened.flush(now=302)
    assert statistics.status(reopened.store)['current']['steps'] == 3


def test_observed_damage_rejects_switches_healing_and_new_battles(tmp_path):
    store = Store(tmp_path)
    tracker = statistics.StatisticsTracker(store)
    memory = bytearray(65536)
    memory[W_ENEMY_MAX_HP + 1] = 100
    memory[W_ENEMY_HP + 1] = 100
    mon = individual()
    def sample(frame, hp, enemy_hp, **kwargs):
        memory[W_ENEMY_HP + 1] = enemy_hp
        tracker.observe(snap(frame=frame, party=(replace(mon, hp=hp),), **kwargs), memory, now=100 + frame)
    sample(0, 30, 100)
    sample(30, 30, 100, in_battle=1, enemy_species=84)
    sample(60, 20, 70, in_battle=1, enemy_species=84)
    sample(90, 30, 100, in_battle=1, enemy_species=84)
    sample(120, 30, 30, in_battle=1, enemy_species=85)
    sample(150, 30, 0)
    tracker.flush(now=300)
    data = statistics.status(store)['current']
    assert data['damage_taken'] == 10
    assert data['damage_dealt'] == 30
    assert data['battles'] == 1


def test_capture_receipts_and_existing_marathons_seed_stats_once(tmp_path):
    store = Store(tmp_path)
    catches = CatchTracker(store, next(iter(SUPPORTED)), fresh=True)
    catches.record('first', 1)
    catches.record('first', 1)
    store.add_event(Event('marathon', 'Kanto Marathon finished!'), snap(), None, None)
    store.add_event(Event('marathon', 'Kanto Marathon called off'), snap(), None, None)
    tracker = statistics.StatisticsTracker(store)
    observe(tracker, 0)
    observe(tracker, 30)
    tracker.flush(now=200)
    tracker.flush(now=201)
    assert statistics.status(store)['current']['captures'] == 1
    assert statistics.status(store)['current']['marathons'] == 1
    catches.reset()
    tracker.flush(now=202)
    catches.record('second', 2)
    tracker.flush(now=203)
    assert statistics.status(store)['current']['captures'] == 2


def test_hourly_history_compacts_old_days_and_keeps_latest(tmp_path):
    store = Store(tmp_path)
    tracker = statistics.StatisticsTracker(store)
    observe(tracker, 0)
    observe(tracker, 30)
    with store.db:
        for hour in range(24 * 60):
            store.db.execute('INSERT OR REPLACE INTO statistics_history VALUES (?, ?, ?)',
                             (hour, hour * 3600, json.dumps({'steps': hour})))
    tracker.flush(now=60 * statistics.DAY)
    rows = list(store.db.execute('SELECT ts FROM statistics_history'))
    assert len(rows) <= 30 + 24 * 30 + 1
    result = statistics.status(store)
    assert len(result['history']) <= 600
    assert result['history'][-1]['ts'] == 60 * statistics.DAY
    assert result['history'][0]['ts'] == 100
    assert result['history'][1]['ts'] == 23 * 3600


def test_stats_routes_are_scoped_and_entries_do_not_load_charts(tmp_path):
    store = Store(tmp_path)
    client = TestClient(create_app(SimpleNamespace(status=lambda: {}), store, base_path='/games/red', adventure_id='red'))
    entries = client.get('/journal').text
    stats = client.get('/journal/stats').text
    assert '/games/red/journal/stats' in entries
    assert 'progress.js' not in entries
    assert '/games/red/static/statistics.js' in stats
    assert 'aria-current="page">Stats' in stats
    result = client.get('/api/statistics').json()
    returns = result.pop('legendary_returns')
    assert returns['interval'] == 1000000 and not returns['available']
    assert result == {
        'started_at': None, 'updated_at': None, 'current': {}, 'history': []}


def test_large_counters_survive_restart(tmp_path):
    store = Store(tmp_path)
    tracker = statistics.StatisticsTracker(store)
    observe(tracker, 0)
    observe(tracker, 30)
    tracker.value['counters']['steps'] = 10_000_000_000
    tracker.flush(now=300)
    reopened = statistics.StatisticsTracker(Store(tmp_path))
    assert reopened.value['counters']['steps'] == 10_000_000_000


def test_malformed_and_stale_collection_does_not_become_zero(tmp_path):
    store = Store(tmp_path)
    tracker = statistics.StatisticsTracker(store)
    observe(tracker, 0)
    tracker.observe(snap(frame=30), now=101)
    assert tracker.gauges is None
    tracker.observe(snap(frame=60), now=102)
    tracker.flush(now=103)
    current = statistics.status(store)['current']
    assert current['collection_power'] is None
    assert current['average_dv'] is None


def test_thirty_second_flush_is_atomic_and_first_baseline_survives(tmp_path):
    store = Store(tmp_path)
    tracker = statistics.StatisticsTracker(store)
    observe(tracker, 0)
    observe(tracker, 30, x=6)
    observe(tracker, 60, x=7, now=110)
    assert statistics.status(store)['current']['steps'] == 1
    observe(tracker, 90, x=8, now=131)
    data = statistics.status(store)
    assert data['current']['steps'] == 3
    assert data['history'][0]['steps'] == 1
    assert data['history'][-1]['steps'] == 3


def test_hundred_thousand_hour_history_is_bounded(tmp_path):
    store = Store(tmp_path)
    with store.db:
        store.db.executemany('INSERT INTO statistics_history VALUES (?, ?, ?)',
                             ((hour, hour * 3600, json.dumps({'steps': hour * 100000}))
                              for hour in range(100_001)))
    data = statistics.status(store)
    assert len(data['history']) <= 600
    assert data['history'][0]['steps'] == 0
    assert data['history'][-1]['steps'] == 10_000_000_000


def test_save_before_first_observation_keeps_collection_on_restart(tmp_path):
    store = Store(tmp_path)
    tracker = statistics.StatisticsTracker(store)
    observe(tracker, 0)
    observe(tracker, 30)
    before = statistics.status(store)['current']
    restored = statistics.StatisticsTracker(store)
    restored.flush(now=200)
    after = statistics.status(store)['current']
    assert {key: after[key] for key in statistics.GAUGES} == {key: before[key] for key in statistics.GAUGES}


def test_failed_history_transaction_does_not_consume_capture_delta(tmp_path):
    import sqlite3
    import pytest
    store = Store(tmp_path)
    catches = CatchTracker(store, next(iter(SUPPORTED)), fresh=True)
    tracker = statistics.StatisticsTracker(store)
    observe(tracker, 0)
    observe(tracker, 30)
    catches.record('new-capture', 25)
    with store.db:
        store.db.execute("CREATE TRIGGER reject_stats BEFORE INSERT ON statistics_history "
                         "BEGIN SELECT RAISE(ABORT, 'test failure')" + chr(59) + ' END')
    with pytest.raises(sqlite3.IntegrityError):
        tracker.flush(now=200)
    assert tracker.value['capture_baseline'] == 0
    assert statistics.status(store)['current']['captures'] == 0
    with store.db:
        store.db.execute('DROP TRIGGER reject_stats')
    tracker.flush(now=201)
    tracker.flush(now=202)
    assert statistics.status(store)['current']['captures'] == 1
