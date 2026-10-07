"""Optional test sharding so CI can run one suite as several parallel jobs.

Set POKESIM_TEST_SHARD to "index/total" (for example "2/4"). Whole test modules are assigned to shards by
weight, so tests that share module state stay together. Without the variable every test runs. The shards
together always cover exactly the full suite, and a shard that selects nothing is an error.
"""
import os


def pytest_collection_modifyitems(config, items):
    spec = os.environ.get('POKESIM_TEST_SHARD')
    if not spec:
        return
    index, total = (int(part) for part in spec.split('/'))
    assert 1 <= index <= total, 'POKESIM_TEST_SHARD must look like 2/4'
    modules = {}
    for item in items:
        modules.setdefault(item.nodeid.split('::')[0], []).append(item)
    loads = [0] * total
    owner = {}
    for module in sorted(modules, key=lambda name: (-len(modules[name]), name)):
        lightest = min(range(total), key=lambda shard: (loads[shard], shard))
        owner[module] = lightest + 1
        loads[lightest] += len(modules[module])
    selected = [item for item in items if owner[item.nodeid.split('::')[0]] == index]
    deselected = [item for item in items if owner[item.nodeid.split('::')[0]] != index]
    assert selected or not items, f'Shard {spec} selected no tests'
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
