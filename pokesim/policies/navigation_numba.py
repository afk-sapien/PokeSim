"""Optional compiled breadth-first search over lazily indexed navigation edges."""
import logging
import os

import numpy as np

logger = logging.getLogger(__name__)
_kernel = None
_unavailable = False


def disable(error):
    global _kernel, _unavailable
    _unavailable = True
    _kernel = None
    logger.warning('Compiled navigation failed, using Python: %s', error)


def _advance(queue, head, tail, parents, steps, goals, counts, targets, directions, limit):
    while head < tail and tail < limit:
        source = queue[head]
        if goals[source]:
            return source, head, tail, 1
        if counts[source] < 0:
            return source, head, tail, 0
        head += 1
        for edge in range(counts[source]):
            target = targets[source, edge]
            if parents[target] < 0:
                parents[target] = source
                steps[target] = directions[source, edge]
                queue[tail] = target
                tail += 1
    return -1, head, tail, 2


def kernel():
    global _kernel, _unavailable
    if _unavailable or os.environ.get('POKESIM_NAVIGATION_BACKEND') == 'python':
        return None
    if _kernel is None:
        try:
            from numba import njit
            _kernel = njit(cache=True)(_advance)
            # Compile before exposing the backend, so unsupported installs fall back.
            values = np.zeros(1, dtype=np.int64)
            _kernel(values, 0, 0, values, values, np.zeros(1, dtype=np.bool_),
                    values, values.reshape(1, 1), values.reshape(1, 1), 1)
        except Exception as error:
            _unavailable = True
            _kernel = None
            logger.info('Compiled navigation unavailable, using Python: %s', error)
    return _kernel


class SearchGraph:
    """Keep integer edges in exactly the order supplied by the Python navigator."""
    def __init__(self, run, signature, directions):
        self.run = run
        self.signature = signature
        self.direction_names = tuple(directions)
        self.direction_ids = {name: index for index, name in enumerate(directions)}
        self.ids = {}
        self.positions = []
        self.map_nodes = {}
        self.map_caches = {}
        self.counts = np.full(1024, -1, dtype=np.int64)
        self.targets = np.empty((1024, 8), dtype=np.int64)
        self.directions = np.empty((1024, 8), dtype=np.int64)

    def node(self, pos):
        if pos in self.ids:
            return self.ids[pos]
        index = len(self.positions)
        if index == len(self.counts):
            capacity = len(self.counts) * 2
            counts = np.full(capacity, -1, dtype=np.int64)
            counts[:index] = self.counts
            self.counts = counts
            for name in ('targets', 'directions'):
                previous = getattr(self, name)
                grown = np.empty((capacity, previous.shape[1]), dtype=np.int64)
                grown[:index] = previous
                setattr(self, name, grown)
        self.ids[pos] = index
        self.positions.append(pos)
        self.map_nodes.setdefault(pos[0], []).append(index)
        return index

    def sync(self, caches):
        for m, previous in list(self.map_caches.items()):
            if caches.get(m) is not previous:
                self.counts[self.map_nodes[m]] = -1
                self.map_caches.pop(m)

    def fill(self, source, neighbors, caches):
        pos = self.positions[source]
        edges = neighbors(pos)
        values = [(self.direction_ids[direction], self.node(target)) for direction, target in edges]
        if len(values) > self.targets.shape[1]:
            for name in ('targets', 'directions'):
                previous = getattr(self, name)
                grown = np.empty((len(self.counts), len(values)), dtype=np.int64)
                grown[:, :previous.shape[1]] = previous
                setattr(self, name, grown)
        for i, (direction, target) in enumerate(values):
            self.targets[source, i] = target
            self.directions[source, i] = direction
        self.counts[source] = len(values)
        self.map_caches[pos[0]] = caches[pos[0]]

    def route(self, pos, goals, limit, neighbors, caches):
        self.sync(caches)
        source = self.node(pos)
        goal_ids = [self.node(goal) for goal in goals]
        capacity = len(self.counts)
        parents = np.full(capacity, -1, dtype=np.int64)
        steps = np.empty(capacity, dtype=np.int64)
        queue = np.empty(capacity, dtype=np.int64)
        goal_flags = np.zeros(capacity, dtype=np.bool_)
        goal_flags[goal_ids] = True
        queue[0] = source
        parents[source] = source
        head, tail = 0, 1
        while True:
            found, head, tail, status = self.run(queue, head, tail, parents, steps,
                goal_flags, self.counts, self.targets, self.directions, limit)
            if status:
                break
            self.fill(found, neighbors, caches)
            if len(self.counts) != capacity:
                new_capacity = len(self.counts)
                new_parents = np.full(new_capacity, -1, dtype=np.int64)
                new_parents[:capacity] = parents
                parents = new_parents
                new_steps = np.empty(new_capacity, dtype=np.int64)
                new_steps[:capacity] = steps
                steps = new_steps
                new_queue = np.empty(new_capacity, dtype=np.int64)
                new_queue[:tail] = queue[:tail]
                queue = new_queue
                new_flags = np.zeros(new_capacity, dtype=np.bool_)
                new_flags[:capacity] = goal_flags
                goal_flags = new_flags
                capacity = new_capacity
        path = []
        if status == 1:
            while found != source:
                parent = parents[found]
                path.append((self.positions[parent], self.direction_names[steps[found]], self.positions[found]))
                found = parent
        return reversed(path)
