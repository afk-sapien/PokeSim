"""Gen II Battle Power is rated from the adventure's own cartridge data."""
import os
import pytest

from pokesim.gen2.battle_power import battle_power, hidden_power
from pokesim.gen2.web import live_status
from pokesim.statistics import highlights

TYPES = {'NORMAL': 0, 'FIGHTING': 1, 'FLYING': 2, 'POISON': 3, 'GROUND': 4, 'ROCK': 5, 'BUG': 7,
         'GHOST': 8, 'STEEL': 9, 'FIRE': 20, 'WATER': 21, 'GRASS': 22, 'ELECTRIC': 23,
         'PSYCHIC_TYPE': 24, 'ICE': 25, 'DRAGON': 26, 'DARK': 27}


def move(name, effect, power, kind, accuracy=100):
    return {'name': name.title(), 'constant': name, 'effect': effect, 'power': power,
            'type': TYPES[kind], 'accuracy': accuracy}


class Data:
    """Hashable by identity like the real GameData."""
    def __init__(self, **fields):
        self.__dict__.update(fields)


DATA = Data(
    types=TYPES,
    species={154: {'dex': 154, 'name': 'Meganium', 'stats': [80, 82, 100, 80, 83, 100], 'types': [22, 22]},
             208: {'dex': 208, 'name': 'Steelix', 'stats': [75, 85, 200, 30, 55, 65], 'types': [9, 4]},
             19: {'dex': 19, 'name': 'Rattata', 'stats': [30, 56, 35, 72, 25, 35], 'types': [0, 0]}},
    moves={33: move('TACKLE', 'EFFECT_NORMAL_HIT', 35, 'NORMAL', 95),
           76: move('SOLARBEAM', 'EFFECT_SOLARBEAM', 120, 'GRASS'),
           75: move('RAZOR_LEAF', 'EFFECT_NORMAL_HIT', 55, 'GRASS', 95),
           231: move('IRON_TAIL', 'EFFECT_DEFENSE_DOWN_HIT', 100, 'STEEL', 75),
           237: move('HIDDEN_POWER', 'EFFECT_HIDDEN_POWER', 1, 'NORMAL'),
           235: move('SYNTHESIS', 'EFFECT_SYNTHESIS', 0, 'GRASS'),
           68: move('COUNTER', 'EFFECT_COUNTER', 1, 'FIGHTING')},
    matchups={(22, 22): 0.5, (22, 21): 2, (22, 9): 0.5, (22, 4): 2, (0, 8): 0, (0, 9): 0.5,
              (9, 9): 0.5, (9, 5): 2, (9, 25): 2, (20, 22): 2, (20, 9): 2})


def meganium(**changes):
    return {'species': 154, 'level': 100, 'dvs': [5, 4, 11, 12, 5], 'stat_exp': [65535] * 5,
            'moves': [70, 15, 231, 76], 'friendship': 255, 'egg': False, **changes}


def test_live_status_rates_gen2_party_and_pc_with_cartridge_moves():
    # Strength and Cut are missing from this fixture's table, so they are unknown, not zero.
    party = meganium(moves=[33, 231, 76, 75])
    stored = {**party, 'box': 3, 'position': 1}
    game = {'party': [party], 'storage': {'pokemon': [stored]}, 'dex_owned': [154]}
    status = live_status(game, {}, data=DATA)
    value = battle_power(party, DATA)
    assert isinstance(value, int) and value > 0
    assert status['party'][0]['battle_power'] == value
    assert status['storage']['pokemon'][0]['battle_power'] == value
    assert live_status(game, {})['party'][0]['battle_power'] is None

    best = highlights(game, (lambda mon: battle_power(mon, DATA), lambda mon: None), DATA.species)
    assert best['battle']['value'] == value and best['battle']['dex'] == 154 and best['dvs'] is None


def test_gen2_power_ignores_condition_and_rejects_unknown_snapshots():
    base = meganium(moves=[33, 76, 0, 0])
    assert battle_power(base, DATA) == battle_power({**base, 'hp': 0, 'status': 8, 'pp': [0] * 4}, DATA)
    assert battle_power({**base, 'moves': [70]}, DATA) is None
    assert battle_power({**base, 'moves': None}, DATA) is None
    assert battle_power({**base, 'dvs': []}, DATA) is None
    assert battle_power({**base, 'egg': True}, DATA) is None
    assert battle_power({**base, 'species': 300}, DATA) is None
    assert battle_power({**base, 'moves': [0, 0, 0, 0]}, DATA) == 0
    assert battle_power({**base, 'moves': [68]}, DATA) == 0


def test_gen2_power_uses_split_specials_coverage_and_recovery():
    solar = meganium(moves=[76])
    assert battle_power(meganium(moves=[76, 231]), DATA) > battle_power(solar, DATA)
    assert battle_power(meganium(moves=[76, 235]), DATA) > battle_power(solar, DATA)
    assert battle_power(meganium(moves=[75]), DATA) > battle_power(solar, DATA)  # No charging turn.
    # Gen II splits Special: Special Attack drives Solarbeam but not Tackle.
    boosted = Data(**{**vars(DATA), 'species': {
        **DATA.species, 154: {**DATA.species[154], 'stats': [80, 82, 100, 80, 140, 100]}}})
    assert battle_power(solar, boosted) > battle_power(solar, DATA)
    tackle = meganium(moves=[33])
    assert battle_power(tackle, boosted) == battle_power(tackle, DATA)


def test_hidden_power_follows_the_dvs():
    assert hidden_power(DATA, (15, 15, 15, 15, 15)) == (TYPES['DARK'], 70)
    assert hidden_power(DATA, (0, 12, 12, 0, 0)) == (TYPES['FIGHTING'], 31 + 5 * 12 // 2)
    fire = meganium(moves=[237], dvs=[0, 10, 0, 0, 0])
    assert hidden_power(DATA, fire['dvs'])[0] == TYPES['FIRE']
    assert battle_power(fire, DATA) > 0


@pytest.mark.parametrize('version', ['gold', 'silver', 'crystal'])
def test_real_gen2_data_rates_every_species(version):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    data = GameData.load(directory, version)
    for species, row in data.species.items():
        moves = [mid for _, mid in row['learnset']][-4:]
        mon = {'species': species, 'level': 50, 'dvs': [15] * 5, 'stat_exp': [0] * 5, 'moves': moves}
        assert battle_power(mon, data) is not None, row['name']
    starter = {'species': 154, 'level': 100, 'dvs': [5, 4, 11, 12, 5], 'stat_exp': [65535] * 5,
               'moves': [70, 15, 231, 76], 'friendship': 255}
    assert battle_power(starter, data) > 1000
