"""Small Gen II cartridge tables, in-game trade flags, the contest judge and the Ruins boards."""
import random
from collections import defaultdict
from types import SimpleNamespace

import pytest

from pokecore.gen2 import (DESTINATIONS, FIELD_MOVES, NPC_TRADES, PRIZES, memory_map, npc_trades, prizes,
                               puzzle_button, puzzles, state)


class BankedMemory:
    def __init__(self, version):
        self.banks = defaultdict(lambda: bytearray(65536))
        self.symbols = memory_map.symbols(version)

    def __getitem__(self, key):
        bank, address = key if isinstance(key, tuple) else (0, key)
        return self.banks[bank][address]

    def put(self, name, data, offset=0):
        bank, address = self.symbols[name]
        self.banks[bank][address + offset:address + offset + len(data)] = bytes(data)


# pret data/events/npc_trades.asm, in wTradeFlags bit order, as (npc, request, give) species IDs:
# Drowzee for Machop, Bellsprout for Onix, Krabby for Voltorb, Dragonair for Rhydon or Dodrio,
# Gloom for Rapidash, Haunter for Xatu, Chansey for Aerodactyl, Abra for Machop, Dugtrio for Magneton.
PRET = {
    'gold': [('MIKE', 96, 66), ('KYLE', 69, 95), ('TIM', 98, 100), ('EMY', 148, 112), ('CHRIS', 44, 78),
             ('KIM', 113, 142)],
    'crystal': [('MIKE', 63, 66), ('KYLE', 69, 95), ('TIM', 98, 100), ('EMY', 148, 85), ('CHRIS', 93, 178),
                ('KIM', 113, 142), ('FOREST', 51, 82)],
}


@pytest.mark.parametrize('game', ['gold', 'crystal'])
def test_trade_table_matches_pret(game):
    rows = [(trade.npc.upper(), trade.request, trade.give) for trade in npc_trades(game)]
    assert rows == PRET[game]
    assert [trade.index for trade in npc_trades(game)] == list(range(len(rows)))
    assert all(trade.map_name.isupper() for trade in npc_trades(game))
    assert NPC_TRADES['silver'] == NPC_TRADES['gold']
    assert [trade.npc for trade in npc_trades(game) if trade.female] == ['Emy']


def test_prize_tables_differ_by_game():
    # Silver sells Sandshrew where Gold sells Ekans. Crystal has its own six.
    assert [row[0] for row in prizes('gold')] == [63, 27, 147, 122, 133, 137]
    assert [row[0] for row in prizes('silver')] == [63, 23, 147, 122, 133, 137]
    assert prizes('crystal')[-1] == (246, 8888, 'CELADON')
    assert all(len(PRIZES[game]) == 6 for game in ('gold', 'silver', 'crystal'))
    with pytest.raises(KeyError):
        prizes('red')


def test_field_moves_are_the_seven_hms():
    assert FIELD_MOVES == {15, 19, 57, 70, 127, 148, 250}


@pytest.mark.parametrize('version', ['gold', 'crystal'])
def test_trade_flags_report_each_trade_by_bit(version):
    memory = BankedMemory(version)
    assert state.npc_trades_done(memory, version) == ()
    memory.put('wTradeFlags', [0b1010])
    trades = npc_trades(version)
    assert state.npc_trade_flags(memory, version) == 0b1010
    assert state.npc_trade_done(memory, version, trades[1]) and state.npc_trade_done(memory, version, 3)
    assert not state.npc_trade_done(memory, version, trades[0])
    assert [trade.npc for trade in state.npc_trades_done(memory, version)] == ['Kyle', 'Emy']


def test_trade_qualifies_on_species_eggs_and_gender():
    kyle, emy = npc_trades('gold')[1], npc_trades('gold')[3]
    assert state.npc_trade_qualifies({'species': 69, 'egg': False}, kyle)
    assert not state.npc_trade_qualifies({'species': 69, 'egg': True}, kyle)
    assert not state.npc_trade_qualifies({'species': 70}, kyle)
    assert not state.npc_trade_qualifies(SimpleNamespace(species=148, egg=False, gender='Male'), emy)
    assert not state.npc_trade_qualifies({'species': 148}, emy)    # gender unknown
    assert state.npc_trade_qualifies(SimpleNamespace(species=148, egg=False, gender='Female'), emy)


