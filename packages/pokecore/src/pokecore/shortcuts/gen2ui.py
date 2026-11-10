"""Read-only screen reading for Gold, Silver and Crystal.

The classifier reads the 20x18 tilemap and a few menu bytes through Core's Gen 2
memory map, always through an explicit WRAM bank. Map tiles in the overworld
decode as random letters, so text is only trusted inside menu frames, the text
box, or at the fixed places each menu draws it.
"""
from __future__ import annotations

from functools import lru_cache
import re

from ..gen2.charmap import charmap
from ..gen2.memory_map import symbols as core_symbols
from ..gen2.ram import Memory
from ..gen2.tables import GameTables
from ..textmatch import has_word
from .screens import MAIN_MENU_WORDS, normalize, pregame_menu

# Menu and battle symbols the shortcuts read, as (Gold and Silver, Crystal) addresses from the pret
# symbol files. Bank 1 holds 0xD000 to 0xDFFF, everything else is bank 0.
UI_SYMBOLS = {
    'wMenuScrollPosition': (0xCFD4, 0xD0E4),
    'w2DMenuNumRows': (0xCEDA, 0xCFA3),
    'w2DMenuNumCols': (0xCEDB, 0xCFA4),
    'wMenuBorderTopCoord': (0xCEB9, 0xCF82),
    'wMenuBorderLeftCoord': (0xCEBA, 0xCF83),
    'wWindowStackSize': (0xCEAF, 0xCF78),
    'wCurItem': (0xD002, 0xD106),
    'wTMHMPocketScrollPosition': (0xCFD2, 0xD0E2),
    'wCurMartCount': (0xCFEC, 0xD0F0),
    'wCurMartItems': (0xCFED, 0xD0F1),
    'wCurPlayerMove': (0xCBC1, 0xC6E3),
    'wBattleMonMoves': (0xCB0E, 0xC62E),
    'wBattleMonPP': (0xCB14, 0xC634),
    'wBattleMonHP': (0xCB1C, 0xC63C),
    'wPartyMenuActionText': (0xD03E, 0xD141),
    'wBillsPC_NumMonsInBox': (0xCA2C, 0xCB2C),
    'wBillsPC_LoadedBox': (0xCA2E, 0xCB2E),
    'wBattleResult': (0xCFE9, 0xD0EE),
    'wPCItems': (0xD617, 0xD8F2),
    'wPlayerSubStatus5': (0xCB4A, 0xC66C),
    'wCurMoveNum': (0xCFC7, 0xD0D5),
    # Bit 0 counts play time. Reset clears it and only a started game sets it.
    'wGameTimerPaused': (0xD8B8, 0xCFBC),
}
LCDC = 0xFF40
# hMapAnims is 1 while the overworld animates. The intro, title and main menu never set it.
H_MAP_ANIMS = {'gold': 0xFFE0, 'silver': 0xFFE0, 'crystal': 0xFFDE}
# Tiles.
BOX_TL, BOX_H, BOX_TR, BOX_V, BOX_BL, BOX_BR = 0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E
CURSOR, IDLE_CURSOR, MORE = 0xED, 0xEC, 0xEE
TIMES = 0xF1
DIGITS = range(0xF6, 0x100)
# Battle menu cursor tiles and their labels.
BATTLE_MENU = {(9, 14): 'FIGHT', (15, 14): 'PKMN', (9, 16): 'PACK', (15, 16): 'RUN'}
_EXPAND = {'<PK>': 'PK', '<MN>': 'MN', '<PO>': 'PO', '<KE>': 'Ké', '<DOT>': '.', '<PKMN>': 'PKMN', '#': 'POKé',
           '<PC>': 'PC', '<TM>': 'TM', '<TRAINER>': 'TRAINER', '<ROCKET>': 'ROCKET'}


@lru_cache(maxsize=3)
def tables(version):
    merged = dict(core_symbols(version))
    column = 1 if version == 'crystal' else 0
    for name, addresses in UI_SYMBOLS.items():
        address = addresses[column]
        merged[name] = (1 if 0xD000 <= address < 0xE000 else 0, address)
    return GameTables({'game': version, 'symbols': merged})


