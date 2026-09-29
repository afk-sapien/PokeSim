from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import psutil

from pokesim.app.resources import ProcessUsage, recent_activity


def test_usage_samples_deltas_and_reuses_reads_for_two_seconds(monkeypatch):
    process = SimpleNamespace(is_running=lambda: True, oneshot=nullcontext,
                              cpu_times=Mock(return_value=SimpleNamespace(user=10, system=2)),
                              memory_info=Mock(return_value=SimpleNamespace(rss=250 * 1048576)))
    monkeypatch.setattr('pokesim.app.resources.psutil.Process', lambda pid: process)
    moments = iter([10, 11, 14, 16])
    monkeypatch.setattr('pokesim.app.resources.time.monotonic', lambda: next(moments))
    usage = ProcessUsage(123)
    assert usage.sample() == {'cpu_percent': None, 'memory_bytes': 250 * 1048576}
    assert usage.sample()['cpu_percent'] is None
    assert process.cpu_times.call_count == 1
    process.cpu_times.return_value.user = 13
    assert usage.sample()['cpu_percent'] == 75
    process.cpu_times.return_value.user = 16
    assert usage.sample()['cpu_percent'] == 150


def test_exited_or_inaccessible_process_never_reports_stale_usage(monkeypatch):
    process = SimpleNamespace(is_running=Mock(return_value=True), oneshot=nullcontext,
                              cpu_times=Mock(return_value=SimpleNamespace(user=1, system=1)),
                              memory_info=Mock(return_value=SimpleNamespace(rss=42)))
    monkeypatch.setattr('pokesim.app.resources.psutil.Process', lambda pid: process)
    usage = ProcessUsage(123)
    assert usage.sample()['memory_bytes'] == 42
    process.is_running.return_value = False
    assert usage.sample() is None
    process.is_running.side_effect = psutil.AccessDenied(123)
    assert usage.sample() is None
    assert usage.previous is None


def test_activity_is_bounded_deduplicated_and_does_not_mutate_previous_summary():
    summary = {'recent_activity': []}
    for now, place in enumerate(['Pallet Town', 'Route 1', 'Viridian City', 'Route 2']):
        summary = {'recent_activity': recent_activity(summary, place, now)}
    assert [row['message'] for row in summary['recent_activity']] == ['Route 2', 'Viridian City', 'Route 1']
    same = recent_activity(summary, 'Route 2', 100)
    assert same == summary['recent_activity']
    assert same is not summary['recent_activity']


def test_real_process_reports_current_resident_memory():
    import os
    reading = ProcessUsage(os.getpid()).sample()
    assert reading['memory_bytes'] > 0
    assert reading['cpu_percent'] is None


def test_observed_speed_measures_emulation_and_expires_without_fresh_samples(monkeypatch):
    from pokesim.app.resources import ObservedSpeed
    now = [10.0]
    monkeypatch.setattr('pokesim.app.resources.time.monotonic', lambda: now[0])
    pace = ObservedSpeed()
    assert pace.sample() == {'observed_speed': None, 'speed_status': 'measuring'}
    pace.observe({'frames': 1000, 'sampled_at': 10})
    assert pace.sample()['observed_speed'] is None
    pace.observe({'frames': 1690, 'sampled_at': 15})
    now[0] = 15
    assert pace.sample() == {'observed_speed': 2.3, 'speed_status': 'ready'}
    pace.observe({'frames': 1690, 'sampled_at': 18})
    now[0] = 18
    assert pace.sample()['observed_speed'] == 0
    pace.observe({'frames': 12490, 'sampled_at': 21})
    now[0] = 21
    assert pace.sample()['observed_speed'] == 60
    now[0] = 37
    assert pace.sample() == {'observed_speed': None, 'speed_status': 'unavailable'}
    pace.observe({'frames': 12550, 'sampled_at': 37})
    assert pace.sample()['observed_speed'] is None
    pace.observe({'frames': 12730, 'sampled_at': 40})
    now[0] = 40
    assert pace.sample()['observed_speed'] == 1


def test_observed_speed_resets_on_missing_invalid_or_restarted_counters(monkeypatch):
    from pokesim.app.resources import ObservedSpeed
    monkeypatch.setattr('pokesim.app.resources.time.monotonic', lambda: 10)
    for invalid in [None, {'frames': True, 'sampled_at': 10},
                    {'frames': -1, 'sampled_at': 10}, {'frames': 500, 'sampled_at': float('nan')},
                    {'frames': 20, 'sampled_at': 10}, {'frames': 500, 'sampled_at': 5}]:
        pace = ObservedSpeed()
        pace.observe({'frames': 100, 'sampled_at': 5})
        pace.observe({'frames': 400, 'sampled_at': 10})
        assert pace.sample()['observed_speed'] == 1
        pace.observe(invalid)
        assert pace.sample()['observed_speed'] is None
