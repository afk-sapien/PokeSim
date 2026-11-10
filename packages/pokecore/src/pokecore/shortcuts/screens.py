"""Read-only screen classification for English Red, Blue, Yellow, Gold, Silver and Crystal.

``current_screen`` names the screen from the tilemap and menu WRAM only. It never
writes memory and never guesses a menu from a nickname: party rows must match the
owned party, and menu words are matched against whole visible rows.

Before the game starts, the intro and title screen are ``title`` and the CONTINUE and
NEW GAME menu is ``main_menu``. A soft reset can keep the last game in WRAM, so the
title is told apart by the play time flag only a started game sets: bit 0 of
``wStatusFlags6`` in Gen 1 and of ``wGameTimerPaused`` in Gen 2. Text boxes are read
first, so Oak's speech before a new game is ``dialogue``.

``continue_ready`` recognizes the cartridge's continue-only text wait from live
stack words, the same check PokeBench uses, so callers never press A on a menu.
"""
from __future__ import annotations

import re

from ..gen1 import W_TILEMAP, decode_text, read_party
from ..gen1_ui import _VISIBLE_GLYPHS, read_screen
from ..yellow import red_layout
from .items import generation

SCREENS = ('overworld', 'dialogue', 'transition', 'naming', 'battle_menu', 'move_menu', 'move_list',
           'pause', 'bag', 'item_action', 'party', 'party_action', 'item_target', 'yes_no',
           'switch_prompt', 'quantity', 'mart', 'mart_list', 'pc', 'bills_pc', 'players_pc',
           'pc_items', 'pc_party', 'pc_box', 'pc_mon_action', 'fly_map', 'menu', 'title', 'main_menu', 'unknown',
           'unsupported')
# Bit 0 of wStatusFlags6 counts play time. Init clears it and only a started game sets it.
W_STATUS_FLAGS_6 = 0xD732
# Whole menu rows of the CONTINUE, NEW GAME and OPTION menu shown before the game starts.
MAIN_MENU_WORDS = ({'CONTINUE', 'NEWGAME'}, {'NEWGAME', 'OPTION'})


def pregame_menu(rows):
    """True for the OPTION screen. Title art can hold a cursor tile, so other pre-game menus are the title."""
    return any('TEXT SPEED' in row for row in rows)


# wListPointer values (Red, Yellow) for each ITEMLISTMENU or PCPOKEMONLISTMENU list.
_LISTS = {'bag': (0xD31D, 0xD31C), 'pc_items': (0xD53A, 0xD539), 'pc_party': (0xD163, 0xD162),
          'pc_box': (0xDA80, 0xDA7F)}
_BATTLE_MENU = {(9, 14): 'FIGHT', (15, 14): 'PKMN', (9, 16): 'ITEM', (15, 16): 'RUN'}


def normalize(text):
    return re.sub('[^A-Z0-9]', '', str(text).upper().replace('É', 'E'))


def battle_live(memory, version=None):
    return red_layout(memory, version)[0xD057] in (1, 2)


def _cursor(screen):
    return screen['cursor']


def menu_rows(memory, screen, spacing=2):
    """Visible rows of the active menu as [{'text', 'cursor'}], from wTopMenuItemY/X and wMaxMenuItem."""
    x, y, count = memory[0xCC25], memory[0xCC24], memory[0xCC28] + 1
    if not 1 <= count <= 8 or x > 18 or y > 17:
        return []
    options = []
    for row in range(y, min(y + spacing * count, 18), spacing):
        end = next((col for col in range(x + 1, 20) if screen['tiles'][row * 20 + col] in (0x7C, 0x7A, 0x7B)),
                   20)
        options.append({'text': tile_text(screen['tiles'][row * 20 + x + 1:row * 20 + end]).strip(),
                        'cursor': [x, row]})
    return options


def tile_text(tiles):
    """Decode tiles one by one, so two-letter glyphs like PK MN and contractions stay in place."""
    return ''.join(_CONTRACTIONS.get(tile) or (decode_text(bytes([tile])) if tile != 0x50 else '') or ' '
                   for tile in tiles)


# Contraction tiles ('d 'l 's 't 'v 'r 'm), which the shared screen decoder shows as blanks.
_CONTRACTIONS = {0xBB: "'d", 0xBC: "'l", 0xBD: "'s", 0xBE: "'t", 0xBF: "'v", 0xE4: "'r", 0xE5: "'m"}


