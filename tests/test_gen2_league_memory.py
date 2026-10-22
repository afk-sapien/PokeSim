"""League families do not keep a Gen I worker's discarded copies of the Gen II data (issue #111)."""
import gc
import weakref

from pokesim.gen2 import league


class GameData:
    def __init__(self, species):
        self.species = species


def game_data():
    return GameData({
        1: {'name': 'Pichu', 'evolutions': [{'species': 2}]},
        2: {'name': 'Pikachu', 'evolutions': [{'species': 3}]},
        3: {'name': 'Raichu', 'evolutions': []},
    })


def test_a_family_names_every_stage_from_the_root():
    assert league.family(game_data(), 3) == (1, {'PICHU', 'PIKACHU', 'RAICHU'})


def test_each_trade_s_copy_of_the_data_is_freed_after_use():
    copies = []
    for _ in range(5):
        data = game_data()
        league.family(data, 3)
        copies.append(weakref.ref(data))
    del data
    gc.collect()
    assert [copy() for copy in copies] == [None] * 5
