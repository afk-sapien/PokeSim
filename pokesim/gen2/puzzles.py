"""Plan Strength pushes using the cartridge's collision grid and boulder positions."""
from collections import deque
from heapq import heappop, heappush
from itertools import count

from .navigation import DIRS, OPPOSITE, blocked_side


def push_plan(grid, width, height, permissions, player, stones, target, hole, *, obstacles=(), limit=12000):
    """Return stand position and direction for each push, without moving game memory."""
    obstacles = set(obstacles)

    def floor(point):
        x, y = point
        return (point not in obstacles and 0 <= x < width and 0 <= y < height
                and permissions[grid[y * width + x]] & 15 == 0)

    def reach(origin, blocks):
        seen = {origin}
        queue = deque([origin])
        while queue:
            x, y = queue.popleft()
            for direction, (dx, dy) in DIRS.items():
                point = (x + dx, y + dy)
                if point in seen or point in blocks or not floor(point):
                    continue
                nx, ny = point
                if (0x60 <= grid[ny * width + nx] <= 0x7F
                        or blocked_side(grid[y * width + x], direction)
                        or blocked_side(grid[ny * width + nx], OPPOSITE[direction])):
                    continue
                seen.add(point)
                queue.append(point)
        return seen

    reachable = {hole}
    reverse = deque([hole])
    while reverse:
        x, y = reverse.popleft()
        for dx, dy in DIRS.values():
            before, stand = (x - dx, y - dy), (x - 2 * dx, y - 2 * dy)
            if before not in reachable and floor(before) and floor(stand):
                reachable.add(before)
                reverse.append(before)
    if stones[target] not in reachable:
        return None
    initial = tuple(stones)
    order = count()
    queue = [(0, next(order), player, initial, [])]
    visited = set()
    while queue and len(visited) < limit:
        _, _, origin, positions, path = heappop(queue)
        accessible = reach(origin, set(positions))
        key = (min(accessible), positions)
        if key in visited:
            continue
        visited.add(key)
        for index, (x, y) in enumerate(positions):
            for direction, (dx, dy) in DIRS.items():
                stand, destination = (x - dx, y - dy), (x + dx, y + dy)
                if stand not in accessible or destination in positions or not floor(destination):
                    continue
                nx, ny = destination
                tile = grid[ny * width + nx]
                if (blocked_side(grid[y * width + x], direction)
                        or blocked_side(tile, OPPOSITE[direction])):
                    continue
                step = (stand, direction)
                if index == target and destination == hole:
                    return path + [step]
                if 0x60 <= tile <= 0x7F or tile in (0x23, 0x2B):
                    continue
                if index == target and destination not in reachable:
                    continue
                moved = list(positions)
                moved[index] = destination
                distance = abs(moved[target][0] - hole[0]) + abs(moved[target][1] - hole[1])
                heappush(queue, (len(path) + 1 + distance * 2, next(order), (x, y), tuple(moved), path + [step]))
    return None
