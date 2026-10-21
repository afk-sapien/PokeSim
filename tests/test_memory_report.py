import json
import logging
import threading

from pokesim.runtime import memory_report


def test_snapshot_separates_python_from_the_allocator():
    data = memory_report.snapshot(top=3)
    assert data['objects'] > 0 and data['python_blocks'] > 0
    assert len(data['top_types']) == 3
    if data['malloc'] is not None:
        assert set(data['malloc']) == {'heap_mib', 'mmap_mib', 'in_use_mib', 'free_held_mib'}
    json.dumps(data)


def test_allocator_is_optional(monkeypatch):
    def missing(_):
        raise OSError('no libc')
    monkeypatch.setattr(memory_report.ctypes, 'CDLL', missing)
    assert memory_report.allocator() is None


def test_allocator_is_optional_on_windows(monkeypatch):
    def windows(_):
        raise TypeError("argument of type 'NoneType' is not iterable")
    monkeypatch.setattr(memory_report.ctypes, 'CDLL', windows)
    assert memory_report.allocator() is None


def test_report_logs_once_and_stops(caplog):
    stop = threading.Event()
    with caplog.at_level(logging.INFO, logger=memory_report.__name__):
        thread = memory_report.start('abc', 60, stop)
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith('memory abc '))
    assert 'rss_mib' in json.loads(line.split(' ', 2)[2])


def test_zero_minutes_turns_it_off():
    assert memory_report.start('abc', 0, threading.Event()) is None


class _Holder:
    def __init__(self):
        self.rows = [[1, 2], [3, 4]]


def test_lists_names_the_attribute_holding_a_list():
    holder = _Holder()
    skip = set()
    assert memory_report._owner(holder.rows[0], skip).endswith('_Holder.rows')
    data = memory_report.lists(sample=50, owners=5)
    assert data['shapes'] and data['owners']
    json.dumps(data)