@lru_cache(maxsize=3)
def _glyphs(version):
    single, wide = {}, {}
    for tile, value in charmap(version).items():
        wide[tile] = _EXPAND.get(value, value if not value.startswith('<') else ' ')
        single[tile] = value if len(value) == 1 else ' '
    return single, wide


class View:
    """Banked, read-only access to one Gen 2 game's memory by symbol name."""

    def __init__(self, memory, version):
        self.raw = memory
        self.version = version
        self.mem = Memory(memory, tables(version))
        self._tiles = None

    def byte(self, name, offset=0):
        return self.mem.byte(name, offset)

    def read(self, name, size=1, offset=0):
        return self.mem.read(name, size, offset)

    @property
    def tiles(self):
        if self._tiles is None:
            self._tiles = self.mem.read('wTilemap', 360)
        return self._tiles

    def tile(self, x, y):
        return self.tiles[y * 20 + x]

    def lcd_on(self):
        try:
            return bool(self.raw[LCDC] & 0x80)
        except (TypeError, IndexError, KeyError, ValueError):
            return True

    def pre_game(self):
        """True on the intro, title and main menu: play time is not counting and the map is not animating."""
        return not self.byte('wGameTimerPaused') & 1 and not self.raw[H_MAP_ANIMS[self.version]]


def rows_of(view):
    """The tilemap as 18 strings of 20 characters, multi-letter tiles shown as spaces."""
    single = _glyphs(view.version)[0]
    tiles = view.tiles
    return [''.join(single.get(tile, ' ') for tile in tiles[row * 20:row * 20 + 20]) for row in range(18)]


def tile_text(view, x0, x1, y):
    """Text of tiles x0..x1-1 on row y, with PK MN, POKé and contractions spelled out."""
    wide = _glyphs(view.version)[1]
    return ''.join(wide.get(view.tile(x, y), ' ') for x in range(x0, x1))


def text_box(view):
    """The bottom text box joined with spaces, or '' when no text box is framed there.

    The standard box spans rows 12 to 17. The party prompt box starts at row 14 and
    Bill's PC prints in a one-line box on rows 15 to 17. The mart money box or a
    YES/NO box can overlap a corner, so rows without both side bars are skipped.
    """
    return ' '.join(text_box_lines(view))


def text_box_lines(view):
    """The non-blank lines of the bottom text box, as ``text_box`` finds it, or [] with no box."""
    if view.tile(0, 17) != BOX_BL:
        return []
    top = next((y for y in (12, 14, 15) if view.tile(0, y) in (BOX_TL, BOX_V)
                and view.tile(19, y) in (BOX_TR, BOX_BR)), None)
    if top is None:
        return []
    rows = [y for y in range(top + 1, 17) if view.tile(0, y) == BOX_V and view.tile(19, y) == BOX_V]
    lines = [' '.join(tile_text(view, 1, 19, y).split()) for y in rows]
    return [line for line in lines if line]