def text_lines(memory):
    """Text box rows 12 to 17 joined with spaces, with contractions spelled out.

    Rows are decoded tile by tile, since PK and MN tiles each print two letters.
    A short read returns what it holds.
    """
    raw = bytes(memory[W_TILEMAP + 240:W_TILEMAP + 360])
    out = []
    for start in range(0, len(raw), 20):
        line = ''.join(_CONTRACTIONS.get(tile) or _VISIBLE_GLYPHS[tile] for tile in raw[start:start + 20])
        if line.strip():
            out.append(' '.join(line.split()))
    return ' '.join(out)


def text_rows(memory):
    """The lines inside the framed bottom text box (rows 13 to 16), or [] when no box is framed there.

    Blank lines are left out and contractions are spelled out. ``memory`` is Red layout.
    """
    raw = bytes(memory[W_TILEMAP:W_TILEMAP + 360])
    if raw[12 * 20] != 0x79:
        return []
    lines = (' '.join(tile_text(raw[row * 20 + 1:row * 20 + 19]).split()) for row in range(13, 17))
    return [line for line in lines if line]


def screen_words(memory):
    """All visible tilemap text normalized to capital letters and digits, for marker checks."""
    return normalize(' '.join(read_screen(memory)['rows']))


def party_screen(memory, screen, version=None):
    """True when the party list is on screen with its cursor and the names match the owned party."""
    cursor = screen['cursor']
    if not cursor or cursor[0] != 0 or memory[0xCC24] != 1 or memory[0xCC25] != 0:
        return False
    party = read_party(memory, version=version)
    if not party or memory[0xCC28] + 1 != len(party):
        return False
    return all(screen['rows'][2 * i][3:13].strip() == mon['nick'] for i, mon in enumerate(party))


def _list_kind(memory, screen):
    list_id = memory[0xCF94]
    pointer = memory[0xCF8B] | memory[0xCF8C] << 8
    if list_id == 2:
        return 'mart_list'
    for kind, pointers in _LISTS.items():
        if pointer in pointers:
            return kind
    return None


def _quantity(screen):
    """A quantity box: a framed "×NN" with the frame's top-left corner up and to the left of the ×."""
    rows, tiles = screen['rows'], screen['tiles']
    for y in range(1, 18):
        for x in range(1, 18):
            if rows[y][x] == '×' and rows[y][x + 1:x + 3].isdigit() and tiles[(y - 1) * 20 + x - 1] == 0x79:
                return True
    return False


# Prompts that stay printed while a quantity box waits for input.
_QUANTITY_PROMPTS = ('TAKEYOURTIME', 'WHATWOULDYOU', 'HOWMANY')


def _fly_map(screen):
    """The FLY town map: "To <town>" on the top row with the up and down arrows at its right end."""
    return screen['rows'][0].startswith('To ') and list(screen['tiles'][18:20]) == [0xED, 0xEE]


def fly_destination(screen):
    """The town name the FLY map points at."""
    return tile_text(screen['tiles'][3:18]).strip()


def current_screen(memory, ui=None, *, version=None):
    """Name the visible screen. See ``SCREENS``. Gen 2 screens come from ``gen2ui.classify``."""
    if generation(version) != 1:
        from . import gen2ui
        return gen2ui.classify(gen2ui.View(memory, version))[0]
    memory = red_layout(memory, version)
    if not memory[0xFF40] & 128 or memory[0xFF47] in (0, 85, 170, 255):
        return 'transition'
    screen = read_screen(memory)
    rows, cursor = screen['rows'], screen['cursor']
    battle = memory[0xD057] in (1, 2)
    text = normalize(' '.join(rows[12:18]))
    if 'HT' in rows[6] and 'WT' in rows[8] and rows[2].strip():
        return 'dialogue'
    if any(row[2:19:2] in ('ABCDEFGHI', 'abcdefghi') for row in rows):
        return 'naming'
    if _fly_map(screen):
        return 'fly_map'
    if cursor:
        if 'FIGHT' in rows[14] and 'RUN' in rows[16] and tuple(cursor) in _BATTLE_MENU:
            return 'battle_menu'
        if party_screen(memory, screen, version):
            if 'USEITEMON' in text or 'USETMON' in text or 'USEHMON' in text:
                return 'item_target'
            if 'BRINGOUT' in text or 'CHANGEPOK' in text and not battle:
                return 'party'
            return 'party'
        if memory[0xCC24] == 4 and memory[0xCC25] == 5 and cursor[0] == 5:
            kind = _list_kind(memory, screen)
            if kind:
                return kind
        if cursor[0] == 5 and battle and memory[0xCC24] == 12 and 13 <= cursor[1] <= 16:
            return 'move_menu'
        if cursor[0] == 5 and memory[0xCC24] in (7, 8) and memory[0xCC28] <= 5:
            return 'move_list'
        choices = {normalize(option['text']) for option in menu_rows(memory, screen)}
        if not battle and any(words <= choices for words in MAIN_MENU_WORDS):
            return 'main_menu'
        if {'USE', 'TOSS'} <= choices:
            return 'item_action'
        if {'STATS', 'SWITCH', 'CANCEL'} <= choices:
            return 'party_action'
        if {'STATS', 'CANCEL'} <= choices and choices & {'DEPOSIT', 'WITHDRAW'}:
            return 'pc_mon_action'
        if {'ITEM', 'EXIT'} <= choices:
            return 'pause'
        if {'BUY', 'SELL', 'QUIT'} <= choices:
            return 'mart'
        if any(choice.startswith('WITHDRAWPKMN') or choice.startswith('WITHDRAWPOKMON') for choice in choices):
            return 'bills_pc'
        if 'WITHDRAWITEM' in choices:
            return 'players_pc'
        if 'LOGOFF' in choices:
            return 'pc'
        if {'YES', 'NO'} <= choices:
            return 'switch_prompt' if battle and 'CHANGEPOK' in text else 'yes_no'
        if battle and cursor[0] == 5 and 13 <= cursor[1] <= 16:
            return 'move_menu'
        if not battle and not memory[W_STATUS_FLAGS_6] & 1 and not pregame_menu(rows):
            return 'title'
        return 'menu'
    if _quantity(screen) and (not rows[14][1:10].strip() or normalize(rows[14]) in _QUANTITY_PROMPTS):
        return 'quantity'
    if screen['textbox'] or battle:
        return 'dialogue'
    if not memory[W_STATUS_FLAGS_6] & 1:
        return 'title'
    if screen['pause']:
        return 'transition'
    if memory[0xC102] == 255:
        return 'unknown'
    return 'overworld'


