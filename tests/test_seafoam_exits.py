from pokesim.policies.navigation import Navigator, SEAFOAM_HOLES
from pokesim.policies.progression import healing_goal
from pokesim.strategy_data import MAPS
from test_events import snap
from test_strategy import mon


def test_remembered_cross_floor_fall_cannot_replace_a_ladder_route():
    nav = Navigator()
    source = (MAPS['SEAFOAM_ISLANDS_B1F'], 18, 7)
    landing = (MAPS['SEAFOAM_ISLANDS_B2F'], 19, 7)
    nav.load_state_dict({'edges': [[list(source), 'up', list(landing)]]})
    nav.update_story(snap(map=source[0]))
    assert ('up', landing) not in nav.neighbors(source, 0)


def test_routine_navigation_never_steps_into_a_seafoam_hole():
    nav = Navigator()
    nav.update_story(snap())
    for hole in SEAFOAM_HOLES:
        source = (hole[0], hole[1], hole[2] + 1)
        nav.edges[source] = {'up': hole}
        assert all(target != hole for direction, target in nav.neighbors(source, 0))
    assert len(SEAFOAM_HOLES) == 8


def test_deep_seafoam_has_a_route_to_healing_without_falling():
    s = snap(map=MAPS['SEAFOAM_ISLANDS_B4F'], x=16, y=7, badges=255,
             party=(mon(moves=(57, 70, 15, 0)),))
    nav = Navigator()
    nav.update_story(s)
    assert nav.route((s.map, s.x, s.y), healing_goal(s).targets, 0) is not None
    assert all(target not in SEAFOAM_HOLES for _, _, target in nav.path)
    assert nav.path[-1][2] in healing_goal(s).targets
