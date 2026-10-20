"""Periodic memory figures for a worker, to tell a Python leak from a native one (issue #111).

The line separates three things. Python objects that are still alive, memory the C
allocator holds but has freed (fragmentation), and what the process holds in total.
"""
from __future__ import annotations

from collections import Counter
import ctypes
import gc
import json
import logging
import sys
import threading

log = logging.getLogger(__name__)
MIB = 2 ** 20


class _Mallinfo2(ctypes.Structure):
    _fields_ = [(name, ctypes.c_size_t) for name in (
        'arena', 'ordblks', 'smblks', 'hblks', 'hblkhd', 'usmblks', 'fsmblks',
        'uordblks', 'fordblks', 'keepcost')]


def allocator():
    """glibc totals over every arena, or None where mallinfo2 is missing."""
    try:
        libc = ctypes.CDLL(None)
        call = libc.mallinfo2
    except (OSError, AttributeError):
        return None
    call.restype = _Mallinfo2
    info = call()
    return {'heap_mib': round(info.arena / MIB, 1), 'mmap_mib': round(info.hblkhd / MIB, 1),
            'in_use_mib': round(info.uordblks / MIB, 1), 'free_held_mib': round(info.fordblks / MIB, 1)}


def rss_mib():
    try:
        with open('/proc/self/status') as status:
            for line in status:
                if line.startswith('VmRSS:'):
                    return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    return None


def snapshot(top=12):
    counts = Counter(type(obj).__name__ for obj in gc.get_objects())
    return {'rss_mib': rss_mib(), 'malloc': allocator(),
            'python_blocks': sys.getallocatedblocks(), 'objects': sum(counts.values()),
            'top_types': dict(counts.most_common(top))}


def start(adventure_id, minutes, stop):
    """Log a snapshot every ``minutes`` until ``stop`` is set. Zero turns it off."""
    if minutes <= 0:
        return None

    def report():
        while True:
            try:
                log.info('memory %s %s', adventure_id, json.dumps(snapshot(), separators=(',', ':')))
            except Exception:
                log.exception('memory report failed')
            if stop.wait(minutes * 60):
                return

    thread = threading.Thread(target=report, name='memory-report', daemon=True)
    thread.start()
    return thread
