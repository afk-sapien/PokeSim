"""A wild Ditto that used Transform is still the Ditto the hunt came for."""
from pokesim.policies.battle import (TRANSFORMED, W_BATTLE_MON, W_ENEMY_MON, W_ENEMY_SPECIES2, W_ENEMY_STATUS3,
                                     choose_battle, read_battler)
from pokesim.ram import W_IS_IN_BATTLE, read_snapshot
from pokesim.strategy_data import ITEMS
from test_disabled_moves import battler
from test_events import snap
from test_scenarios import cartridge
from test_strategy import mon

DITTO, BULBASAUR = 0x4C, 0x99


def transformed(memory):
    me = mon()
    battler(memory, W_BATTLE_MON, me)
    # Transform copied the player's Bulbasaur over the foe, species included.
    battler(memory, W_ENEMY_MON, mon(level=26))
    memory[W_ENEMY_SPECIES2] = DITTO
    memory[W_ENEMY_STATUS3] = TRANSFORMED
    return me


def test_a_transformed_foe_reads_as_the_species_that_was_met():
    memory = bytearray(65536)
    transformed(memory)
    assert read_battler(memory, W_ENEMY_MON).species == DITTO
    memory[W_ENEMY_STATUS3] = 0
    assert read_battler(memory, W_ENEMY_MON).species == BULBASAUR


def test_the_snapshot_keeps_the_species_that_was_met():
    memory = cartridge()
    transformed(memory)
    memory[W_IS_IN_BATTLE] = 1
    assert read_snapshot(memory, 0).enemy_species == DITTO
    memory[W_ENEMY_STATUS3] = 0
    assert read_snapshot(memory, 0).enemy_species == BULBASAUR


def test_the_hunt_throws_at_a_missing_ditto_after_it_transforms():
    memory = bytearray(65536)
    me = transformed(memory)
    state = snap(party=(me,), in_battle=1, enemy_species=DITTO, enemy_level=26, items=((ITEMS['POKE_BALL'], 5),))
    decision = choose_battle(state, read_battler(memory, W_BATTLE_MON), read_battler(memory, W_ENEMY_MON), 0,
                             collect_missing=True)
    assert decision.kind != 'run', decision.reason
