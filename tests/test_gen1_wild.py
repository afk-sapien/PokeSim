"""The Gen I wild table is generated from the disassembly and agrees with the encounters the planner already reads."""
import importlib.util
import os
from pathlib import Path

import pytest

from pokesim.game_data import SOURCE_REVISION, YELLOW_REVISION
from pokesim.planning.cost import slot_chance
from pokesim.policies import wild
from pokesim.strategy_data import MAPS, SPECIES, WORLD

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / 'pokesim' / 'policies' / 'wild.py'
_spec = importlib.util.spec_from_file_location('gen1_wild_tool', ROOT / 'tools' / 'gen1_wild.py')
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

CHECKOUTS = (('pokered', 'POKERED_SOURCE', SOURCE_REVISION), ('pokeyellow', 'POKEYELLOW_SOURCE', YELLOW_REVISION))


def checkout(name, env, revision):
    """A pret checkout at the pinned commit from ``env`` or the .reference folder CI fills, or None."""
    path = Path(os.environ.get(env) or ROOT / '.reference' / name)
    if not (path / 'data' / 'wild').is_dir() or tool.source(path)[1] != revision:
        return None
    return path


def test_the_table_names_the_commits_it_came_from():
    head = TABLE.read_text(encoding='utf-8').splitlines()[:2]
    assert f'pret/pokered {SOURCE_REVISION}' in head[0]
    assert f'pret/pokeyellow {YELLOW_REVISION}' in head[1]
    assert 'not written by hand' in wild.__doc__


def test_every_map_has_ten_slots_for_each_rate_and_every_name_is_known():
    names = {entry['name'] for entry in SPECIES.values()}
    assert len(wild.SLOT_CHANCES) == 10 and sum(wild.SLOT_CHANCES) == 256
    for game, table in wild.BY_GAME.items():
        assert table, game
        for name, parts in table.items():
            assert name in MAPS, (game, name)
            for rate, slots in parts:
                assert len(slots) == (10 if rate else 0), (game, name)
                assert {species for _, species in slots} <= names, (game, name)


def test_red_and_blue_grass_is_what_the_planner_already_reads():
    """The strategy data lists the grass slots of Red and Blue together for partner searches."""
    ids = {entry['name']: number for number, entry in SPECIES.items()}
    symbols = {number: name for name, number in MAPS.items()}
    for number, world in WORLD.items():
        slots = {slot for game in (wild.RED, wild.BLUE) for slot in game.get(symbols[number], ((0, ()), (0, ())))[0][1]}
        assert {(ids[species], level) for level, species in slots} == {tuple(p) for p in world['encounters']}, symbols[number]


def test_blue_has_its_own_slots_only_where_pokered_says():
    assert wild.BLUE.keys() == wild.RED.keys()
    # Route 2 holds the bug in slots 5, 8 and 9: 25, 11 and 3 of 256.
    assert slot_chance(wild.RED['ROUTE_2'][0][1], 'WEEDLE', wild.SLOT_CHANCES) == pytest.approx(100 * 39 / 256)
    assert slot_chance(wild.BLUE['ROUTE_2'][0][1], 'WEEDLE', wild.SLOT_CHANCES) == 0
    assert slot_chance(wild.BLUE['ROUTE_2'][0][1], 'CATERPIE', wild.SLOT_CHANCES) == pytest.approx(100 * 39 / 256)
    assert wild.BLUE['ROUTE_1'] is wild.RED['ROUTE_1']
    # Yellow surfs up Psyduck on Route 6, which Red and Blue do not.
    assert wild.YELLOW['ROUTE_6'][1][0] == 3 and wild.RED['ROUTE_6'][1] == (0, ())


@pytest.mark.parametrize('name, env, revision', CHECKOUTS)
def test_the_table_is_what_the_tool_generates_from_the_pinned_source(name, env, revision):
    src = checkout(name, env, revision)
    if src is None:
        pytest.skip(f'no {name} checkout at the pinned commit, set {env} or fill .reference/{name}')
    table = TABLE.read_text(encoding='utf-8')
    body = tool.red_body(src) if name == 'pokered' else tool.yellow_body(src)
    assert body in table, 'regenerate pokesim/policies/wild.py with tools/gen1_wild.py'
    red, yellow = (checkout(*row) for row in CHECKOUTS)
    if red and yellow:
        assert table == tool.render(red, yellow)
