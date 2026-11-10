"""The Gen I hand rows give navigation the tables it kept by hand, and each row matches its script."""
import itertools
import re
from pathlib import Path

import pytest

from pokesim.data_tools.strategy import switched_blocks
from pokesim.mapfacts.gen1_hand import HAND
from pokesim.policies.navigation import CURRENTS, FORCED, MANSION_FALLS, OPTIONAL_LIFTS, SEAFOAM_HOLES, Navigator
from pokesim.strategy_data import MAPS, WORLD
from test_events import snap
from test_gen1_map_facts import SOURCES, pinned, tool
from test_strategy import flags

# The tables navigation and data_tools/strategy.py kept by hand before the rows, keyed by map constant.
FORMER_LIFTS = {'CELADON_MART_ELEVATOR', 'SILPH_CO_ELEVATOR'}
FORMER_VICTORY_ROAD_FALL = {('VICTORY_ROAD_3F', 23, 15): ('VICTORY_ROAD_2F', 22, 16)}
FORMER_MANSION_FALLS = {('POKEMON_MANSION_3F', x, 14): ('POKEMON_MANSION_1F', 16, 14) for x in (16, 17)}
FORMER_SEAFOAM_HOLES = {
    'SEAFOAM_ISLANDS_1F': ((17, 6), (24, 6)),
    'SEAFOAM_ISLANDS_B1F': ((18, 6), (23, 6)),
    'SEAFOAM_ISLANDS_B2F': ((19, 6), (22, 6)),
    'SEAFOAM_ISLANDS_B3F': ((3, 16), (6, 16)),
}
FORMER_CURRENT_FLAGS = ('EVENT_SEAFOAM3_BOULDER1_DOWN_HOLE', 'EVENT_SEAFOAM3_BOULDER2_DOWN_HOLE')
FORMER_CURRENT = {('SEAFOAM_ISLANDS_B3F', 15, 8)} | {('SEAFOAM_ISLANDS_B4F', x, y) for x in (20, 21) for y in (16, 17)}
FORMER_SWITCH_BLOCKS = {
    'POKEMON_MANSION_1F': [(12, 6, 0x0E, 0x2D), (8, 3, 0x2D, 0x0E), (10, 8, 0x2D, 0x0E), (13, 13, 0x2D, 0x0E)],
    'POKEMON_MANSION_2F': [(4, 2, 0x0E, 0x5F), (9, 4, 0x54, 0x0E), (3, 11, 0x5F, 0x0E)],
    'POKEMON_MANSION_3F': [(7, 2, 0x0E, 0x5F), (7, 5, 0x5F, 0x0E)],
    'POKEMON_MANSION_B1F': [(13, 8, 0x0E, 0x2D), (6, 11, 0x0E, 0x5F), (4, 3, 0x5F, 0x0E), (8, 8, 0x54, 0x0E)],
}


def squares(names):
    """Squares keyed by map constant, as navigation keys them."""
    return {(MAPS[name], x, y) for name, x, y in names}


def moves(table):
    return {(MAPS[name], x, y): (MAPS[to], tx, ty) for (name, x, y), (to, tx, ty) in table.items()}


def test_navigation_reads_the_tables_it_kept_by_hand():
    assert OPTIONAL_LIFTS == {MAPS[name] for name in FORMER_LIFTS}
    assert MANSION_FALLS == moves(FORMER_MANSION_FALLS)
    assert SEAFOAM_HOLES == squares((name, x, y) for name, points in FORMER_SEAFOAM_HOLES.items() for x, y in points)
    assert len(SEAFOAM_HOLES) == 8
    assert [until for until, _ in CURRENTS] == [FORMER_CURRENT_FLAGS] * 2
    assert set().union(*(held for _, held in CURRENTS)) == squares(FORMER_CURRENT)


def test_the_victory_road_fall_is_the_only_forced_move_not_in_the_map_data():
    walked = {(m, x, y): (m, tx, ty) for m, w in WORLD.items() for x, y, tx, ty in w.get('forced_moves', [])}
    assert FORCED == walked | moves(FORMER_VICTORY_ROAD_FALL)
    assert not FORCED.keys() & MANSION_FALLS.keys()