@pytest.mark.parametrize('version', ['silver', 'crystal'])
def test_contest_score_follows_the_judge(version):
    memory = BankedMemory(version)
    assert state.contest_score(memory, version) == 0
    memory.put('wContestMonSpecies', [123])
    memory.put('wContestMonDVs', [0xF2, 0x22])
    memory.put('wContestMonMaxHP', (40).to_bytes(2, 'big'))
    memory.put('wContestMonHP', (33).to_bytes(2, 'big'))
    for stat, value in zip(state.CONTEST_STATS, (30, 25, 35, 20, 21)):
        memory.put('wContestMon' + stat, value.to_bytes(2, 'big'))
    # 160 for max HP, 131 for the stats, 1 + 4 + 8 + 16 for the DVs and 4 for an eighth of HP.
    assert state.contest_score(memory, version) == 160 + 131 + 29 + 4
    memory.put('wContestMonItem', [1])
    assert state.contest_score(memory, version) == 325
    assert state.contest_score(memory, version, 'wEnemyMon') == 0


def _shuffled(seed):
    rng = random.Random(seed)
    board = [0] * 36
    for piece, cell in enumerate(rng.sample(sorted(puzzles.CELLS), 16), 1):
        board[cell] = piece
    return board


def test_ruins_solver_completes_shuffled_boards_without_losing_pieces():
    for seed in range(50):
        board = _shuffled(seed)
        cursor, held = 0, 0
        for _ in range(2000):
            if all(board[cell] == piece for piece, cell in DESTINATIONS.items()):
                break
            button = puzzle_button(board, cursor, held)
            assert button is not None
            if button == 'a':
                board[cursor], held = held, board[cursor]
            elif cursor == 30 and button == 'right':
                cursor = 35
            elif cursor == 35 and button == 'left':
                cursor = 30
            else:
                cursor += {'up': -6, 'down': 6, 'left': -1, 'right': 1}[button]
            assert cursor in puzzles.CELLS
            assert sorted([n for n in board if n] + ([held] if held else [])) == list(range(1, 17))
        assert all(board[cell] == piece for piece, cell in DESTINATIONS.items())
        assert not held


def test_ruins_solver_refuses_boards_it_does_not_know():
    board = _shuffled(1)
    assert puzzle_button(board[:35], 0, 0) is None
    assert puzzle_button(board, 31, 0) is None
    board[board.index(16)] = 0
    assert puzzle_button(board, 0, 0) is None
    assert puzzle_button(board, 0, 16) is not None


@pytest.mark.parametrize('version', ['gold', 'crystal'])
def test_ruins_control_reads_the_open_board(version):
    memory = BankedMemory(version)
    assert puzzles.control(memory, version) is None
    memory.put('wTilemap', [puzzles.BOARD_CORNER])
    assert puzzles.control(memory, version) == 'wait'    # pieces still being drawn
    board = _shuffled(3)
    memory.put('wPuzzlePieces', board)
    memory.put('wUnownPuzzleCursorPosition', [0])
    assert puzzles.control(memory, version) == puzzle_button(board, 0, 0)
    assert puzzles.control(memory, version, 'RUINS_OF_ALPH_KABUTO_CHAMBER') == puzzle_button(board, 0, 0)
    assert puzzles.control(memory, version, 'VIOLET_CITY') is None
    piece = board.index(5)
    board[piece] = 0
    memory.put('wPuzzlePieces', board)
    memory.put('wUnownPuzzleHeldPiece', [5])
    assert puzzles.control(memory, version) == 'wait'    # the held flag is not set yet
    memory.put('wHoldingUnownPuzzlePiece', [1])
    assert puzzles.control(memory, version) == puzzle_button(board, 0, 5)
