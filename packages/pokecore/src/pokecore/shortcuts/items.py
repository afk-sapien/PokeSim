"""Item kinds and where each item can be used, by item ID.

The tables hold item IDs and mechanical facts only, as ``RESTORATIVE_ITEMS`` does.
Names are never shipped. ``item_names`` and ``move_names`` decode them from the
cartridge in memory, and callers may pass their own labels instead.

Gen 1 IDs follow pret pokered. Gen 2 IDs follow pret pokecrystal and pokegold,
which share one item list, and Berries count as heal or status items.

Kinds: heal, status, revive, pp, ball, repel, escape, evolution, tm, hm, key,
fishing, battle-stat, vitamin, rare-candy, held (Gen 2 hold items), mail and other. ``target`` is what the item
asks for after USE: ``party`` (a party slot), ``move`` (a party slot, then a
move), or ``none``.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..gen1 import decode_text


@dataclass(frozen=True)
class ItemKind:
    kind: str
    field: bool
    battle: bool
    target: str = 'none'
    wild_only: bool = False
    note: str = ''

    def as_dict(self):
        return {'kind': self.kind, 'field': self.field, 'battle': self.battle, 'target': self.target,
                'wild_only': self.wild_only, 'note': self.note}


def _table(*groups):
    table = {}
    for ids, kind in groups:
        for item in ids:
            table[item] = kind
    return table


_PARTY_BOTH = dict(field=True, battle=True, target='party')

GEN1_KINDS = _table(
    ((0x01, 0x02, 0x03, 0x04), ItemKind('ball', False, True, wild_only=True)),
    ((0x08,), ItemKind('ball', False, False, note='Safari Zone battles are not supported')),
    ((0x0A, 0x20, 0x21, 0x22, 0x2F), ItemKind('evolution', True, False, 'party')),
    ((0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x34), ItemKind('status', **_PARTY_BOTH)),
    ((0x10, 0x11, 0x12, 0x13, 0x14, 0x3C, 0x3D, 0x3E), ItemKind('heal', **_PARTY_BOTH)),
    ((0x35, 0x36), ItemKind('revive', **_PARTY_BOTH)),
    ((0x1D,), ItemKind('escape', True, False)),
    ((0x33,), ItemKind('escape', False, True, wild_only=True)),
    ((0x1E, 0x38, 0x39), ItemKind('repel', True, False)),
    ((0x23, 0x24, 0x25, 0x26, 0x27), ItemKind('vitamin', True, False, 'party')),
    ((0x28,), ItemKind('rare-candy', True, False, 'party')),
    ((0x2E, 0x37, 0x3A, 0x41, 0x42, 0x43, 0x44), ItemKind('battle-stat', False, True)),
    ((0x4C, 0x4D, 0x4E), ItemKind('fishing', True, False)),
    ((0x4F,), ItemKind('pp', True, False, 'move')),
    ((0x50, 0x51), ItemKind('pp', True, True, 'move')),
    ((0x52, 0x53), ItemKind('pp', **_PARTY_BOTH)),
    ((0x06,), ItemKind('key', True, False, note='Bicycle')),
    ((0x49,), ItemKind('key', True, True, note='Poke Flute')),
    ((0x45, 0x47), ItemKind('key', True, False, note='prints a message')),
    ((0x05, 0x07, 0x09, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1F, 0x29, 0x2A, 0x2B, 0x2C,
      0x2D, 0x30, 0x3F, 0x40, 0x46, 0x48, 0x4A),
     ItemKind('key', False, False, note='no shortcut effect')),
    ((0x31, 0x32, 0x3B, 0x4B), ItemKind('other', False, False, note='not usable')),
    (range(0xC4, 0xC9), ItemKind('hm', True, False, 'party')),
    (range(0xC9, 0xFB), ItemKind('tm', True, False, 'party')),
)

# Items the bag never lets the player toss or sell (pret KeyItemFlags, plus HMs).
GEN1_KEY_ITEMS = frozenset((0x05, 0x06, 0x07, 0x08, 0x09, *range(0x15, 0x1D), 0x1F, 0x29, 0x2A, 0x2B, 0x2C,
                            0x2D, 0x30, 0x3F, 0x40, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x4C, 0x4D,
                            0x4E, *range(0xC4, 0xC9)))
# Gen 1 move IDs of the five HM moves, which the learn-move menu refuses to forget.
GEN1_HM_MOVES = frozenset((15, 19, 57, 70, 148))
# Badge bit in wObtainedBadges for each field move, and the move ID.
GEN1_FIELD_MOVES = {'CUT': (15, 1), 'FLY': (19, 2), 'SURF': (57, 4), 'STRENGTH': (70, 3), 'FLASH': (148, 0)}

_HELD = ItemKind('held', False, False, note='hold item, pass it to give_item')
_MAIL = ItemKind('mail', False, False, note='mail is not supported by the shortcuts')
_SPOT = dict(note='works only at one place in the story')

# Gen 2 kinds from the pret pokecrystal and pokegold item attributes (pocket, field and battle menus).
GEN2_KINDS = _table(
    ((0x01, 0x02, 0x04, 0x05, 0x9D, 0x9F, 0xA0, 0xA1, 0xA4, 0xA5, 0xA6), ItemKind('ball', False, True,
                                                                                    wild_only=True)),
    ((0xB1,), ItemKind('ball', False, False, note='Bug-Catching Contest only')),
    ((0x08, 0x16, 0x17, 0x18, 0x22, 0xA9), ItemKind('evolution', True, False, 'party')),
    ((0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x26, 0x4A, 0x4E, 0x4F, 0x50, 0x54, 0x6D, 0x7B),
     ItemKind('status', **_PARTY_BOTH)),
    ((0x53,), ItemKind('status', False, True, 'party')),
    ((0x0E, 0x0F, 0x10, 0x11, 0x12, 0x2E, 0x2F, 0x30, 0x48, 0x72, 0x79, 0x7A, 0x8B, 0xAD, 0xAE),
     ItemKind('heal', **_PARTY_BOTH)),
    ((0x27, 0x28, 0x7C), ItemKind('revive', **_PARTY_BOTH)),
    ((0x9C,), ItemKind('revive', True, False)),
    ((0x13,), ItemKind('escape', True, False)),
    ((0x25,), ItemKind('escape', False, True, wild_only=True)),
    ((0x14, 0x2A, 0x2B), ItemKind('repel', True, False)),
    ((0x1A, 0x1B, 0x1C, 0x1D, 0x1F), ItemKind('vitamin', True, False, 'party')),
    ((0x20,), ItemKind('rare-candy', True, False, 'party')),
    ((0x21, 0x29, 0x2C, 0x31, 0x33, 0x34, 0x35), ItemKind('battle-stat', False, True)),
    ((0x3A, 0x3B, 0x3D), ItemKind('fishing', True, False)),
    ((0x3E,), ItemKind('pp', True, False, 'move')),
    ((0x3F, 0x40, 0x96), ItemKind('pp', True, True, 'move')),
    ((0x15, 0x41), ItemKind('pp', **_PARTY_BOTH)),
    ((0x07,), ItemKind('key', True, False, note='Bicycle')),
    ((0x36, 0x74), ItemKind('key', True, False, note='prints a message')),
    ((0x37,), ItemKind('key', True, False, note='Itemfinder')),
    ((0x7F, 0x85, 0xAF), ItemKind('key', False, False, **_SPOT)),
    ((0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x73, 0x80, 0x81, 0x82, 0x86, 0xB2),
     ItemKind('key', False, False, note='no shortcut effect')),
    ((0x03, 0x1E, 0x23, 0x39, 0x49, 0x4C, 0x4D, 0x51, 0x52, 0x58, 0x5B, 0x5E, 0x5F, 0x60, 0x62, 0x66, 0x68,
      0x69, 0x6A, 0x6B, 0x6C, 0x70, 0x71, 0x75, 0x76, 0x77, 0x7D, 0x7E, 0x8A, 0x8C, 0x8F, 0x90, 0x92, 0x97,
      0x98, 0xA3, 0xAA, 0xAC), _HELD),
    ((0x9E, *range(0xB5, 0xBE)), _MAIL),
    (range(0xBF, 0xF3), ItemKind('tm', True, False, 'party')),
    (range(0xF3, 0xFA), ItemKind('hm', True, False, 'party')),
)
GEN2_KINDS.pop(0xC3)
GEN2_KINDS.pop(0xDC)
# Crystal-only key items. Gold and Silver keep unused placeholders at these IDs.
GEN2_CRYSTAL_ONLY = frozenset((0x46, 0x73, 0x74, 0x81))
# Gen 2 items the pack never lets the player toss or sell (pret CANT_TOSS).
GEN2_KEY_ITEMS = frozenset((0x07, 0x36, 0x37, 0x3A, 0x3B, 0x3D, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x73, 0x74,
                            0x7F, 0x80, 0x81, 0x82, 0x85, 0x86, 0xAF, 0xB2, *range(0xF3, 0xFA)))
GEN2_BALLS = frozenset(item for item, kind in GEN2_KINDS.items() if kind.kind == 'ball')
GEN2_POCKETS = ('items', 'balls', 'key', 'tms_hms')
# Gen 2 field moves: move ID and the Johto badge bit, None when no badge is needed.
# The badge bits follow the game's order, where MINERALBADGE (4) comes before STORMBADGE (5).
GEN2_FIELD_MOVES = {'CUT': (15, 1), 'FLY': (19, 5), 'SURF': (57, 3), 'STRENGTH': (70, 2), 'FLASH': (148, 0),
                    'WHIRLPOOL': (250, 6), 'WATERFALL': (127, 7), 'ROCKSMASH': (249, None),
                    'HEADBUTT': (29, None)}
GEN2_HM_MOVES = frozenset((15, 19, 57, 70, 148, 250, 127))

GEN2 = ('gold', 'silver', 'crystal')
_OTHER = ItemKind('other', False, False, note='not usable')


def generation(version):
    version = getattr(version, 'version', version)
    if version in (None, 'red', 'blue', 'yellow'):
        return 1
    if version in GEN2:
        return 2
    raise ValueError(f'Unknown game version {version!r}')


def item_kind(item_id, version=None):
    """The :class:`ItemKind` of an item ID. Unknown IDs are ``other`` and not usable."""
    if generation(version) == 1:
        return GEN1_KINDS.get(item_id, _OTHER)
    if item_id in GEN2_CRYSTAL_ONLY and getattr(version, 'version', version) != 'crystal':
        return _OTHER
    return GEN2_KINDS.get(item_id, _OTHER)


def gen2_pocket(item_id, version='crystal'):
    """The Gen 2 pack pocket of an item ID: items, balls, key or tms_hms."""
    if tm_number(item_id, version):
        return 'tms_hms'
    if item_id in GEN2_BALLS:
        return 'balls'
    kind = item_kind(item_id, version).kind
    if kind in ('key', 'fishing') or (item_id in GEN2_KEY_ITEMS and kind != 'other'):
        return 'key'
    return 'items'


def key_item(item_id, version=None):
    """True for items the game never lets the player toss or sell."""
    if generation(version) == 1:
        return item_id in GEN1_KEY_ITEMS
    if item_id in GEN2_CRYSTAL_ONLY and getattr(version, 'version', version) != 'crystal':
        return False
    return item_id in GEN2_KEY_ITEMS


def tm_number(item_id, version=None):
    """('TM', n) or ('HM', n) for a machine item ID, otherwise None."""
    if generation(version) == 1:
        if 0xC4 <= item_id <= 0xC8:
            return 'HM', item_id - 0xC3
        if 0xC9 <= item_id <= 0xFA:
            return 'TM', item_id - 0xC8
        return None
    if 0xF3 <= item_id <= 0xF9:
        return 'HM', item_id - 0xF2
    if 0xBF <= item_id <= 0xF2 and item_id not in (0xC3, 0xDC):
        return 'TM', item_id - 0xBE - (item_id > 0xC3) - (item_id > 0xDC)
    return None


def gen2_tm_item(index):
    """Item ID of entry ``index`` (0 based) of Gen 2's 57-byte TM/HM quantity array."""
    if index >= 50:
        return 0xF3 + index - 50
    return 0xBF + index + (index >= 4) + (index >= 28)