def test_the_mansion_switches_flip_the_blocks_strategy_flipped_by_hand():
    switched = {name: sorted(switched_blocks(name)) for name in MAPS if switched_blocks(name)}
    assert switched == {name: sorted(blocks) for name, blocks in FORMER_SWITCH_BLOCKS.items()}


def test_routes_keep_off_the_currents_until_both_boulders_fall():
    nav = Navigator()
    for count in range(len(FORMER_CURRENT_FLAGS) + 1):
        for names in itertools.combinations(FORMER_CURRENT_FLAGS, count):
            nav.update_story(snap(map=MAPS['SEAFOAM_ISLANDS_B3F'], event_flags=flags(*names)))
            assert SEAFOAM_HOLES <= nav.story_blocks
            current = squares(FORMER_CURRENT) & nav.story_blocks
            assert current == (set() if count == 2 else squares(FORMER_CURRENT))


@pytest.mark.parametrize('row', HAND, ids=lambda row: f'{row.map}-{row.kind}')
def test_each_hand_row_says_what_it_does_and_why(row):
    assert row.generated is False
    assert row.map in MAPS and row.kind in {'hole', 'current', 'lift'}
    assert row.effect in {'avoid', 'fall', 'skip'}
    assert (row.tiles is None) == (row.effect == 'skip')
    assert (row.to is not None) == (row.effect == 'fall') and (row.to is None or row.to[0] in MAPS)
    assert row.reason.endswith('.') and len(row.source) == 2


def label(script, name):
    """(the lines of the global label's scope, the lines after the label itself) in a script.

    name is a global label, or Global.local for a local label under it.
    """
    lines = tool._code(script.read_text(encoding='utf-8')).splitlines()
    head, _, local = name.partition('.')
    start = next(i for i, line in enumerate(lines) if re.fullmatch(rf'{head}::?', line))
    end = next((i for i in range(start + 1, len(lines)) if re.match(r'[A-Za-z_]\w*::?(\s|$)', lines[i])),
               len(lines))
    scope = lines[start + 1:end]
    if not local:
        return scope, scope
    return scope, scope[next(i for i, line in enumerate(scope) if re.fullmatch(rf'\s*\.{local}:?', line)) + 1:]


def listed(lines):
    """The dbmapcoord list at the top of lines, as (x, y) squares."""
    out = []
    for line in lines:
        if not (found := re.fullmatch(r'\s*dbmapcoord\s+(\d+),\s*(\d+)', line)):
            break
        out.append((int(found[1]), int(found[2])))
    return out


def compared(scope, coord):
    """The values the script compares the player's coord with."""
    return {int(value) for value in re.findall(rf'ld a, \[{coord}\]\n\s*cp (\d+)\b', '\n'.join(scope))}


@pytest.mark.parametrize('name, env, revision', SOURCES)
@pytest.mark.parametrize('row', HAND, ids=lambda row: f'{row.map}-{row.kind}')
def test_each_hand_row_matches_its_script(row, name, env, revision):
    src = pinned(name, env, revision)
    script = Path(src) / 'scripts' / f'{row.source[0]}.asm'
    assert tool._map_name(src, script) == row.map
    scope, after = label(script, row.source[1])
    if row.tiles is not None:
        coords = listed(after) or itertools.product(compared(scope, 'wXCoord'), compared(scope, 'wYCoord'))
        assert row.tiles and set(row.tiles) <= set(coords)
    text = '\n'.join(scope)
    assert all(re.search(rf'\b{flag}\b', text) for flag in row.until)
    if row.to:
        warps = tool._read(src, 'data/maps/special_warps.asm')
        assert re.search(rf'\bld a, {row.to[0]}\b', text)
        assert re.search(rf'\bfly_warp\s+{row.to[0]},\s*{row.to[1]},\s*{row.to[2]}\b', warps)
