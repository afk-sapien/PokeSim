"""Ruins of Alph goals. Core solves the four picture boards through controller input."""
from pokecore.gen2 import puzzles
from pokecore.gen2.puzzles import CELLS, DESTINATIONS, PUZZLES, puzzle_button

__all__ = ['CELLS', 'DESTINATIONS', 'PUZZLES', 'control', 'journey', 'puzzle_button']


def control(snapshot, mem):
    """Core's board solver (``pokecore.gen2.puzzles.control``) for the current map."""
    return puzzles.control(mem.memory, snapshot.data.game, snapshot.data.maps[snapshot.map]['constant'])


def journey(policy, snapshot, Goal):
    for name in PUZZLES:
        if not snapshot.event('EVENT_SOLVED_' + name + '_PUZZLE'):
            cave = policy.data.map_ids['UNION_CAVE_B1F']
            if name == 'OMANYTE' and snapshot.map == cave:
                stones = policy.nav.objects.setdefault(cave, {})
                stones.update({index: (x, y) for index, x, y in snapshot.objects})
                index = next(i for i, obj in enumerate(policy.data.maps[cave]['objects'], 1)
                             if obj['sprite'] == 'SPRITE_BOULDER')
                x, y = stones.get(index, (7, 10))
                if x > 3:
                    return Goal('push_alph_passage', 'Clear the western passage in Union Cave',
                                'UNION_CAVE_B1F', x + 1, y, 'left')
            return Goal('alph_' + name.lower(), 'Solve the ' + name.replace('_', '-') + ' picture puzzle',
                        'RUINS_OF_ALPH_' + name + '_CHAMBER', 3, 3, 'up')
    return None