# The text-wait routine. Its calls return to the empty groups, and the link cable
# branch (one call on Red and Blue, a far call between pushes on Yellow) to ``link``.
_TEXT_WAIT = (rb'\xf0(.)\xf5\xf0(.)\xf5\xaf\xe0\1\x3e\x06\xe0\2'
              rb'\xe5\xfa..\xa7\x28(?P<skip>.)(?P<link>.{3,16}?)\x21..\xcd..(?P<arrow>)\xe1\xcd..(?P<joypad>)'
              rb'\x3e\x2d\xcd..(?P<delay>)\xf0.\xe6\x03\x28.\xf1\xe0\2\xf1\xe0\1\xc9')
_POKEDEX_WAIT = rb'\xcd..\xf0.\xe6\x03\x28\xf7\xf1\xe0.\xcd..\xcd..\xcd..\xcd..\xcd..'
_WAIT_CACHE = {}


def _wait_returns(memory):
    try:
        header = bytes(memory[0x134:0x150])
    except (TypeError, IndexError, ValueError):
        header = None
    cached = _WAIT_CACHE.get(header) if header is not None else None
    if cached is not None:
        return cached
    matches = [m for m in re.finditer(_TEXT_WAIT, bytes(memory[0:0x4000]), re.DOTALL)
               if m.group('skip')[0] == len(m.group('link'))]
    text = set()
    if len(matches) == 1:
        found = matches[0]
        text = {found.start(name) for name in ('arrow', 'joypad', 'delay')}
        link = found.group('link')
        text |= {found.start('link') + i + 3 for i in range(len(link) - 2) if link[i] == 0xCD}
    pokedex = set()
    for bank in (16, 15, 17, 18):
        try:
            data = bytes(memory[bank, 0x4000:0x7FFF])
        except (TypeError, IndexError, KeyError, ValueError):
            break
        found = list(re.finditer(_POKEDEX_WAIT, data, re.DOTALL))
        if len(found) == 1:
            pokedex = {0x4000 + found[0].start() + 3}
            break
    result = (frozenset(text), frozenset(pokedex))
    if header is not None:
        _WAIT_CACHE[header] = result
    return result


def continue_ready(memory, sp):
    """True when the game waits for A or B only to continue printed text.

    ``sp`` is the CPU stack pointer (``emulator.register_file.SP``). Only live stack
    words are inspected. Returns None when the routine is not found, so shortcuts
    fall back to text that stopped changing. Yellow's Red-layout memory is read
    through to the raw stack, since its shifted WRAM would misalign the words.
    """
    if not 0xC000 <= sp < 0xE000:
        return False
    memory = getattr(memory, 'raw', memory)
    text, pokedex = _wait_returns(memory)
    if not text:
        return None
    live = {memory[p] + 256 * memory[p + 1] for p in range(sp, min(sp + 80, 0xDFFF), 2)}
    return bool(live & text or live & pokedex)

