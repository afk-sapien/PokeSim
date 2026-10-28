"""The Gen I gate table is generated from the disassembly, and navigation closes the same gates as before."""
import importlib.util
import itertools
import os
from pathlib import Path

import pytest

from pokesim.game_data import SOURCE_REVISION, YELLOW_REVISION
from pokesim.policies import gates
from pokesim.policies.navigation import CLOSED_GATE_TILES, Navigator
from pokesim.strategy_data import ITEMS, MAPS, WORLD, event_set
from test_events import snap
from test_strategy import flags

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / 'pokesim' / 'policies' / 'gates.py'
_spec = importlib.util.spec_from_file_location('gen1_gates_tool', ROOT / 'tools' / 'gen1_gates.py')
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

# The lists navigation kept by hand before the table, to show it closes the same gates.
FORMER_ROUTE_23 = ((136, 2), (119, 4), (105, 8), (96, 16), (85, 32), (56, 64), (35, 128))
FORMER_CYCLING_ROAD = (('ROUTE_16_GATE_1F', ((4, 7), (4, 8), (4, 9), (4, 10))),
                       ('ROUTE_18_GATE_1F', ((4, 3), (4, 4), (4, 5), (4, 6))))
FORMER_SAFFRON = (('ROUTE_5_GATE', ((3, 3), (4, 3))), ('ROUTE_6_GATE', ((3, 2), (4, 2))),
                  ('ROUTE_7_GATE', ((3, 3), (3, 4))), ('ROUTE_8_GATE', ((2, 3), (2, 4))))
FORMER_CINNABAR = ((9, 3, False), (6, 3, False), (6, 6, False), (3, 8, True), (2, 6, False), (2, 3, False))
FORMER_DRINKS = ('FRESH_WATER', 'SODA_POP', 'LEMONADE')


def checkout(name, env):
    """A pret checkout from ``env`` or the .reference folder CI fills, or None."""
    path = Path(os.environ.get(env) or ROOT / '.reference' / name)
    return path if (path / 'scripts').is_dir() else None


def former_gates(s):
    """The gate tiles and Cinnabar door tiles navigation closed before it read the table."""
    blocks, overrides = set(), {}
    held = {item for item, qty in s.items if qty}
    gym = MAPS['CINNABAR_GYM']
    for index, (bx, by, vertical) in enumerate(FORMER_CINNABAR):
        if not event_set(s.event_flags, f'EVENT_CINNABAR_GYM_GATE{index + 1}_UNLOCKED'):
            overrides.update(((gym, bx * 2 + dx, by * 2 + dy), tile) for (dx, dy), tile in CLOSED_GATE_TILES[vertical])
    for row, badge in FORMER_ROUTE_23:
        if not s.badges & badge:
            blocks.update((MAPS['ROUTE_23'], x, row) for x in range(WORLD[MAPS['ROUTE_23']]['width']))
    if ITEMS['BICYCLE'] not in held:
        blocks.update((MAPS[name], x, y) for name, coords in FORMER_CYCLING_ROAD for x, y in coords)
    if not s.saffron_open and not held & {ITEMS[name] for name in FORMER_DRINKS}:
        blocks.update((MAPS[name], x, y) for name, coords in FORMER_SAFFRON for x, y in coords)
    if ITEMS['CARD_KEY'] not in held:
        blocks.update((m, x + dx, y + dy) for m, world in WORLD.items() for x, y, flag in world.get('locked_doors', [])
                      if not event_set(s.event_flags, flag) for dx in range(2) for dy in range(2))
    return blocks, overrides


def gate_tiles(nav):
    """The story blocks a gate can add, leaving out Seafoam and the other blocks no gate decides."""
    tiles = {(MAPS[name], x, y) for name, coords in FORMER_CYCLING_ROAD + FORMER_SAFFRON for x, y in coords}
    tiles |= {(m, x + dx, y + dy) for m, world in WORLD.items() for x, y, _ in world.get('locked_doors', [])
              for dx in range(2) for dy in range(2)}
    return {q for q in nav.story_blocks if q in tiles or q[0] == MAPS['ROUTE_23']}


def test_the_table_names_the_commit_it_came_from():
    assert f'pret/pokered {SOURCE_REVISION}' in TABLE.read_text(encoding='utf-8').splitlines()[0]
    assert 'not written by hand' in gates.__doc__


def test_navigation_closes_the_gates_it_closed_before_the_table():
    silph = [flag for world in WORLD.values() for _, _, flag in world.get('locked_doors', [])]
    doors = [f'EVENT_CINNABAR_GYM_GATE{n}_UNLOCKED' for n in range(1, 7)]
    held = [(), ((ITEMS['BICYCLE'], 1),), ((ITEMS['SODA_POP'], 1),), ((ITEMS['CARD_KEY'], 1),),
            ((ITEMS['LEMONADE'], 0), (ITEMS['BICYCLE'], 0))]
    events = [flags(), flags(*doors[:3], silph[0]), flags(*doors, *silph)]
    nav = Navigator()
    closed = former_gates(snap(event_flags=flags()))[1]
    for badges, items, saffron, event_flags in itertools.product((0, 2, 63, 127, 191, 255), held, (False, True), events):
        s = snap(map=MAPS['ROUTE_23'], badges=badges, items=items, saffron_open=saffron, event_flags=event_flags)
        nav.update_story(s)
        blocks, overrides = former_gates(s)
        # The game checks the Earth Badge row only west of x 14, where the Victory Road exit is not.
        assert gate_tiles(nav) == {q for q in blocks if not (q[0] == MAPS['ROUTE_23'] and q[2] == 35 and q[1] >= 14)}
        assert {q: tile for q, tile in nav.tile_overrides.items() if closed.get(q) == tile} == overrides


def test_every_name_in_the_table_is_a_known_map_or_item():
    assert all(name in MAPS for name, _ in gates.CYCLING_ROAD + gates.SAFFRON_GATES)
    assert all(name in ITEMS for name in gates.DRINKS)
    assert gates.DRINKS == FORMER_DRINKS and gates.CINNABAR_GYM_DOORS == FORMER_CINNABAR
    # Only the Earth Badge guard by the Victory Road exit checks part of its row.
    assert [limit for _, _, limit in gates.ROUTE_23_GUARDS] == [13, None, None, None, None, None, None]


@pytest.mark.parametrize('name, env, revision', [('pokered', 'POKERED_SOURCE', SOURCE_REVISION),
                                                 ('pokeyellow', 'POKEYELLOW_SOURCE', YELLOW_REVISION)])
def test_the_table_is_what_the_tool_generates_from_the_pinned_source(name, env, revision):
    src = checkout(name, env)
    if src is None:
        pytest.skip(f'no {name} checkout, set {env} or fill .reference/{name}')
    if tool.source(src)[1] != revision:
        pytest.skip(f'{name} checkout is not at the pinned commit')
    table = TABLE.read_text(encoding='utf-8')
    # Red and Yellow agree on every gate, so both give the same table under the header.
    assert table.endswith(tool.body(src)), 'regenerate pokesim/policies/gates.py with tools/gen1_gates.py'
    if name == 'pokered':
        assert table == tool.render(src)
