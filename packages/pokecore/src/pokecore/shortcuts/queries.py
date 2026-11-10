"""Read-only queries: bag, party, moves, boxes and the current screen. No input, no writes.

Every query takes ``memory`` and ``version`` (``None`` means Red or Blue). Gen 1
names come from the cartridge in memory (``item_names``, ``move_names``) unless
the caller passes ``labels`` ({item ID or str(ID): name}). Gen 2 reads use the
``gen2.state`` readers and the cartridge's name tables.
"""
from __future__ import annotations

from .. import gen1
from ..gen1_ui import read_storage
from ..yellow import red_layout
from .items import gen2_tm_item, generation, item_kind, item_names, move_names
from . import gen2ui
from .screens import current_screen as _current_screen


def _gen2():
    from ..gen2 import state
    return state


def _label(labels, key):
    value = labels.get(key, labels.get(str(key)))
    if isinstance(value, dict):
        value = value.get('name')
    return value if isinstance(value, str) else None


def _usability(kind, battle):
    if battle:
        usable = kind.battle
    else:
        usable = kind.field
    reason = '' if usable else kind.note or ('battle only' if kind.battle else 'field only' if kind.field
                                              else 'not usable')
    return usable, reason


def list_items(memory, version=None, *, labels=None):
    """Bag entries as dicts: id, name, qty, kind, pocket, usable (now), reason, target, field, battle.

    ``usable`` is for the current context (battle or not). It does not promise the
    game will accept the item, for example a Potion on a Pokemon at full HP.
    """
    labels = labels or {}
    gen = generation(version)
    if gen == 1:
        view = red_layout(memory, version)
        battle = view[0xD057] in (1, 2)
        entries = [(item, qty, 'items') for item, qty in gen1.read_bag(memory, version=version)]
        try:
            names = item_names(memory, version)
        except (TypeError, IndexError, KeyError, ValueError):
            names = {}
    else:
        state = _gen2()
        pockets = state.read_items(memory, version)
        battle = gen2ui.View(memory, version).byte('wBattleMode') != 0
        entries = [(item, qty, pocket) for pocket in ('items', 'balls', 'key') for item, qty in pockets[pocket]]
        entries += [(gen2_tm_item(index), qty, 'tms_hms') for index, qty in enumerate(pockets['tms_hms']) if qty]
        names = item_names(memory, version)
    out = []
    for item, qty, pocket in entries:
        kind = item_kind(item, version)
        usable, reason = _usability(kind, battle)
        out.append({'id': item, 'name': _label(labels, item) or names.get(item), 'qty': qty, 'pocket': pocket,
                    'kind': kind.kind, 'target': kind.target, 'field': kind.field, 'battle': kind.battle,
                    'usable': usable, 'reason': reason})
    return out


def list_party(memory, version=None):
    """Party members as dicts: slot (0 based), species, nick, level, hp, max_hp, status, moves, pp."""
    if generation(version) == 1:
        party = gen1.read_party(memory, version=version)
        return [{'slot': i, 'species': mon['species'], 'nick': mon['nick'], 'level': mon['level'],
                 'hp': mon['hp'], 'max_hp': mon['max_hp'], 'status': mon['status'],
                 'moves': list(mon['moves']), 'pp': list(mon['pp'])} for i, mon in enumerate(party)]
    party = _gen2().read_party_structs(memory, version)
    return [{'slot': i, 'species': mon['species'], 'nick': mon['nickname'], 'level': mon['level'],
             'hp': mon.get('hp'), 'max_hp': (mon.get('stats') or (None,))[0], 'status': mon.get('status'),
             'moves': list(mon['moves']), 'pp': list(mon['pp']), 'egg': mon['egg'],
             'held_item': mon['held_item']} for i, mon in enumerate(party)]


def list_moves(memory, slot, version=None):
    """Moves of party ``slot`` as dicts: index (0 based), id, name, pp, pp_ups. Empty slots are left out."""
    if type(slot) is not int or not 0 <= slot < 6:
        raise ValueError('Party slot must be an integer from 0 through 5')
    gen = generation(version)
    if gen == 1:
        party = gen1.read_party(memory, version=version)
        names = move_names(memory, version)
        view = red_layout(memory, version)
    else:
        party = _gen2().read_party_structs(memory, version)
        names = move_names(memory, version)
    if slot >= len(party):
        return []
    mon = party[slot]
    out = []
    for index, move in enumerate(mon['moves']):
        if not move:
            continue
        if gen == 1:
            raw = view[0xD16B + slot * 44 + 29 + index]
            ups = raw >> 6
        else:
            ups = mon['pp_ups'][index]
        out.append({'index': index, 'id': move, 'name': names.get(move), 'pp': mon['pp'][index], 'pp_ups': ups})
    return out


def list_box(memory, box=None, version=None):
    """Pokemon in a PC box (0 based, the current box by default) as dicts, or None when unreadable.

    Gen 1 boxes other than the current one need banked cartridge RAM reads.
    """
    if generation(version) == 1:
        storage = read_storage(memory, version=version)
        if not storage['available']:
            return None
        box = storage['active_box'] - 1 if box is None else box
        if type(box) is not int or not 0 <= box < 12:
            raise ValueError('Gen 1 box must be 0 through 11')
        entry = storage['boxes'][box]
        if not entry['available']:
            return None
        return [{'position': mon['slot'] - 1, 'species': mon['species'], 'nick': mon['nick'],
                 'level': mon['level'], 'moves': mon['moves']} for mon in entry['pokemon']]
    try:
        mons = _gen2().read_box_structs(memory, version, box)
    except (TypeError, IndexError, KeyError):
        return None
    return [{'position': i, 'species': mon['species'], 'nick': mon['nickname'], 'level': mon['level'],
             'moves': list(mon['moves']), 'egg': mon['egg']} for i, mon in enumerate(mons)]


def current_screen(memory, version=None):
    """The visible screen name, see ``screens.SCREENS``."""
    return _current_screen(memory, version=version)
