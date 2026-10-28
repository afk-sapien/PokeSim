"""The Gen I gate table is generated from the disassembly and agrees with the lists navigation uses today."""
import importlib.util
import os
from pathlib import Path

import pytest

from pokesim.game_data import SOURCE_REVISION, YELLOW_REVISION
from pokesim.policies import gates
from pokesim.policies.navigation import CINNABAR_GYM_GATES, CYCLING_ROAD_CHECKS, ROUTE_23_CHECKS
from pokesim.strategy_data import ITEMS, MAPS

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / 'pokesim' / 'policies' / 'gates.py'
_spec = importlib.util.spec_from_file_location('gen1_gates_tool', ROOT / 'tools' / 'gen1_gates.py')
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def checkout(name, env):
    """A pret checkout from ``env`` or the .reference folder CI fills, or None."""
    path = Path(os.environ.get(env) or ROOT / '.reference' / name)
    return path if (path / 'scripts').is_dir() else None


def test_the_table_names_the_commit_it_came_from():
    assert f'pret/pokered {SOURCE_REVISION}' in TABLE.read_text(encoding='utf-8').splitlines()[0]
    assert 'not written by hand' in gates.__doc__


def test_the_table_matches_the_lists_navigation_uses_today():
    assert gates.CYCLING_ROAD == CYCLING_ROAD_CHECKS
    assert tuple((row, badge) for row, badge, _ in gates.ROUTE_23_GUARDS) == tuple(reversed(ROUTE_23_CHECKS))
    assert gates.CINNABAR_GYM_DOORS == CINNABAR_GYM_GATES
    # Navigation spells the Saffron gates out inside its story rebuild.
    assert gates.SAFFRON_GATES == (('ROUTE_5_GATE', ((3, 3), (4, 3))), ('ROUTE_6_GATE', ((3, 2), (4, 2))),
                                   ('ROUTE_7_GATE', ((3, 3), (3, 4))), ('ROUTE_8_GATE', ((2, 3), (2, 4))))
    assert gates.DRINKS == ('FRESH_WATER', 'SODA_POP', 'LEMONADE')


def test_every_name_in_the_table_is_a_known_map_or_item():
    assert all(name in MAPS for name, _ in gates.CYCLING_ROAD + gates.SAFFRON_GATES)
    assert all(name in ITEMS for name in gates.DRINKS)
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
