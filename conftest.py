"""Slow tests that run only on request, and optional sharding so CI can run one suite as several jobs.

A test marked `slow` is skipped unless POKESIM_SLOW_TESTS=1. The local nightly run sets it.

Set POKESIM_TEST_SHARD to "index/total" (for example "2/4"). Whole test modules are assigned to shards by
their recorded run time in tests/durations.json, so tests that share module state stay together and the
shards finish close together. A module with no recorded time counts the recorded median per test for each
of its tests. Without the variable every test runs. The shards together always cover exactly the full
suite, and a shard that selects nothing is an error. `python tools/record_durations.py` rewrites the file.
"""
import json
import os
from pathlib import Path

import pytest

DURATIONS = Path(__file__).resolve().parent / 'tests' / 'durations.json'
SLOW_SKIP = pytest.mark.skip(reason='set POKESIM_SLOW_TESTS=1 to run the slow tests, as the local nightly run does')


def recorded():
    """Recorded seconds per test module and per test, or empty maps when the file is missing."""
    try:
        data = json.loads(DURATIONS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}, 1.0
    modules = {name: float(entry['seconds']) for name, entry in data.get('modules', {}).items()}
    per_test = sorted(float(entry['seconds']) / max(1, int(entry['tests'])) for entry in data.get('modules', {}).values())
    return modules, per_test[len(per_test) // 2] if per_test else 1.0


def pytest_collection_modifyitems(config, items):
    if os.environ.get('POKESIM_SLOW_TESTS') != '1':
        for item in items:
            if item.get_closest_marker('slow'):
                item.add_marker(SLOW_SKIP)
    spec = os.environ.get('POKESIM_TEST_SHARD')
    if not spec:
        return
    index, total = (int(part) for part in spec.split('/'))
    assert 1 <= index <= total, 'POKESIM_TEST_SHARD must look like 2/4'
    modules = {}
    for item in items:
        modules.setdefault(item.nodeid.split('::')[0], []).append(item)
    seconds, per_test = recorded()
    weight = {module: seconds.get(module, per_test * len(tests)) for module, tests in modules.items()}
    loads = [0.0] * total
    owner = {}
    for module in sorted(modules, key=lambda name: (-weight[name], name)):
        lightest = min(range(total), key=lambda shard: (loads[shard], shard))
        owner[module] = lightest + 1
        loads[lightest] += weight[module]
    selected = [item for item in items if owner[item.nodeid.split('::')[0]] == index]
    deselected = [item for item in items if owner[item.nodeid.split('::')[0]] != index]
    assert selected or not items, f'Shard {spec} selected no tests'
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
