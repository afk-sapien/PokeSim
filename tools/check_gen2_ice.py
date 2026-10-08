"""List which warps of every Gen II ice map can be reached from which, using only generated map data.

Run with the generated data directory (the same one GEN2_DATA_DIR names). Two cases are shown for
each map. "bare" has no objects at all, which is the puzzle as the player first meets it. "solved"
has every boulder and person the map data places, in their starting positions. A warp that cannot
be reached from some other warp in the solved case is a gap in the maps, and exits non-zero.
"""
import argparse
import sys
from pathlib import Path

from pokesim.gen2 import ice
from pokesim.gen2.data import GameData

DOOR = range(0x60, 0x80)


def reachable(data, mid, start, solid=frozenset()):
    """Every tile a player can stop on, or enter as a warp, starting from ``start``."""
    entry = data.maps[mid]
    width, height, grid = entry['width'], entry['height'], entry['collision']
    enter = lambda tile: (data.permissions[tile] & 15) == 0
    doors = frozenset((warp['x'], warp['y']) for warp in entry['warps'] if grid[warp['y'] * width + warp['x']] in DOOR)
    solid = frozenset(solid) - doors
    seen, stack = {start}, [start]
    while stack:
        point = stack.pop()
        if point in doors and point != start:
            continue
        for button in ice.DIRS:
            end = ice.move(grid, width, height, point, button, enter, solid, doors)
            if end is not None and end not in seen:
                seen.add(end)
                stack.append(end)
    return seen


def report(data, label):
    gaps = 0
    for mid, entry in sorted(data.maps.items()):
        if not ice.has_ice(entry['collision']):
            continue
        width, grid = entry['width'], entry['collision']
        doors = [(warp['x'], warp['y']) for warp in entry['warps'] if grid[warp['y'] * width + warp['x']] in DOOR]
        objects = {(obj['x'], obj['y']) for obj in entry['objects']}
        print(f"{label} {entry['constant']} ({mid}): {len(doors)} warps, {len(objects)} objects")
        for case, solid in (('bare', frozenset()), ('solved', objects)):
            for door in doors:
                reached = reachable(data, mid, door, solid)
                missing = [other for other in doors if other != door and other not in reached]
                if missing:
                    print(f'  {case}: from {door} cannot reach {missing}')
                    gaps += case == 'solved'
    return gaps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path, help='generated Gen II data directory')
    parser.add_argument('games', nargs='*', default=['gold', 'silver', 'crystal'])
    args = parser.parse_args()
    gaps = sum(report(GameData.load(args.data, game), game) for game in args.games)
    return 1 if gaps else 0


if __name__ == '__main__':
    sys.exit(main())
