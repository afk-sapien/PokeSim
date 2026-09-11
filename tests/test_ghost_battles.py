from dataclasses import replace

import pytest

from pokesim.policies.battle import choose_battle
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap
from test_strategy import mon


def encounter(**changes):
    me = mon(level=35, hp=100, max_hp=100, moves=(52,), pp=(25,), special=100)
    enemy = mon(species=25, level=20, hp=40, max_hp=40, types=(8, 3), moves=(122,), pp=(30,))
    s = snap(map=MAPS['POKEMON_TOWER_3F'], in_battle=1, party=(me,), owned=frozenset({92}))
    return replace(s, **changes), me, enemy


@pytest.mark.parametrize('floor', range(1, 8))
def test_unidentified_tower_ghosts_are_escaped(floor):
    s, me, enemy = encounter(map=MAPS[f'POKEMON_TOWER_{floor}F'],
                             items=((ITEMS['POKE_BALL'], 10),))
    assert choose_battle(s, me, enemy, 0, collect_missing=True).kind == 'run'


def test_silph_scope_allows_normal_battle_decisions():
    s, me, enemy = encounter(items=((ITEMS['SILPH_SCOPE'], 1),))
    assert choose_battle(s, me, enemy, 0).kind == 'fight'


def test_tower_trainers_do_not_trigger_ghost_escape():
    s, me, enemy = encounter(in_battle=2)
    assert choose_battle(s, me, enemy, 0).kind == 'fight'


def test_ghost_species_outside_tower_do_not_trigger_ghost_escape():
    s, me, enemy = encounter(map=MAPS['ROUTE_1'])
    assert choose_battle(s, me, enemy, 0).kind == 'fight'