# Encoded "MASTER BALL@ULTRA BALL@" and "POUND@KARATE CHOP@" anchors in the Gen 1 charmap.
_GEN1_ITEM_ANCHOR = bytes([0x8C, 0x80, 0x92, 0x93, 0x84, 0x91, 0x7F, 0x81, 0x80, 0x8B, 0x8B, 0x50,
                           0x94, 0x8B, 0x93, 0x91, 0x80, 0x7F, 0x81, 0x80, 0x8B, 0x8B, 0x50])
_GEN1_MOVE_ANCHOR = bytes([0x8F, 0x8E, 0x94, 0x8D, 0x83, 0x50, 0x8A, 0x80, 0x91, 0x80, 0x93, 0x84, 0x7F,
                           0x82, 0x87, 0x8E, 0x8F, 0x50])
_NAME_CACHE = {}


def _rom_banks(memory, banks=64):
    for bank in range(banks):
        try:
            data = bytes(memory[bank, 0x4000:0x8000]) if bank else bytes(memory[0:0x4000])
        except (TypeError, IndexError, KeyError, ValueError):
            return
        yield data


def _header(memory):
    try:
        return bytes(memory[0x134:0x150])
    except (TypeError, IndexError, ValueError):
        return None


def _decode_list(memory, anchor, count, key, decode=decode_text, banks=64):
    header = _header(memory)
    cache_key = (header, key)
    if header is not None and cache_key in _NAME_CACHE:
        return _NAME_CACHE[cache_key]
    names = {}
    for data in _rom_banks(memory, banks):
        start = data.find(anchor)
        if start < 0:
            continue
        position = start
        for index in range(1, count + 1):
            end = data.find(b'\x50', position)
            if end < 0:
                break
            names[index] = decode(data[position:end])
            position = end + 1
        break
    if header is not None:
        _NAME_CACHE[cache_key] = names
    return names


