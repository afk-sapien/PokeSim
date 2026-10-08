"""Ice sliding for Gen II maps, shared by the step planner and the region graph.

Stepping onto an ice tile commits the player to that direction until the next tile is
blocked or is not ice. Boulders, people and warp tiles end or block a slide, so which
tiles can be reached depends on where those are.
"""
ICE = frozenset((0x23, 0x2B))
WALLS = ({'right'}, {'left'}, {'up'}, {'down'}, {'down', 'right'}, {'down', 'left'},
         {'up', 'right'}, {'up', 'left'})
DIRS = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}
OPPOSITE = {'up': 'down', 'down': 'up', 'left': 'right', 'right': 'left'}


def has_ice(grid):
    return not ICE.isdisjoint(grid)


def side_blocked(tile, direction):
    return tile & 0xF0 in (0xB0, 0xC0) and direction in WALLS[tile & 7]


def slide(grid, width, height, point, button, enter, solid=frozenset(), stop=frozenset()):
    """Where a player who just stepped onto ``point`` while moving ``button`` comes to rest.

    ``enter`` says whether a tile can be walked on. ``solid`` holds tiles occupied by objects.
    A tile in ``stop`` ends the slide as soon as it is entered, as warps and goals do.
    """
    dx, dy = DIRS[button]
    x, y = point
    while grid[y * width + x] in ICE and (x, y) not in stop:
        nx, ny = x + dx, y + dy
        if (not 0 <= nx < width or not 0 <= ny < height or (nx, ny) in solid
                or side_blocked(grid[y * width + x], button)
                or side_blocked(grid[ny * width + nx], OPPOSITE[button])
                or not enter(grid[ny * width + nx])):
            break
        x, y = nx, ny
    return x, y


def move(grid, width, height, point, button, enter, solid=frozenset(), stop=frozenset()):
    """Where one step from ``point`` ends, or None when the first tile cannot be entered."""
    dx, dy = DIRS[button]
    x, y = point
    nx, ny = x + dx, y + dy
    if (not 0 <= nx < width or not 0 <= ny < height or (nx, ny) in solid
            or side_blocked(grid[y * width + x], button)
            or side_blocked(grid[ny * width + nx], OPPOSITE[button])
            or not enter(grid[ny * width + nx])):
        return None
    return slide(grid, width, height, (nx, ny), button, enter, solid, stop)
