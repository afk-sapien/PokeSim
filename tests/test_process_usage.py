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
