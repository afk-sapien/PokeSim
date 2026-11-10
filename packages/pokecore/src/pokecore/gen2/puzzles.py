"""Ruins of Alph picture boards: read the board and choose the next button.

The board is the 6 by 6 ``wPuzzlePieces`` grid. Pieces 1 to 16 belong in the
middle 4 by 4 square. The cursor reaches the top five rows and the two bottom
corners (cells 30 and 35), and the cells around the square hold pieces out of place.
``puzzle_button`` never drops a piece on an occupied cell, so no piece is lost.
"""
from collections import deque

from .state import memory_reader

PUZZLES = ('KABUTO', 'AERODACTYL', 'OMANYTE', 'HO_OH')
# Each piece's home cell in the middle 4 by 4 square.
DESTINATIONS = {piece: (piece - 1) // 4 * 6 + (piece - 1) % 4 + 7 for piece in range(1, 17)}
# The cells the cursor can reach.
CELLS = frozenset(set(range(30)) | {30, 35})
# The board's top left border tile, shown only while a board is open.
BOARD_CORNER = 0xEE


def _complete(board, held):
    return sorted([value for value in board if value] + ([held] if held else [])) == list(range(1, 17))


def puzzle_button(board, cursor, held):
    """The next button toward a solved board, or None when the board is not one this solver knows.

    ``board`` is the 36 ``wPuzzlePieces`` bytes, ``cursor`` the cursor cell and ``held``
    the piece in hand (0 for none). ``'a'`` on a solved board with nothing held finishes it.
    """
    if len(board) != 36 or cursor not in CELLS or not _complete(board, held):
        return None
    if held:
        target = DESTINATIONS.get(held)
        if target is None:
            return None
        if board[target]:
            target = next((index for index in sorted(CELLS)
                           if not board[index] and index not in DESTINATIONS.values()), None)
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


def control(memory, version, map_constant=None):
    """The next button while a Ruins of Alph board is open, ``'wait'`` while it is changing, or None.

    None means no board is on screen. ``map_constant`` is the current map's constant name
    when the caller has map tables, and anything outside the Ruins of Alph returns None.
    Without it the open board alone decides.
    """
    if map_constant is not None and 'RUINS_OF_ALPH_' not in map_constant:
        return None
    mem = memory_reader(memory, version)
    if mem.byte('wTilemap') != BOARD_CORNER:
        return None
    board = list(mem.read('wPuzzlePieces', 36))
    held = mem.byte('wUnownPuzzleHeldPiece') if mem.byte('wHoldingUnownPuzzlePiece') else 0
    if not _complete(board, held):
        return 'wait'
    return puzzle_button(board, mem.byte('wUnownPuzzleCursorPosition'), held) or 'wait'
