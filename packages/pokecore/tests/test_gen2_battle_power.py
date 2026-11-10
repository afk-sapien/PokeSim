"""Gen II Battle Power is rated from consumer game tables. These tables are synthetic."""
from types import SimpleNamespace

from pokecore.gen2 import (ancestors, battle_power, branch_parents, hidden_power, level_credit, live_status,
                               offspring, retrieval_cost)

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


FAMILY = Data(species={
    25: {'egg_groups': ['GROUND', 'FAIRY'], 'evolutions': [{'species': 26}], 'growth': 'MEDIUM_FAST'},
    26: {'egg_groups': ['GROUND', 'FAIRY'], 'evolutions': [], 'growth': 'MEDIUM_FAST'},
    172: {'egg_groups': ['NONE'], 'evolutions': [{'species': 25}], 'growth': 'MEDIUM_FAST'},
    29: {'egg_groups': ['MONSTER', 'GROUND'], 'evolutions': [{'species': 30}], 'growth': 'MEDIUM_SLOW'},
    30: {'egg_groups': ['NONE'], 'evolutions': [], 'growth': 'MEDIUM_SLOW'},
    132: {'egg_groups': ['DITTO'], 'evolutions': [], 'growth': 'MEDIUM_FAST'},
    236: {'egg_groups': ['NONE'], 'evolutions': [{'species': 106}, {'species': 107}, {'species': 237}],
          'growth': 'MEDIUM_FAST', 'stats': [35, 35, 35, 35, 35, 35]},
    106: {'egg_groups': ['HUMANSHAPE'], 'evolutions': [], 'growth': 'MEDIUM_FAST'},
    107: {'egg_groups': ['HUMANSHAPE'], 'evolutions': [], 'growth': 'MEDIUM_FAST'},
    237: {'egg_groups': ['HUMANSHAPE'], 'evolutions': [], 'growth': 'MEDIUM_FAST'}})


def parent(species, gender, defense=2, special=4, **fields):
    return SimpleNamespace(**{'species': species, 'gender': gender, 'egg': False, 'dvs': (0, 8, defense, 8, special),
                              'level': 10, 'experience': 1000, 'stat_exp': (0,) * 5, **fields})


def test_offspring_follows_the_day_care_rules():
    ditto = parent(132, 'Genderless', 3, 3)
    assert offspring(FAMILY, ditto, parent(26, 'Male')) == {172}
    assert offspring(FAMILY, parent(26, 'Female'), parent(25, 'Male', 5, 5)) == {172}
    assert not offspring(FAMILY, parent(26, 'Female'), parent(25, 'Female', 5, 5))
    assert not offspring(FAMILY, parent(26, 'Female'), parent(25, 'Male'))
    assert not offspring(FAMILY, ditto, parent(132, 'Genderless'))
    assert not offspring(FAMILY, ditto, parent(30, 'Female'))
    assert not offspring(FAMILY, ditto, parent(25, 'Male', 3, 11))
    assert not offspring(FAMILY, ditto, parent(25, 'Male', egg=True))
    assert offspring(FAMILY, ditto, parent(29, 'Female')) == {29, 32}


def test_retrieval_cost_and_tyrogue_branches():
    grown = parent(25, 'Male', level=5, experience=10 ** 3)
    assert retrieval_cost(FAMILY, SimpleNamespace(daycare=(grown, None))) == 600
    assert retrieval_cost(FAMILY, SimpleNamespace(daycare=(None, None))) == 0
    strong = parent(236, 'Male', level=19, dvs=(0, 15, 0, 0, 0))
    snapshot = SimpleNamespace(party=(strong,), stored=())
    assert branch_parents(FAMILY, snapshot, 236, {106})
    assert not branch_parents(FAMILY, snapshot, 236, {106, 107})
    assert branch_parents(FAMILY, SimpleNamespace(party=(parent(25, 'Male'),), stored=()), 25, {26})


def test_level_credit_reaches_whole_lines():
    assert ancestors(FAMILY, 26) == {26, 25, 172}
    assert level_credit(FAMILY, 26) == {26, 25, 172}
    assert level_credit(FAMILY, 25) == {25}