def cursors(view, tile=CURSOR):
    tiles = view.tiles
    return [(index % 20, index // 20) for index, value in enumerate(tiles) if value == tile]


def box_around(view, x, y):
    """The menu frame around (x, y) as (left, top, right, bottom), or None when unframed."""
    left = next((col for col in range(x - 1, -1, -1) if view.tile(col, y) == BOX_V), None)
    if left is None:
        return None
    top = next((row for row in range(y - 1, -1, -1) if view.tile(left, row) == BOX_TL), None)
    bottom = next((row for row in range(y + 1, 18) if view.tile(left, row) == BOX_BL), None)
    if top is None or bottom is None:
        return None
    right = next((col for col in range(left + 1, 20) if view.tile(col, top) == BOX_TR), None)
    if right is None or right <= x:
        return None
    return left, top, right, bottom


def choices(view, cursor):
    """Visible menu labels in the cursor's column as [(label, (x, y))]."""
    if cursor is None:
        return []
    x, y = cursor
    box = box_around(view, x, y)
    if box is None:
        return []
    left, top, right, bottom = box
    out = []
    for row in range(top + 1, bottom):
        if view.tile(x, row) not in (CURSOR, IDLE_CURSOR, 0x7F):
            continue
        label = ' '.join(tile_text(view, x + 1, right, row).split())
        if label:
            out.append((label, (x, row)))
    return out


def party_names(view):
    from ..gen2.state import read_party_structs
    try:
        return [('EGG' if mon['egg'] else mon['nickname']) for mon in read_party_structs(view.raw, view.version)]
    except (TypeError, IndexError, KeyError, ValueError):
        return []


def roster(view, rows):
    """True when the party list shows every owned party member at its row."""
    names = party_names(view)
    if not names or rows[0].strip():
        return False
    return all(rows[2 * index + 1][3:13].strip() == name.strip() for index, name in enumerate(names))


def quantity_box(view):
    """A framed "×NN" amount box."""
    for y in range(1, 17):
        for x in range(1, 17):
            if (view.tile(x, y) == TIMES and view.tile(x + 1, y) in DIGITS and view.tile(x + 2, y) in DIGITS
                    and view.tile(x - 1, y) == BOX_V and view.tile(x - 1, y - 1) == BOX_TL):
                return True
    return False


def bills_list(view, rows):
    """Bill's PC deposit, withdraw and release lists: the box name box at the top, no tile cursor."""
    return view.tile(8, 0) == BOX_TL and view.tile(8, 1) == BOX_V and view.tile(8, 2) == BOX_BL and bool(
        rows[1][9:19].strip())


def classify(view, rows=None):
    """(screen, extra) for the visible Gen 2 screen. ``extra`` holds cursor, choices and pocket."""
    rows = rows if rows is not None else rows_of(view)
    battle = view.byte('wBattleMode') != 0
    found = cursors(view)
    cursor = found[0] if len(found) == 1 else None
    menu = choices(view, cursor)
    if len(found) > 1:
        # A YES/NO box drawn over a menu leaves the menu's cursor on screen too.
        for spot in found:
            labels = choices(view, spot)
            if {normalize(label) for label, _ in labels} == {'YES', 'NO'}:
                cursor, menu = spot, labels
    extra = {'cursor': cursor, 'choices': menu, 'battle': battle}
    if not view.lcd_on():
        return 'transition', extra
    text = normalize(text_box(view))
    words = {normalize(label) for label, _ in menu}
    if rows[0][2:8] == 'Where?':
        return 'fly_map', extra
    if any(row[2:19:2] in ('ABCDEFGHI', 'abcdefghi') for row in rows):
        return 'naming', extra
    if cursor:
        x, y = cursor
        if battle and cursor in BATTLE_MENU and 'FIGHT' in rows[14] and 'RUN' in rows[16]:
            return 'battle_menu', extra
        if not battle and any(main <= words for main in MAIN_MENU_WORDS):
            return 'main_menu', extra
        if x == 0 and y % 2 and roster(view, rows):
            if 'USEONWHICH' in text or 'TEACHWHICH' in text or 'GIVETOWHICH' in text or 'TOWHICH' in text:
                return 'item_target', extra
            return 'party', extra
        if x == 7 and y in (2, 4, 6, 8, 10) and not menu:
            extra['pocket'] = view.byte('wCurPocket')
            return 'bag', extra
        # The info box shows TYPE/, or "Disabled!" while the cursor is on a disabled move.
        info = rows[8:13]
        if battle and x == 5 and 13 <= y <= 16 and any('TYPE/' in row or 'Disabled!' in row for row in info):
            return 'move_menu', extra
        if x == 6 and view.tile(5, 2) == BOX_TL and 4 <= y <= 10 and len(menu) <= 4:
            return 'move_list', extra
        if {'BUY', 'SELL', 'QUIT'} <= words:
            return 'mart', extra
        if 'QUIT' in words and words & {'USE', 'GIVE', 'TOSS', 'SEL'}:
            return 'item_action', extra
        if {'STATS', 'SWITCH'} <= words:
            # With four field moves the party submenu scrolls and CANCEL is off screen.
            return 'party_action', extra
        if {'STATS', 'RELEASE', 'CANCEL'} <= words and words & {'DEPOSIT', 'WITHDRAW'}:
            return 'pc_mon_action', extra
        if {'PACK', 'EXIT'} <= words:
            return 'pause', extra
        if 'CHANGEBOX' in words and 'SEEYA' in words:
            return 'bills_pc', extra
        if 'WITHDRAWITEM' in words and 'LOGOFF' in words:
            return 'players_pc', extra
        if 'TURNOFF' in words or 'HALLOFFAME' in words:
            return 'pc', extra
        if {'YES', 'NO'} <= words:
            prompt = 'CHANGEPOK' in text or 'USENEXT' in text
            return ('switch_prompt' if battle and prompt else 'yes_no'), extra
        if x == 1 and 4 <= y <= 10 and '¥' in ''.join(rows[0:3]):
            return 'mart_list', extra
        if x == 4 and y in (2, 4, 6, 8) and view.tile(0, 0) == BOX_TL and view.tile(0, 11) == BOX_BL:
            return 'pc_items', extra
        if not battle and view.pre_game() and not pregame_menu(rows):
            return 'title', extra
        return 'menu', extra
    if bills_list(view, rows):
        loaded = view.byte('wBillsPC_LoadedBox')
        return ('pc_party' if loaded == 0 else 'pc_box'), extra
    if quantity_box(view):
        return 'quantity', extra
    if text or battle:
        return 'dialogue', extra
    if view.pre_game():
        return 'title', extra
    if roster(view, rows):
        return 'party', extra
    if view.byte('wWindowStackSize') == 0:
        return 'overworld', extra
    return 'unknown', extra


POCKETS = ('items', 'balls', 'key', 'tms_hms')


def read_party(memory, version):
    """Party members as dicts with the Gen 1 reader's keys (nick, hp, max_hp) added."""
    from ..gen2.state import read_party_structs
    return [{**mon, 'nick': 'EGG' if mon['egg'] else mon['nickname'], 'max_hp': (mon.get('stats') or (0,))[0]}
            for mon in read_party_structs(memory, version)]


def read_pockets(memory, version):
    """Pack pockets and the item PC as lists of (item ID, quantity), in on-screen order."""
    from ..gen2.state import read_items
    from .items import gen2_tm_item
    items = read_items(memory, version)
    pockets = {name: list(items[name]) for name in ('items', 'balls', 'key', 'pc')}
    pockets['tms_hms'] = [(gen2_tm_item(index), qty) for index, qty in enumerate(items['tms_hms']) if qty]
    return pockets


def read_bag(memory, version):
    """Every pack entry as (item ID, quantity), pocket after pocket."""
    pockets = read_pockets(memory, version)
    return [entry for name in POCKETS for entry in pockets[name]]


def box_count(memory, version):
    """Pokemon in the active PC box."""
    from ..gen2.state import read_box_counts
    counts, active = read_box_counts(memory, version)
    return counts[active]


def box_mons(memory, version):
    """Pokemon in the active PC box as decoded structs."""
    from ..gen2.state import read_box_structs
    return read_box_structs(memory, version)


def holds_mail(mon):
    """True when the Pokemon holds a mail item."""
    from .items import item_kind
    return bool(mon.get('held_item')) and item_kind(mon['held_item'], 'crystal').kind == 'mail'


def list_index(view, screen):
    """The highlighted entry of a list screen (0 based, scroll included), or None."""
    cursor = view.byte('wMenuCursorY')
    if screen == 'bag':
        if view.byte('wCurPocket') == 3:
            return view.byte('wTMHMPocketScrollPosition') + cursor - 1
        return view.byte('wMenuScrollPosition') + cursor - 1
    if screen in ('mart_list', 'pc_items'):
        return view.byte('wMenuScrollPosition') + cursor - 1
    if screen in ('pc_party', 'pc_box'):
        return view.byte('wBillsPC_CursorPosition') + view.byte('wBillsPC_ScrollPosition')
    return cursor - 1


def ready(view):
    """True when the ▼ prompt shows at the text box corner, else None (the ▼ blinks)."""
    return True if view.tile(18, 17) == MORE else None


# _ContText: ld a, [wLinkMode] / or a / jr nz / ... / push de / call PromptButton / pop de / ld a, [wLinkMode] / or a.
_CONT_WAIT = rb'\xb7\x20\x03\xcd..\xcd..\xd5\xcd..\xd1\xfa..\xb7'
_CONT_CACHE = {}


def cont_wait(memory, sp):
    """True while text waits for A or B at a ▼ that the text engine prints.

    ``memory`` is raw emulator memory and ``sp`` the CPU stack pointer. Box nicknames
    print without CorrectNickErrors, so a traded <CONT> (0x55), <PARA> (0x51) or
    <PROMPT> (0x58) stops the Bill's PC list mid-draw. PromptButton is found from
    _ContText, and every home bank call to it is a continue-only text wait. Only live
    stack words are read. False when the routine is not found.
    """
    if not 0xC000 <= sp < 0xE000:
        return False
    header = bytes(memory[0x134:0x150])
    if header not in _CONT_CACHE:
        home = bytes(memory[0:0x4000])
        found = list(re.finditer(_CONT_WAIT, home, re.DOTALL))
        returns = frozenset()
        if len(found) == 1:
            call = found[0].group()[10:13]
            returns = frozenset(match.end() for match in re.finditer(re.escape(call), home))
        _CONT_CACHE[header] = returns
    returns = _CONT_CACHE[header]
    return any(memory[p] + 256 * memory[p + 1] in returns for p in range(sp, min(sp + 80, 0xDFFF), 2))


def fly_destination(view):
    return ' '.join(tile_text(view, 2, 18, 1).split())


def menu_label(row):
    """The label of one menu row (a ``rows_of`` string): frame bars, a leading kana
    column, the pack image beside TM and HM rows, item numbers and cursors removed."""
    if row.count('│') >= 2:
        row = row.rsplit('│', 2)[-2]
    if any('\u3040' <= char <= '\u30ff' for char in row[:5]):
        row = row[5:]
    # The pack image occupies columns 0 through 4 beside TM and HM rows.
    if re.match(r'(?:H\d|\d{2})[\s▶▷]', row[5:]):
        row = row[5:]
    return re.sub(r'^[\s│▷▶]*(?:H?\d+[\s▷▶]*)?', '', row).strip(' │')


def choose(rows, label, *, exact=False):
    """One button toward ``label`` in a vertical menu: 'a' on it, 'down' or 'up' toward it.

    ``rows`` are ``rows_of`` strings. ``label`` matches a whole word, ignoring case, or the
    whole row label when ``exact``. None when the label or the ▶ cursor is not on screen.
    """
    wanted = label.casefold()
    target = next((i for i, row in enumerate(rows)
                   if (menu_label(row).casefold() == wanted if exact else has_word(row.casefold(), wanted))), None)
    cursor = next((i for i, row in enumerate(rows) if '▶' in row), None)
    if target is None or cursor is None:
        return None
    return 'a' if target == cursor else 'down' if target > cursor else 'up'


def close_pc(rows, text):
    """The button that leaves a Pokémon Center PC whose list (BILL's PC ... TURN OFF) is on screen.

    ``text`` is the screen text. The list stays drawn under messages such as "BILL's PC
    accessed." and those hold the cursor until they are dismissed. Moving toward TURN OFF
    works only while the list asks "Access whose PC?". Otherwise B dismisses the message.
    """
    if 'whose PC' in text:
        return choose(rows, 'TURN OFF') or 'b'
    return 'b'
