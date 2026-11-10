"""Verified retail Red, Blue and Yellow Cable Club preparation locations.

A cable session starts with each trainer standing in a Pokémon Center that has a
Cable Club attendant. ``CENTERS`` maps each supported map ID to its PC tile and the
tile in front of the attendant (``rendezvous``). The Celadon hotel has no attendant.
"""
from types import SimpleNamespace

from .gen1 import (W_BATTLE_TYPE, W_CUR_MAP, W_IS_IN_BATTLE, W_PARTY_COUNT, W_PARTY_MONS, W_PLAYTIME_H, W_TILEMAP,
                   W_X, W_Y, TILE_BOX_TL, PARTY_STRUCT)
from .gen1_ui import read_screen
from .textmatch import ScreenText

_STANDARD = {
    41: 'Viridian Pokémon Center',
    58: 'Pewter Pokémon Center',
    64: 'Cerulean Pokémon Center',
    68: 'Mt. Moon Pokémon Center',
    81: 'Rock Tunnel Pokémon Center',
    89: 'Vermilion Pokémon Center',
    133: 'Celadon Pokémon Center',
    141: 'Lavender Pokémon Center',
    154: 'Fuchsia Pokémon Center',
    171: 'Cinnabar Pokémon Center',
    182: 'Saffron Pokémon Center',
}

CENTERS = {map_id: {'name': name, 'pc': (map_id, 13, 4),
                    'rendezvous': (map_id, 11, 3)} for map_id, name in _STANDARD.items()}
CENTERS[174] = {'name': 'Indigo Plateau lobby', 'pc': (174, 15, 8),
                'rendezvous': (174, 13, 7)}
# The highest Red and Blue map ID. Higher values in wCurMap are not a loaded map.
LAST_MAP = 0xF7
# wUpdateSpritesEnabled is 1 while the overworld runs and 0xFF while the title or
# Continue screen shows the save that was just loaded.
W_UPDATE_SPRITES_ENABLED = 0xCFCB
W_TOP_MENU_Y = 0xCC24
W_TOP_MENU_X = 0xCC25


def screen(memory):
    """The raw screen text and menu cursor. ``text`` matches whole words with ``in``."""
    view = read_screen(memory, raw_text=True)
    return SimpleNamespace(rows=view['rows'], text=ScreenText('\n'.join(view['rows'])), cursor=view['cursor'],
                           menu_index=view['menu_index'], top_x=memory[W_TOP_MENU_X], top_y=memory[W_TOP_MENU_Y])


def location(memory):
    """The fields ``safe_center`` reads, decoded from Red-layout memory without game tables.

    ``valid`` is a table-free sanity check: a real map ID, a known battle mode, a
    playtime clock below 60, and party levels and HP in range. ``started`` is true once
    the trainer has a map, playtime or a party.
    """
    in_battle = memory[W_IS_IN_BATTLE]
    count = memory[W_PARTY_COUNT]
    party = []
    for index in range(min(count, 6)):
        base = W_PARTY_MONS + index * PARTY_STRUCT
        party.append((memory[base + 33], memory[base + 1] << 8 | memory[base + 2],
                      memory[base + 34] << 8 | memory[base + 35]))
    hours, minutes, seconds = memory[W_PLAYTIME_H], memory[W_PLAYTIME_H + 2], memory[W_PLAYTIME_H + 3]
    map_id = memory[W_CUR_MAP]
    started = bool(map_id or hours or minutes or seconds or party)
    valid = (map_id <= LAST_MAP and in_battle in (0, 1, 2, 0xFF) and minutes <= 59 and seconds <= 59
             and count <= 6 and all(level <= 100 and hp <= max_hp for level, hp, max_hp in party)
             and not (in_battle in (1, 2) and not party and started))
    return SimpleNamespace(map=map_id, x=memory[W_X], y=memory[W_Y], in_battle=in_battle,
                           battle_type=memory[W_BATTLE_TYPE], started=started, valid=valid,
                           textbox=memory[W_TILEMAP + 12 * 20] == TILE_BOX_TL,
                           start_menu=memory[W_TILEMAP + 10] == TILE_BOX_TL and not in_battle)


def _overworld(view):
    """No naming keyboard and no quantity prompt. The caller has ruled out every cursor and text box."""
    naming = any(row[2:19:2] in ('ABCDEFGHI', 'abcdefghi') for row in view.rows)
    return not naming and 'HOW MANY' not in ScreenText(view.text.upper())


def safe_center(snapshot, map_id, memory):
    """Require a loaded overworld in Center ``map_id``, not the save data shown by Continue.

    ``snapshot`` needs ``valid``, ``started``, ``map``, ``in_battle``, ``textbox`` and
    ``start_menu``, as ``location(memory)`` gives. ``memory`` is Red-layout memory.
    """
    view = screen(memory)
    return (type(map_id) is int and map_id in CENTERS and snapshot.valid and snapshot.started
            and snapshot.map == map_id and not snapshot.in_battle
            and not snapshot.textbox and not snapshot.start_menu
            and memory[W_UPDATE_SPRITES_ENABLED] == 1 and view.cursor is None
            and 'CONTINUE' not in view.text and 'NEW GAME' not in view.text
            and _overworld(view))
