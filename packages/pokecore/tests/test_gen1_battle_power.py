import pytest

from pokecore import dvs
from pokecore.gen1_battle_power import BattlePower, Battler, calculated_stat, stat_exp_bonus, stored_strength

# Synthetic tables in the documented shapes. They are not cartridge data.
SPECIES = {1: {'stats': [50, 60, 40, 70, 55], 'types': [0, 0]},
           2: {'stats': [80, 40, 90, 30, 70], 'types': [21, 21]}}
MOVES = {1: {'name': 'TACKLE', 'power': 40, 'type': 0, 'accuracy': 100, 'effect': 'NO_ADDITIONAL_EFFECT'},
         2: {'name': 'SPLASHY', 'power': 80, 'type': 21, 'accuracy': 90, 'effect': 'NO_ADDITIONAL_EFFECT'},
         3: {'name': 'SEISMIC_TOSS', 'power': 1, 'type': 1, 'accuracy': 100, 'effect': 'SPECIAL_DAMAGE_EFFECT'},
         4: {'name': 'GROWL', 'power': 0, 'type': 0, 'accuracy': 100, 'effect': 'ATTACK_DOWN1_EFFECT'},
         5: {'name': 'SLEEPY', 'power': 0, 'type': 0, 'accuracy': 75, 'effect': 'SLEEP_EFFECT'}}
MATCHUPS = {(21, 0): 2.0, (0, 21): 0.5}


def test_stat_formula_matches_cartridge_rounding():
    assert stat_exp_bonus(0) == 0
    assert stat_exp_bonus(1) == 0
    assert stat_exp_bonus(17) == 1
    assert stat_exp_bonus(65535) == 63
    assert calculated_stat(50, 100, 15, 65535, hp=True) == ((65 * 2 + 63) + 110)
    assert calculated_stat(255, 100, 15, 65535) == 608


def test_stored_strength_validates_and_scores():
    mon = {'species': 1, 'level': 50, 'dvs': [15, 15, 15, 15, 15], 'stat_exp': [0] * 5}
    result = stored_strength(mon, SPECIES)
    assert result['calculated_stats']['HP'] == (65 * 2) * 50 // 100 + 60
    assert result['stat_total'] == sum(result['calculated_stats'].values())
    assert result['power'] > 0
    assert stored_strength({**mon, 'dvs': [16] * 5}, SPECIES)['power'] is None
    assert stored_strength({**mon, 'species': 99}, SPECIES)['power'] is None


def test_battle_power_and_replacement():
    power = BattlePower(SPECIES, MOVES, MATCHUPS)
    mon = {'species': 1, 'level': 30, 'dvs': [8] * 5, 'stat_exp': [100] * 5, 'moves': [1, 4]}
    assert power.battle_power(mon) > 0
    assert power.battle_power({**mon, 'moves': [77]}) is None
    assert power.battle_power({**mon, 'moves': []}) is None
    battler = power.battler(mon)
    assert isinstance(battler, Battler) and battler.hp == battler.max_hp
    assert power.damage(3, battler, battler) == 30.0
    assert power.damage(4, battler, battler) == 0.0
    enemy = Battler(2, 50, 50, 30, types=(21, 21), defense=40, special=40)
    assert power.damage(1, battler, enemy) < power.damage(1, battler, Battler(1, 50, 50, 30, types=(0, 0),
                                                                              defense=40, special=40))
    assert power.best_replacement(battler, 2) in (0, 1)
    assert power.best_replacement(battler, 1) is None
    assert power.best_replacement(battler, 2, protected=(1, 4)) is None
    with_utility = power.moveset_score(battler, (1, 5))
    assert with_utility == pytest.approx(power.moveset_score(battler, (1,)) * 1.08)


def test_dv_flags():
    assert dvs.is_perfect({'dvs': [15] * 5})
    assert not dvs.is_perfect({'dvs': [15] * 4})
    assert dvs.is_shiny({'dvs': (0, 2, 10, 10, 10)})
    assert not dvs.is_shiny({'dvs': [0, 1, 10, 10, 10]})
    assert dvs.shiny_bytes(bytes([0x2a, 0xaa])) and dvs.shiny_bytes(bytes([0xfa, 0xaa]))
    assert not dvs.shiny_bytes(bytes([0x2b, 0xaa]))
