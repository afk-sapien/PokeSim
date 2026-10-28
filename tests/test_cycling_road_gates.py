"""The Cycling Road gates turn back a player without a Bicycle, so navigation does not route through them."""
from pokesim.policies.navigation import CYCLING_ROAD_CHECKS, Navigator
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap

GATE = MAPS['ROUTE_18_GATE_1F']


def test_without_a_bicycle_the_guards_close_the_cycling_road_gates():
    """A Red run with no Bicycle paced Route 18 Gate 1F on its way to Route 16 Gate 2F until the
    explore project gave up, as the guard walked it back from each of these tiles."""
    nav = Navigator()
    nav.update_story(snap(map=GATE, badges=255))
    for name, coords in CYCLING_ROAD_CHECKS:
        assert all((MAPS[name], x, y) in nav.story_blocks for x, y in coords)
    assert all(target != (GATE, 4, 4) for _, target in nav.neighbors((GATE, 5, 4), 0))
    nav.update_story(snap(map=GATE, badges=255, items=((ITEMS['BICYCLE'], 1),)))
    assert not any(m in {MAPS['ROUTE_16_GATE_1F'], GATE} for m, _, _ in nav.story_blocks)
