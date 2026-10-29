"""The shared cost model gives Gold, Silver and Crystal the same search costs they had before it moved."""
import itertools

import pytest

from pokesim.gen2 import standdown
from pokesim.planning import cost


def former_search_expected(chance, maps=0, odds=1.0):
    """gen2/standdown.py search_expected before it moved to planning/cost.py."""
    battles = 1 / (min(100, max(1, chance)) / 100 * odds)
    return maps * 150 + battles * 75


def test_gen2_search_expected_returns_what_it_did():
    assert standdown.search_expected is cost.search_expected
    assert (standdown.DECISIONS_PER_BATTLE, standdown.DECISIONS_PER_MAP) == (75, 150)
    for chance, maps, odds in itertools.product((0, 0.5, 1, 5, 10, 30, 50, 70, 90, 100, 150), (0, 1, 3, 12),
                                                (1.0, 0.75, 0.5, 0.1, 1 / 3)):
        assert cost.search_expected(chance, maps, odds) == former_search_expected(chance, maps, odds)
        assert cost.search_expected(chance, maps=maps, odds=odds) == former_search_expected(chance, maps, odds)
    assert cost.search_expected(10) == former_search_expected(10)


def test_a_search_can_need_several_catches_and_count_in_frames():
    assert cost.search_expected(20, needed=3) == pytest.approx(3 * cost.search_expected(20))
    assert cost.search_expected(50, maps=2, per_map=1000, per_battle=600) == 2 * 1000 + 2 * 600


def test_slot_chance_adds_the_shares_of_every_slot_holding_the_species():
    slots = ((3, 'PIDGEY'), (3, 'RATTATA'), (4, 'PIDGEY'))
    assert cost.slot_chance(slots, 'PIDGEY', (2, 1, 1)) == 75
    assert cost.slot_chance(slots, 'ZUBAT', (2, 1, 1)) == 0
