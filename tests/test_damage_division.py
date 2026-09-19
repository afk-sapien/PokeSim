"""Avoid the cartridge's zero-defense damage calculation freeze."""
from dataclasses import replace

import pytest

from pokesim.policies.battle import (Decision, W_BATTLE_MON, W_ENEMY_MON,
                                    choose_battle, damage_division_safe, ranked_moves)
from pokesim.policies.strategic import StrategicPolicy
from pokesim.screen import Screen
from test_disabled_moves import battler
from test_events import snap
from test_strategy import menu, mon


def matchup():
    player = mon(species=39, level=100, hp=289, max_hp=307, attack=324,
                 defense=337, special=191, moves=(89, 153, 88, 70), pp=(10, 5, 15, 4))
    enemy = mon(species=165, level=2, hp=13, max_hp=13, attack=7, defense=3,
                special=6, types=(0, 0), moves=(33, 39, 0, 0), pp=(35, 30, 0, 0))
    return player, enemy


@pytest.mark.parametrize('defense, safe', [(1, False), (2, False), (3, False), (4, True), (255, True)])
def test_strength_rejects_zero_after_scaling(defense, safe):
    player, enemy = matchup()
    assert damage_division_safe(70, player, replace(enemy, defense=defense)) is safe
    assert damage_division_safe(70, replace(player, attack=255), replace(enemy, defense=defense))


def test_special_moves_use_special_stats_and_explosion_has_its_own_clamp():
    player, enemy = matchup()
    assert damage_division_safe(94, player, replace(enemy, special=3))
    assert not damage_division_safe(94, replace(player, special=324), replace(enemy, special=3))
    assert damage_division_safe(153, player, enemy)
    assert damage_division_safe(45, player, enemy)
    assert [slot for _, slot in ranked_moves(player, enemy)] == [1]


@pytest.mark.parametrize('can_switch', [True, False])
def test_choose_safe_partner_instead_of_strength_or_explosion(can_switch):
    player, enemy = matchup()
    partner = mon(species=131, level=100, hp=387, max_hp=387, special=350,
                  moves=(94, 0, 0, 0), pp=(20, 0, 0, 0))
    state = snap(party=(player, partner), in_battle=1, owned=frozenset({19}))
    decision = choose_battle(state, player, enemy, 0, can_switch=can_switch)
    assert (decision.kind, decision.index) == ('switch', 1)


def test_only_unsafe_attacks_escape_wild_battle():
    player, enemy = matchup()
    player = replace(player, pp=(10, 0, 15, 4))
    state = snap(party=(player,), in_battle=1, owned=frozenset({19}))
    assert choose_battle(state, player, enemy, 0).kind == 'run'


def test_move_menu_rechecks_stale_strength_intent():
    player, enemy = matchup()
    player = replace(player, moves=(89, 94, 88, 70))
    memory = menu({13: '      EARTHQUAKE', 14: '      PSYCHIC', 15: '      ROCK THROW',
                   16: '      STRENGTH'}, (5, 16), 4, (5, 12))
    battler(memory, W_BATTLE_MON, player)
    battler(memory, W_ENEMY_MON, enemy)
    state = snap(party=(player,), in_battle=1, enemy_species=165, enemy_level=2)
    policy = StrategicPolicy(1)
    policy.intent = Decision('fight', 3)
    actions = policy._dispatch(state, Screen(memory), 'moves', memory)
    assert actions[0].button == 'up'
    assert policy.reason == 'Use PSYCHIC_M'
