"""A ledge jump in progress is not a missing route.

In a Gen II ledge jump the coordinates read the wall tile jumped over until the player lands. That tile
is in no region, so the regions found no route from it, and the walk recorded a missing route on the
goal and looked around for 150 decisions. On the gold/new_game ladder rung this happened on Route 29
on the way to Mr. Pokémon, and on silver/badges_6 the waiting Lake of Rage goal left the bot pacing
inside the Olivine Mart door.
"""
from types import SimpleNamespace

from pokesim.gen2.policy import Goal, Policy
from pokesim.gen2.routes import Regions

ROUTE = 1


def route_with_a_ledge():
    """A route row with a left ledge at (3, 1) that jumps over the wall at (2, 1) to land on (1, 1)."""
    maps = {
        ROUTE: {'width': 6, 'height': 3, 'constant': 'ROUTE_29',
                'collision': [7, 7, 7, 7, 7, 7,
                              0, 0, 7, 0xA1, 0, 0,
                              7, 7, 7, 7, 7, 7],
                'connections': [], 'objects': [], 'warps': []},
    }
    permissions = [0] * 256
    permissions[7] = 15
    return SimpleNamespace(maps=maps, permissions=permissions, map_ids={'ROUTE_29': ROUTE})


def walk_to(x, y):
    """A policy walking to (x, y) on the route with no path this turn, and the explore steps it takes."""
    data = route_with_a_ledge()
    policy = Policy.__new__(Policy)
    policy.data = data
    explored = []
    policy.nav = SimpleNamespace(regions=Regions(data),
                                 explore=lambda snapshot, memory, surf=False: explored.append(1) or ['up'])
    policy.walk = lambda snapshot, memory, path: SimpleNamespace(button=path[0])
    policy.goal = Goal('mystery_egg', 'Visit Mr. Pokémon', 'ROUTE_29', x, y)
    policy.collection, policy.monitor_tables, policy.decisions, policy.clock = {}, {}, 100, 100
    policy.stranded = policy.unreachable_waits = 0
    policy.failure, policy.recoveries = None, 0
    return policy, explored


def at(x, y):
    return SimpleNamespace(map=ROUTE, map_name='Route 29', x=x, y=y, objects=(), badges=0, party=[])


def test_a_player_mid_jump_looks_around_instead_of_recording_a_missing_route():
    policy, explored = walk_to(0, 1)
    action = policy.follow(at(2, 1), None, None, False, False)
    assert action.button == 'up' and explored == [1]
    assert policy.stranded == 1
    assert not policy.no_route_waiting(policy.goal)


def test_a_route_the_regions_rule_out_is_still_recorded_at_once():
    # The ledge only goes left, so nothing on its left side reaches the right side.
    policy, explored = walk_to(5, 1)
    action = policy.follow(at(0, 1), None, None, False, False)
    assert action.button is None and explored == []
    assert policy.no_route_waiting(policy.goal)