def _gen2_decode(raw):
    from ..gen2.tables import decode_text as gen2_decode
    return gen2_decode(bytes(raw) + b'\x50').replace('#', 'POKé').replace('<PK>', 'PK').replace('<MN>', 'MN')


def _gen2_anchor(text):
    from ..gen2.charmap import charmap
    table = {value: key for key, value in charmap('crystal').items() if len(value) == 1}
    return bytes(0x50 if char == '@' else table[char] for char in text)


def item_names(memory, version=None):
    """{item ID: name} decoded from the English cartridge in memory, or {} when not found.

    TMs and HMs are named TM01 to TM50 and HM01 to HM05 (HM07 in Gen 2), as the game prints them.
    """
    names = {}
    if generation(version) == 1:
        names.update(_decode_list(memory, _GEN1_ITEM_ANCHOR, 0x53, 'items'))
        candidates = range(0xC4, 0xFB)
    else:
        names.update({item: name for item, name in _decode_list(
            memory, _gen2_anchor('MASTER BALL@ULTRA BALL@'), 0xBE, 'gen2-items', _gen2_decode, 128).items()
            if name and name != 'TERU-SAMA'})
        candidates = range(0xBF, 0xFA)
    for item in candidates:
        number = tm_number(item, version)
        if number:
            names[item] = f'{number[0]}{number[1]:02d}'
    return names


def move_names(memory, version=None):
    """{move ID: name} decoded from the English cartridge in memory, or {} when not found."""
    if generation(version) != 1:
        return _decode_list(memory, _gen2_anchor('POUND@KARATE CHOP@'), 251, 'gen2-moves', _gen2_decode, 128)
    return _decode_list(memory, _GEN1_MOVE_ANCHOR, 165, 'moves')
