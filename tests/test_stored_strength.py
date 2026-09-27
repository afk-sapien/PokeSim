import pytest

from pokesim.pokemon import SPECIES, stored_strength
from pokesim.web.pokedex import live_status


def pikachu(**changes):
    return {'species': 0x54, 'level': 50, 'dvs': [15] * 5, 'stat_exp': [0] * 5, **changes}


def test_current_level_stats_and_total_match_gen_one_values():
    result = stored_strength(pikachu())
    assert result == {'calculated_stats': {'HP': 110, 'Attack': 75, 'Defense': 50,
                                         'Speed': 110, 'Special': 70}, 'stat_total': 415, 'power': 144}
    assert stored_strength(pikachu(level=100, stat_exp=[65535] * 5)) == {
        'calculated_stats': {'HP': 273, 'Attack': 208, 'Defense': 158, 'Speed': 278, 'Special': 198},
        'stat_total': 1115, 'power': 1400}


def test_stat_experience_rounding_matches_cartridge_at_square_boundaries():
    # ceil(sqrt(10)) / 4 gives the first bonus point, floor(sqrt(10)) would miss it.
    for exp, expected in ((0, 145), (9, 145), (10, 146), (16, 146), (17, 146),
                          (65025, 208), (65535, 208)):
        assert stored_strength(pikachu(level=100, stat_exp=[exp] * 5))['calculated_stats']['Attack'] == expected


def test_species_level_dvs_and_training_each_change_power():
    baseline = stored_strength(pikachu(dvs=[0] * 5))['power']
    assert stored_strength(pikachu())['power'] > baseline
    assert stored_strength(pikachu(dvs=[0] * 5, level=60))['power'] > baseline
    assert stored_strength(pikachu(dvs=[0] * 5, stat_exp=[65535] * 5))['power'] > baseline
    assert stored_strength(pikachu(dvs=[0] * 5, species=0x83))['power'] > baseline  # Mewtwo
    assert stored_strength(pikachu(hp=0, status=64)) == stored_strength(pikachu())


@pytest.mark.parametrize('changes', [
    {'dvs': []}, {'dvs': None}, {'dvs': [16] * 5}, {'dvs': [True] * 5},
    {'stat_exp': []}, {'stat_exp': [-1] * 5}, {'stat_exp': [65536] * 5},
    {'stat_exp': [1.5] * 5}, {'level': 0}, {'level': 101}, {'level': None}, {'species': 0},
])
def test_unknown_or_invalid_data_is_unavailable(changes):
    assert stored_strength(pikachu(**changes)) == {'calculated_stats': None, 'stat_total': None, 'power': None}


def test_storage_api_enriches_all_boxes_without_mutating_snapshot():
    pokemon = [pikachu(box=1, position=1), pikachu(box=12, position=20, level=100)]
    result = live_status({'storage': {'pokemon': pokemon, 'active_box': 1}})
    rows = result['storage']['pokemon']
    assert [row['power'] for row in rows] == [144, 623]
    assert rows[1]['box'] == 12 and rows[1]['position'] == 20
    assert all('power' not in row for row in pokemon)


def test_party_and_box_use_identical_unboosted_strength_despite_damage():
    mon = pikachu(name='Pikachu', nick='ACE', hp=1, max_hp=110, status_label='Paralyzed',
                  experience={'total': 125000}, stats={'Attack': 999, 'Speed': 1})
    result = live_status({'party': [mon], 'storage': {'pokemon': [pikachu()]}})
    party = result['party'][0]
    boxed = result['storage']['pokemon'][0]
    assert party['power'] == boxed['power'] == 144
    assert party['calculated_stats'] == boxed['calculated_stats']
    assert party['slot'] == 1 and party['experience'] == 125000
    assert mon['hp'] == 1 and mon['stats']['Attack'] == 999


def species_strength(name, **changes):
    species = next(key for key, row in SPECIES.items() if row['name'] == name)
    return stored_strength(pikachu(species=species, level=100, stat_exp=[65535] * 5, **changes))


def test_equal_training_ranks_mewtwo_then_birds_and_dragonite_across_all_species():
    ranked = sorted(SPECIES.values(), key=lambda row: species_strength(row['name'])['power'], reverse=True)
    assert ranked[0]['name'] == 'MEWTWO'
    assert {row['name'] for row in ranked[1:5]} == {'ZAPDOS', 'MOLTRES', 'ARTICUNO', 'DRAGONITE'}
    assert species_strength('CLOYSTER')['power'] < species_strength('ARTICUNO')['power']
    assert species_strength('CHANSEY')['power'] < species_strength('MEWTWO')['power']


def test_blue_collection_defense_outlier_no_longer_outranks_legendary_birds():
    # These individuals reproduce the reported ranking at level 100 and full training.
    individuals = {'MEWTWO': [10, 13, 4, 11, 12], 'CLOYSTER': [13, 15, 9, 14, 13],
                   'ZAPDOS': [3, 8, 0, 11, 15], 'MOLTRES': [0, 10, 4, 0, 14],
                   'ARTICUNO': [5, 2, 3, 12, 1]}
    scores = {name: species_strength(name, dvs=dvs) for name, dvs in individuals.items()}
    assert scores['CLOYSTER']['stat_total'] > scores['ZAPDOS']['stat_total']
    assert [scores[name]['power'] for name in individuals] == [4575, 2614, 3291, 3196, 2998]
    assert sorted(scores, key=lambda name: scores[name]['power'], reverse=True) == [
        'MEWTWO', 'ZAPDOS', 'MOLTRES', 'ARTICUNO', 'CLOYSTER']


def test_power_rewards_training_and_level_without_using_moves_or_current_condition():
    base = pikachu(dvs=[0] * 5)
    for level in range(2, 101):
        assert stored_strength({**base, 'level': level})['power'] >= stored_strength({**base, 'level': level - 1})['power']
    for index in range(5):
        training = [0] * 5
        training[index] = 65535
        assert stored_strength({**base, 'stat_exp': training})['power'] > stored_strength(base)['power']
        dvs = [0] * 5
        dvs[index] = 15
        assert stored_strength({**base, 'dvs': dvs})['power'] > stored_strength(base)['power']
    assert stored_strength({**base, 'moves': [1], 'pp': [0], 'hp': 0, 'status': 64}) == stored_strength(base)
