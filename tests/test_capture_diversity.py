"""Capture and storage decisions account for the whole collection."""
from dataclasses import replace

import pytest

from pokesim.policies.battle import choose_battle, useful_capture
from pokesim.policies.strategic import StrategicPolicy
from pokesim.policies.team import release_target
from pokesim.screen import Screen
from pokesim.strategy_data import ITEMS, SPECIES
from test_duplicates import snapshot, stored
from test_events import snap
from test_strategy import mon, menu


def sid(dex):
    return next(key for key, data in SPECIES.items() if data['dex'] == dex)


def collection(**changes):
    values = dict(party=(mon(level=52), mon(level=100)), owned=frozenset({1, 67}),
                  stored_pokemon=tuple((i // 20, sid(67), 41, '') for i in range(102)),
                  in_battle=1, items=((ITEMS['POKE_BALL'], 10),))
    values.update(changes)
    return snap(**values)


@pytest.mark.parametrize('level', [41, 42, 45])
def test_machoke_pile_does_not_justify_another_capture(level):
    state = collection()
    enemy = mon(species=sid(67), types=(1, 1), level=level, hp=1, moves=(), pp=())
    assert not useful_capture(state, enemy.species, level)
    assert choose_battle(state, state.party[0], enemy, 0, collect_missing=True).kind != 'item'


def test_coverage_checks_other_species_in_distant_boxes():
    state = collection(stored_pokemon=((11, sid(68), 55, ''),))
    assert not useful_capture(state, sid(67), 60)
    assert useful_capture(replace(state, stored_pokemon=()), sid(67), 60)


def test_weak_lead_does_not_lower_the_team_coverage_threshold():
    state = collection(party=(mon(level=10), mon(level=100)), stored_pokemon=())
    assert not useful_capture(state, sid(67), 41)
    assert useful_capture(state, sid(67), 50)


def test_genuine_upgrade_is_allowed_once_then_reassessed():
    state = collection(stored_pokemon=((11, sid(67), 50, ''),))
    assert not useful_capture(state, sid(67), 54)
    assert useful_capture(state, sid(67), 55)
    state = replace(state, stored_pokemon=state.stored_pokemon + ((0, sid(67), 55, ''),))
    assert not useful_capture(state, sid(67), 55)
    assert not useful_capture(state, sid(67), 60)
    assert useful_capture(state, sid(67), 61)


def test_missing_entry_and_explicit_field_move_goal_still_capture():
    state = collection()
    enemy = mon(species=sid(25), level=3, hp=1, moves=(), pp=())
    assert choose_battle(state, state.party[0], enemy, 0, collect_missing=True).kind == 'item'
    assert useful_capture(state, sid(67), 10, required_move=70)


def test_compact_active_box_and_party_also_prevent_duplicates():
    state = collection(stored_pokemon=(), boxed_pokemon=((sid(67), 50),))
    assert not useful_capture(state, sid(67), 50)
    state = replace(state, boxed_pokemon=(), party=state.party + (mon(species=sid(67), level=50),))
    assert not useful_capture(state, sid(67), 50)


def test_safari_flees_unneeded_duplicate_but_catches_missing_species():
    policy = StrategicPolicy(7)
    state = collection(enemy_species=sid(67), enemy_level=41)
    memory = menu({12: 'BALL', 14: 'ROCK'}, (1, 12), top=(1, 12))
    assert policy._dispatch(state, Screen(memory), 'safari', memory)[0].button == 'right'
    missing = replace(state, owned=frozenset({1}))
    assert policy._dispatch(missing, Screen(memory), 'safari', memory)[0].button == 'a'


def test_cleanup_targets_abundance_before_low_level_rarity():
    copies = [stored(i, species=sid(67), level=41 + i) for i in range(4)]
    copies += [stored(4, species=sid(25), level=3), stored(5, species=sid(25), level=4)]
    state = snapshot(copies)
    assert release_target(state) == (0, 0)
    assert release_target(state, reserved={(0, 0)}) == (0, 1)
    assert release_target(state, protected={sid(67)}) == (0, 4)
    assert release_target(state, reserved={(0, 0), (0, 1), (0, 2)}) == (0, 4)


def test_cleanup_preserves_best_copy_and_releases_least_invested_equal_level():
    state = snapshot([stored(0, dvs=(15,) * 5), stored(1, dvs=(0,) * 5),
                      stored(2, stat_exp=(10000,) * 5)])
    assert release_target(state) == (0, 1)
