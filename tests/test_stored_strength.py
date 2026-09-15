import pytest

from pokesim.pokemon import stored_strength
from pokesim.web.pokedex import live_status


def pikachu(**changes):
    return {'species': 0x54, 'level': 50, 'dvs': [15] * 5, 'stat_exp': [0] * 5, **changes}


def test_current_level_stats_and_total_match_gen_one_values():
    result = stored_strength(pikachu())
    assert result == {'calculated_stats': {'HP': 110, 'Attack': 75, 'Defense': 50,
                                         'Speed': 110, 'Special': 70}, 'power': 415}
    assert stored_strength(pikachu(level=100, stat_exp=[65535] * 5)) == {
        'calculated_stats': {'HP': 273, 'Attack': 208, 'Defense': 158, 'Speed': 278, 'Special': 198},
        'power': 1115}


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
    assert stored_strength(pikachu(**changes)) == {'calculated_stats': None, 'power': None}


def test_storage_api_enriches_all_boxes_without_mutating_snapshot():
    pokemon = [pikachu(box=1, position=1), pikachu(box=12, position=20, level=100)]
    result = live_status({'storage': {'pokemon': pokemon, 'active_box': 1}})
    rows = result['storage']['pokemon']
    assert [row['power'] for row in rows] == [415, 800]
    assert rows[1]['box'] == 12 and rows[1]['position'] == 20
    assert all('power' not in row for row in pokemon)
