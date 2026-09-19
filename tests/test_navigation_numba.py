"""The optional integer BFS preserves Python route ordering and bounded searches."""
from collections import deque
import sys

import pytest

from pokesim.policies import navigation
from pokesim.policies import navigation_numba as compiled


@pytest.fixture(params=['python_kernel', 'numba_kernel'])
def run(request, monkeypatch):
    if request.param == 'python_kernel':
        return compiled._advance
    pytest.importorskip('numba')
    monkeypatch.delenv('POKESIM_NAVIGATION_BACKEND', raising=False)
    result = compiled.kernel()
    assert result is not None
    return result


def reference_route(source, goals, edges, limit):
    queue = deque([source])
    parents = {source: None}
    found = None
    while queue and len(parents) < limit:
        pos = queue.popleft()
        if pos in goals:
            found = pos
            break
        for direction, target in edges.get(pos, ()):
            if target not in parents:
                parents[target] = (pos, direction)
                queue.append(target)
    path = []
    while found is not None and parents[found] is not None:
        parent, direction = parents[found]
        path.append((parent, direction, found))
        found = parent
    return list(reversed(path))


def search(graph, source, goals, edges, caches, limit=60000):
    def neighbors(pos):
        values = tuple(edges.get(pos, ()))
        caches.setdefault(pos[0], {})[pos] = values
        return values
    return list(graph.route(source, frozenset(goals), limit, neighbors, caches))


def test_compiled_paths_preserve_duplicate_edges_cycles_and_limits(run):
    a, b, c, d, unreachable = [(9001, n, 0) for n in range(5)]
    edges = {a: [('right', b), ('right', c), ('down', b)],
        b: [('left', a), ('down', d)], c: [('left', d)], d: [('up', c)]}
    graph = compiled.SearchGraph(run, object(), navigation.DIRS)
    caches = {}
    for limit in (0, 1, 2, 3, 4, 5, 60000):
        for goals in ([], [a], [b], [c], [d], [c, b], [unreachable]):
            expected = reference_route(a, goals, edges, limit)
            assert search(graph, a, goals, edges, caches, limit) == expected
            assert search(graph, a, goals, edges, caches, limit) == expected


def test_node_and_edge_storage_grows_while_kernel_search_is_suspended(run):
    source = (9001, 0, 0)
    leaves = [(9001, n, 0) for n in range(1, 1551)]
    goal = (9002, 0, 0)
    edges = {source: [('right', target) for target in leaves],
        leaves[-1]: [('down', goal)]}
    graph = compiled.SearchGraph(run, object(), navigation.DIRS)
    caches = {}
    expected = reference_route(source, [goal], edges, 60000)
    assert search(graph, source, [goal], edges, caches) == expected
    assert len(graph.counts) >= len(leaves) + 2
    assert graph.targets.shape[1] >= len(leaves)
    assert search(graph, source, [goal], edges, caches) == expected
    assert search(graph, source, [goal], edges, caches, len(leaves)) == []


def test_map_cache_replacement_invalidates_previously_indexed_edges(run):
    a, b, c = (9001, 0, 0), (9002, 0, 0), (9002, 1, 0)
    edges = {a: [('right', b)], b: [('down', c)]}
    graph = compiled.SearchGraph(run, object(), navigation.DIRS)
    caches = {}
    assert search(graph, a, [c], edges, caches) == reference_route(a, [c], edges, 60000)
    edges[b] = [('up', c)]
    caches.pop(9002)
    assert search(graph, a, [c], edges, caches)[-1] == (b, 'up', c)
    edges[a] = []
    caches[9001] = {}
    assert search(graph, a, [c], edges, caches) == []
    edges[a] = [('down', c)]
    caches.pop(9001)
    assert search(graph, a, [c], edges, caches) == [(a, 'down', c)]


