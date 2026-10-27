"""A goal with no walking route either finds a way round or is reported, never bounced on forever."""
from types import SimpleNamespace

from pokesim.gen2 import flight
from pokesim.gen2.policy import Goal, Policy

ROUTE_36, OLIVINE = 36, 99


def policy_with(toward, goal):
    policy = Policy.__new__(Policy)
    policy.data = SimpleNamespace(map_ids={'ROUTE_36': ROUTE_36})
    policy.nav = SimpleNamespace(toward=toward, explore=lambda snapshot, memory, surf=False: ['up'])
    policy.goal = goal
    policy.stranded, policy.unreachable_waits = 0, 0
    policy.walk = lambda snapshot, memory, path: SimpleNamespace(button=path[0])
    return policy


def where(**events):
    return SimpleNamespace(map=1, map_name='Route 23', event=lambda name: events.get(name, False))


def test_a_door_bounce_does_not_restart_the_stranded_count_and_the_policy_reports_it():
    """A Crystal run spent 11 hours on Route 23. The stranded search walked into the Indigo Plateau door,
    walking back out counted as progress, and the count never reached its limit."""
    policy = policy_with(lambda *args, **kwargs: None, Goal('olivine', 'Travel to Olivine', 'OLIVINE_CITY', 5, 6))
    failures = []
    policy.fail = failures.append
    for _ in range(Policy.STRANDED_LIMIT - 1):
        # Outside: no route and no waypoint, so the search explores into the door.
        assert policy.follow(where(), None, None, False, False).button == 'up'
        # Inside: the only path leads back out to a waypoint.
        assert policy.follow(where(), None, ['down'], True, False).button == 'down'
    assert not failures
    policy.follow(where(), None, None, False, False)
    assert failures == ['no route to Travel to Olivine from Route 23']


def test_a_real_route_still_restarts_the_count():
    policy = policy_with(lambda *args, **kwargs: None, Goal('olivine', 'Travel to Olivine', 'OLIVINE_CITY', 5, 6))
    policy.stranded = 10
    assert policy.follow(where(), None, ['left'], False, False).button == 'left'
    assert policy.stranded == 0
    # Standing on a waypoint that Fly did not leave from counts as stranded.
    policy.fail = lambda reason: None
    policy.follow(where(), None, [], True, False)
    assert policy.stranded == 1


def test_a_returned_sudowoodo_is_battled_when_nothing_else_reaches_the_goal(monkeypatch):
    monkeypatch.setattr(flight, 'outside', lambda *args: None)
    goal = Goal('olivine', 'Travel to Olivine', 'OLIVINE_CITY', 5, 6)
    policy = policy_with(lambda snapshot, map_id, targets, memory, surf=False:
                         ['right'] if (map_id, targets) == (ROUTE_36, [(35, 10)]) else None, goal)
    returned = where(EVENT_FOUGHT_SUDOWOODO=True)
    assert policy.detour(returned, None, None, OLIVINE, False) == (['right'], False)
    assert policy.goal.key == 'sudowoodo' and (policy.goal.map_name, policy.goal.x, policy.goal.y) == ('ROUTE_36', 35, 10)
    # Before the story battle, or once it is gone again, the tree is left alone.
    for snapshot in (where(), where(EVENT_FOUGHT_SUDOWOODO=True, EVENT_ROUTE_36_SUDOWOODO=True)):
        policy.goal = goal
        assert policy.detour(snapshot, None, None, OLIVINE, False) == (None, False)
        assert policy.goal is goal


def test_a_waypoint_comes_before_the_tree(monkeypatch):
    monkeypatch.setattr(flight, 'outside', lambda *args: (27, (5, 5)))
    goal = Goal('olivine', 'Travel to Olivine', 'OLIVINE_CITY', 5, 6)
    policy = policy_with(lambda snapshot, map_id, targets, memory, surf=False: ['left'], goal)
    assert policy.detour(where(EVENT_FOUGHT_SUDOWOODO=True), None, None, OLIVINE, False) == (['left'], True)
    assert policy.goal is goal
