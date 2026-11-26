"""Gen II battle and Battle Tower move scores follow the cartridge's rules for moves without plain power.

Dream Eater lands only on a sleeping foe and Snore only from a sleeping user, Return and Frustration
take their power from friendship, Hidden Power its type and power from the DVs, and a one-hit
knockout fails on a higher-level foe. Counter and Mirror Coat deal nothing of their own.
"""
from types import SimpleNamespace

import pytest

from pokecore.gen2.battle_power import hidden_power, move_power
from pokesim.gen2.policy import Policy
from pokesim.gen2.tower import attack_value

TYPES = {'NORMAL': 0, 'FIGHTING': 1, 'FLYING': 2, 'POISON': 3, 'GROUND': 4, 'ROCK': 5, 'BUG': 7,
         'GHOST': 8, 'STEEL': 9, 'FIRE': 20, 'WATER': 21, 'GRASS': 22, 'ELECTRIC': 23,
         'PSYCHIC_TYPE': 24, 'ICE': 25, 'DRAGON': 26, 'DARK': 27}
GUILLOTINE, HORN_DRILL, SEISMIC_TOSS, HYPER_BEAM, DIG, COUNTER, DREAM_EATER = 12, 32, 69, 63, 91, 68, 138
PSYWAVE, EXPLOSION, SNORE, RETURN, FRUSTRATION, MAGNITUDE, HIDDEN_POWER, MIRROR_COAT = 149, 153, 173, 216, 218, 222, 237, 243
# Plain hits with the power the moves above should score with.
NORMAL_102, GROUND_71, NORMAL_150, NORMAL_250 = 900, 901, 902, 903
SNORLAX, GENGAR, UMBREON = 143, 94, 197


def move(name, effect, power, kind, accuracy=100):
    return {'name': name.title(), 'constant': name, 'effect': effect, 'power': power,
            'type': TYPES[kind], 'accuracy': accuracy}


DATA = SimpleNamespace(
    types=TYPES,
    species={SNORLAX: {'types': [0, 0], 'stats': [160, 110, 65, 30, 65, 110]},
             GENGAR: {'types': [8, 3], 'stats': [60, 65, 60, 110, 130, 75]},
             UMBREON: {'types': [27, 27], 'stats': [95, 65, 110, 65, 60, 130]}},
    moves={GUILLOTINE: move('GUILLOTINE', 'EFFECT_OHKO', 0, 'NORMAL', 30),
           HORN_DRILL: move('HORN_DRILL', 'EFFECT_OHKO', 1, 'NORMAL', 30),
           SEISMIC_TOSS: move('SEISMIC_TOSS', 'EFFECT_LEVEL_DAMAGE', 1, 'FIGHTING'),
           HYPER_BEAM: move('HYPER_BEAM', 'EFFECT_HYPER_BEAM', 150, 'NORMAL', 90),
           DIG: move('DIG', 'EFFECT_FLY', 60, 'GROUND'),
           COUNTER: move('COUNTER', 'EFFECT_COUNTER', 1, 'FIGHTING'),
           MIRROR_COAT: move('MIRROR_COAT', 'EFFECT_MIRROR_COAT', 1, 'PSYCHIC_TYPE'),
           DREAM_EATER: move('DREAM_EATER', 'EFFECT_DREAM_EATER', 100, 'PSYCHIC_TYPE'),
           PSYWAVE: move('PSYWAVE', 'EFFECT_PSYWAVE', 1, 'PSYCHIC_TYPE', 80),
           EXPLOSION: move('EXPLOSION', 'EFFECT_SELFDESTRUCT', 250, 'NORMAL'),
           SNORE: move('SNORE', 'EFFECT_SNORE', 40, 'NORMAL'),
           RETURN: move('RETURN', 'EFFECT_RETURN', 1, 'NORMAL'),
           FRUSTRATION: move('FRUSTRATION', 'EFFECT_FRUSTRATION', 1, 'NORMAL'),
           MAGNITUDE: move('MAGNITUDE', 'EFFECT_MAGNITUDE', 1, 'GROUND'),
           HIDDEN_POWER: move('HIDDEN_POWER', 'EFFECT_HIDDEN_POWER', 1, 'NORMAL'),
           NORMAL_102: move('NORMAL_102', 'EFFECT_NORMAL_HIT', 102, 'NORMAL'),
           GROUND_71: move('GROUND_71', 'EFFECT_NORMAL_HIT', 71, 'GROUND'),
           NORMAL_150: move('NORMAL_150', 'EFFECT_NORMAL_HIT', 150, 'NORMAL', 90),
           NORMAL_250: move('NORMAL_250', 'EFFECT_NORMAL_HIT', 250, 'NORMAL')},
    matchups={(0, 8): 0, (1, 8): 0, (24, 27): 0, (8, 8): 2})
# DVs whose Hidden Power is a power 70 Ghost attack.
GHOST_DVS = (0, 13, 14, 15, 15)


def user(**fields):
    return SimpleNamespace(**{'species': SNORLAX, 'level': 50, 'stats': (220, 130, 90, 50, 90, 130),
                              'status': 0, 'friendship': 70, **fields})


