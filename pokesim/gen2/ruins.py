"""Solve the four Ruins of Alph picture boards through controller input."""
from collections import deque

PUZZLES = ('KABUTO', 'AERODACTYL', 'OMANYTE', 'HO_OH')
DESTINATIONS = {piece: (piece - 1) // 4 * 6 + (piece - 1) % 4 + 7 for piece in range(1, 17)}
CELLS = set(range(30)) | {30, 35}


def puzzle_button(board, cursor, held):
    if (len(board) != 36 or cursor not in CELLS
            or sorted([value for value in board if value] + ([held] if held else [])) != list(range(1, 17))):
        return None
    if held:
        target = DESTINATIONS.get(held)
        if target is None:
            return None
        if board[target]:
            target = next((index for index in CELLS if not board[index] and index not in DESTINATIONS.values()), None)
    else:
        wrong = [piece for piece, cell in DESTINATIONS.items() if board[cell] != piece]
        if not wrong:
            return 'a'
        piece = next((piece for piece in wrong if not board[DESTINATIONS[piece]]), wrong[0])
        target = next((index for index, value in enumerate(board) if value == piece), None)
    if target is None:
        return None
    if cursor == target:
        return 'a'
    queue = deque([(cursor, None)])
    seen = {cursor}
    while queue:
        cell, first = queue.popleft()
        for button, delta in (('up', -6), ('down', 6), ('left', -1), ('right', 1)):
            dest = cell + delta
            if cell == 30 and button == 'right':
                dest = 35
            if cell == 35 and button == 'left':
                dest = 30
            if dest not in CELLS or dest in seen:
                continue
            if button in {'left', 'right'} and cell // 6 != dest // 6:
                continue
            action = first or button
            if dest == target:
                return action
            seen.add(dest)
            queue.append((dest, action))
    return None


def control(snapshot, mem):
    if 'RUINS_OF_ALPH_' not in snapshot.data.maps[snapshot.map]['constant']:
        return None
    if mem.byte('wTilemap') != 0xEE:
        return None
    board = list(mem.read('wPuzzlePieces', 36))
    held = mem.byte('wUnownPuzzleHeldPiece') if mem.byte('wHoldingUnownPuzzlePiece') else 0
    if sorted([value for value in board if value] + ([held] if held else [])) != list(range(1, 17)):
        return 'wait'
    return puzzle_button(board, mem.byte('wUnownPuzzleCursorPosition'), held) or 'wait'


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