def test_navigator_compiled_and_python_routes_match_after_graph_mutations(run, monkeypatch):
    monkeypatch.setattr(compiled, 'kernel', lambda: run)
    nav = navigation.Navigator()
    nav.use_world = False
    a, b, c, d = [(9001, n, 0) for n in range(4)]
    nav.edges = {a: {'right': b, 'down': c}, b: {'right': d}, c: {'up': d}}
    for operation in (
        lambda: None,
        lambda: nav.edges[a].update({'down': d}),
        lambda: nav.blocked.update({(a, 'down'): 100}),
        lambda: nav.story_blocks.add(b),
        lambda: nav.blocked.clear(),
        lambda: nav.story_blocks.clear(),
        lambda: nav.edges[b].clear(),
        lambda: nav.restore(),
    ):
        operation()
        for frame in (0, 101):
            nav.path.clear()
            nav.route(a, [d], frame)
            path = list(nav.path)
            nav.path.clear()
            with monkeypatch.context() as context:
                context.setattr(compiled, 'kernel', lambda: None)
                nav.route(a, [d], frame)
            assert path == list(nav.path)
    assert nav._compiled_graph is not None


def test_python_backend_environment_never_constructs_kernel(monkeypatch):
    monkeypatch.setenv('POKESIM_NAVIGATION_BACKEND', 'python')
    monkeypatch.setattr(compiled, '_kernel', object())
    assert compiled.kernel() is None


def test_unavailable_numba_falls_back_and_remembers_failure(monkeypatch):
    monkeypatch.delenv('POKESIM_NAVIGATION_BACKEND', raising=False)
    monkeypatch.setattr(compiled, '_kernel', None)
    monkeypatch.setattr(compiled, '_unavailable', False)
    monkeypatch.setitem(sys.modules, 'numba', None)
    assert compiled.kernel() is None
    assert compiled._unavailable
    assert compiled.kernel() is None


def test_custom_neighbor_provider_retains_python_expansion(monkeypatch):
    nav = navigation.Navigator()
    a, b = (9001, 0, 0), (9001, 1, 0)
    nav.neighbors = lambda pos, frame: [('right', b)] if pos == a else []
    def forbidden():
        pytest.fail('Custom neighbor provider must bypass compiled graph')
    monkeypatch.setattr(compiled, 'kernel', forbidden)
    assert nav.route(a, [b], 0) == 'right'
    assert list(nav.path) == [(a, 'right', b)]


def test_initial_compilation_failure_falls_back_once(monkeypatch):
    from types import SimpleNamespace
    calls = []
    def compile_failure(*args, **kwargs):
        calls.append(True)
        raise RuntimeError('deliberate compiler failure')
    monkeypatch.delenv('POKESIM_NAVIGATION_BACKEND', raising=False)
    monkeypatch.setattr(compiled, '_kernel', None)
    monkeypatch.setattr(compiled, '_unavailable', False)
    monkeypatch.setitem(sys.modules, 'numba', SimpleNamespace(njit=compile_failure))
    assert compiled.kernel() is None
    assert compiled.kernel() is None
    assert len(calls) == 1


def test_runtime_kernel_failure_retries_python_and_disables_backend(monkeypatch):
    calls = []
    def fail(*args):
        calls.append(True)
        raise RuntimeError('deliberate kernel failure')
    monkeypatch.delenv('POKESIM_NAVIGATION_BACKEND', raising=False)
    monkeypatch.setattr(compiled, '_kernel', fail)
    monkeypatch.setattr(compiled, '_unavailable', False)
    nav = navigation.Navigator()
    nav.use_world = False
    a, b = (9001, 0, 0), (9001, 1, 0)
    nav.edges = {a: {'right': b}}
    assert nav.route(a, [b], 0) == 'right'
    assert list(nav.path) == [(a, 'right', b)]
    nav.path.clear()
    assert nav.route(a, [b], 0) == 'right'
    assert len(calls) == 1
    assert compiled.kernel() is None