def target(**fields):
    return SimpleNamespace(**{'enemy_species': SNORLAX, 'enemy_level': 50, 'enemy_hp': 200,
                              'enemy_defense': 100, 'enemy_special_defense': 100, 'enemy_status': 0, **fields})


def score(mid, mon=None, foe=None):
    return Policy.move_score(SimpleNamespace(data=DATA), mid, mon or user(), foe or target())


def test_dream_eater_needs_a_sleeping_foe():
    assert score(DREAM_EATER) == 0
    assert score(DREAM_EATER, foe=target(enemy_status=2)) > 0
    assert score(DREAM_EATER, foe=target(enemy_species=UMBREON, enemy_status=2)) == 0


def test_snore_needs_a_sleeping_user():
    assert score(SNORE) == 0
    assert score(SNORE, mon=user(status=1)) > 0


def test_return_and_frustration_take_their_power_from_friendship():
    assert move_power(DATA, DATA.moves[RETURN], None, 255) == (0, 102)
    assert move_power(DATA, DATA.moves[RETURN], None, 0) == (0, 1)
    assert move_power(DATA, DATA.moves[FRUSTRATION], None, 0) == (0, 102)
    assert move_power(DATA, DATA.moves[FRUSTRATION], None, 70) == (0, 74)
    assert score(RETURN, mon=user(friendship=255)) == score(FRUSTRATION, mon=user(friendship=0)) == score(NORMAL_102)
    # An opponent's Pokémon battles with the friendship of 70 the cartridge gives it.
    foe = SimpleNamespace(species=SNORLAX, level=50, stats=(220, 130, 90, 50, 90, 130))
    assert score(RETURN, mon=foe) == score(RETURN) > 0


def test_hidden_power_takes_its_type_and_power_from_the_dvs():
    assert hidden_power(DATA, GHOST_DVS) == (8, 70)
    assert move_power(DATA, DATA.moves[HIDDEN_POWER], GHOST_DVS, 70) == (8, 70)
    gengar = target(enemy_species=GENGAR)
    assert score(HIDDEN_POWER, mon=user(dvs=GHOST_DVS), foe=gengar) > 0
    # Without DVs it keeps its listed Normal type, which Gengar is immune to.
    assert score(HIDDEN_POWER, foe=gengar) == 0


def test_magnitude_scores_its_average_power():
    assert score(MAGNITUDE) == score(GROUND_71) > 0


def test_psywave_deals_three_quarters_of_the_level_on_average():
    assert score(PSYWAVE) == pytest.approx(50 * 0.75 * 0.8)
    assert score(PSYWAVE, foe=target(enemy_species=UMBREON)) == 0


def test_a_one_hit_knockout_needs_a_foe_no_higher_in_level():
    # Guillotine lists no power, and each level the foe is lower adds 2 in 255 to its 30% accuracy.
    assert score(GUILLOTINE, foe=target(enemy_level=40)) == pytest.approx(200 * (76 + 20) / 255)
    assert score(HORN_DRILL, foe=target(enemy_level=40)) == score(GUILLOTINE, foe=target(enemy_level=40))
    assert score(GUILLOTINE, foe=target(enemy_level=51)) == 0
    assert score(HORN_DRILL, foe=target(enemy_species=GENGAR, enemy_level=40)) == 0


def test_counter_and_mirror_coat_deal_nothing_of_their_own():
    assert score(COUNTER) == score(MIRROR_COAT) == 0


def test_hyper_beam_is_halved_unless_it_knocks_out():
    assert score(HYPER_BEAM, foe=target(enemy_hp=1000)) == pytest.approx(score(NORMAL_150, foe=target(enemy_hp=1000)) / 2)
    assert score(HYPER_BEAM, foe=target(enemy_hp=1)) == score(NORMAL_150, foe=target(enemy_hp=1))


def test_explosion_halves_the_foes_defense():
    assert score(NORMAL_250) < score(EXPLOSION) * 10 < 2 * score(NORMAL_250)


def test_the_tower_scorer_uses_the_same_rules():
    mon = user(friendship=255)
    # Attack 130 over level 50 for each point of power, STAB 1.5 for Normal and accuracy.
    assert attack_value(DATA, mon, HYPER_BEAM) == pytest.approx(150 * 2.6 * 1.5 * 0.9 * 0.6)
    assert attack_value(DATA, mon, DIG) == pytest.approx(60 * 2.6 * 0.6)
    assert attack_value(DATA, mon, RETURN) == pytest.approx(102 * 2.6 * 1.5)
    assert attack_value(DATA, mon, EXPLOSION) == pytest.approx(250 * 2.6 * 1.5 * 0.1)
    # A move that ignores the stats scores its damage to a 3L + 10 HP foe, so Seismic Toss scores 250.
    assert attack_value(DATA, mon, SEISMIC_TOSS) == pytest.approx(250)
    assert attack_value(DATA, mon, GUILLOTINE) == pytest.approx(160 * 250 / 50 * 0.3)
    assert attack_value(DATA, mon, DREAM_EATER) == attack_value(DATA, mon, SNORE) == attack_value(DATA, mon, COUNTER) == 0
