"""Saved navigation stays small to parse, and older saves still load (issue #111)."""
import json

from pokesim.policies.navigation import Navigator
from pokesim.strategy_data import MAPS


def _learned():
    nav = Navigator()
    town = MAPS['PALLET_TOWN']
    nav.load_state_dict({'edges': [[[town, x, 5], 'right', [town, x + 1, 5]] for x in range(2, 9)]
                         + [[[town, 4, 5], 'down', [town, 4, 6]]],
                         'visits': [[[town, x, 5], 300 + x] for x in range(2, 10)]})
    return nav


def test_saved_navigation_round_trips_without_one_list_per_tile():
    nav = _learned()
    saved = json.loads(json.dumps(nav.state_dict()))
    # Two flat lists of integers, however many tiles were learned.
    assert set(saved) == {'visit_cells', 'edge_cells'}
    assert all(type(value) is int for cells in saved.values() for value in cells)
    again = Navigator()
    again.load_state_dict(saved)
    assert again.edges == nav.edges and again.visits == nav.visits


def test_older_nested_saves_still_load():
    nav = _learned()
    town = MAPS['PALLET_TOWN']
    assert nav.edges[(town, 4, 5)] == {'right': (town, 5, 5), 'down': (town, 4, 6)}
    assert nav.visits[(town, 9, 5)] == 309
