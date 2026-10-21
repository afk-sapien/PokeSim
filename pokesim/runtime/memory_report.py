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
import random
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
    except (OSError, AttributeError, TypeError):  # Windows cannot open the C library by None
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


def _describe(obj):
    if isinstance(obj, dict):
        return f'dict[{len(obj)}]'
    if isinstance(obj, (list, tuple, set, frozenset)):
        return f'{type(obj).__name__}[{len(obj)}]'
    return type(obj).__name__


def _key_of(mapping, target):
    for key, value in mapping.items():
        if value is target:
            return key
    return ''


def _owner(obj, skip, depth=16):
    """A short chain of what holds ``obj``, naming the attribute or key at each step."""
    chain = []
    skip = set(skip)
    for _ in range(depth):
        holders = [r for r in gc.get_referrers(obj) if id(r) not in skip and not isinstance(r, type(sys._getframe()))]
        # The previous step's list of holders refers to this holder too.
        skip.add(id(holders))
        if not holders:
            break
        holder = holders[0]
        name = ''
        # Objects with inline attribute values refer to them directly, not through a dict.
        attrs = getattr(holder, '__dict__', None)
        if isinstance(attrs, dict) and not isinstance(holder, type):
            name = _key_of(attrs, obj)
            if name:
                chain.append(f'{type(holder).__name__}.{name}')
                break
        if isinstance(holder, dict):
            key = _key_of(holder, obj)
            name = repr(key)[:40] if key != '' else ''
            owners = [r for r in gc.get_referrers(holder) if getattr(r, '__dict__', None) is holder]
            skip.add(id(owners))
            if owners:
                chain.append(f'{type(owners[0]).__name__}.{name.strip(chr(39))}')
                break
        chain.append(f'{_describe(holder)}{"[" + name + "]" if name else ""}')
        obj = holder
    # Nested containers repeat, so keep the first holder and the last few, where a name appears.
    if len(chain) > 4:
        chain = chain[:1] + ['...'] + chain[-3:]
    return ' <- '.join(chain)


def lists(sample=2000, owners=12):
    """Shapes of a random sample of live lists, and what holds a few of them."""
    found = [obj for obj in gc.get_objects() if type(obj) is list]
    picked = random.sample(found, min(sample, len(found)))
    shapes = Counter(f'{len(x)}:{type(x[0]).__name__ if x else "-"}' for x in picked)
    traced = picked[:owners]
    skip = {id(found), id(picked), id(traced)}
    held = Counter()
    for x in traced:
        held[_owner(x, skip)] += 1
    del found, picked, traced, x
    return {'shapes': dict(shapes.most_common(8)), 'owners': dict(held.most_common(8))}


def snapshot(top=12, detail=False):
    counts = Counter(type(obj).__name__ for obj in gc.get_objects())
    data = {'rss_mib': rss_mib(), 'malloc': allocator(),
            'python_blocks': sys.getallocatedblocks(), 'objects': sum(counts.values()),
            'top_types': dict(counts.most_common(top))}
    if detail:
        data['lists'] = lists()
    return data


def start(adventure_id, minutes, stop):
    """Log a snapshot every ``minutes`` until ``stop`` is set. Zero turns it off."""
    if minutes <= 0:
        return None

    def report():
        reports = 0
        while True:
            try:
                # Tracing owners walks every object, so it runs on every third report only.
                data = snapshot(detail=reports % 3 == 1)
                reports += 1
                log.info('memory %s %s', adventure_id, json.dumps(data, separators=(',', ':')))
            except Exception:
                log.exception('memory report failed')
            if stop.wait(minutes * 60):
                return

    thread = threading.Thread(target=report, name='memory-report', daemon=True)
    thread.start()
    return thread
