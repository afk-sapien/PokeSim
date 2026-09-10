from collections import Counter

from pokesim.policies.navigation import Navigator
from pokesim.strategy_data import MAPS


def test_many_candidate_goals_share_search_and_preserve_active_route(monkeypatch):
    nav = Navigator()
    expanded = Counter()

    def neighbors(pos, frame):
        expanded[pos] += 1
        if pos < 200:
            yield 'right', pos + 1
        if pos:
            yield 'left', pos - 1

    monkeypatch.setattr(nav, 'neighbors', neighbors)
    nav.path.append((0, 'right', 1))
    nav.target = frozenset({1})
    distance_to = nav.distance_lookup(0, 0)
    assert distance_to([]) is None
    for target in range(1, 201):
        assert distance_to([target]) == target
    assert distance_to([999]) is None
    assert distance_to([150, 3]) == 3
    assert distance_to([0]) == 0
    assert sum(expanded.values()) == 201
    assert max(expanded.values()) == 1
    assert list(nav.path) == [(0, 'right', 1)]
    assert nav.target == frozenset({1})


def test_search_budget_applies_to_all_queries_together(monkeypatch):
    nav = Navigator()
    expanded = []

    def neighbors(pos, frame):
        expanded.append(pos)
        yield 'right', pos + 1

    monkeypatch.setattr(nav, 'neighbors', neighbors)
    distance_to = nav.distance_lookup(0, 0, limit=5)
    assert distance_to([3]) == 3
    assert distance_to([100]) is None
    assert distance_to([200]) is None
    assert distance_to([5]) == 5
    assert expanded == list(range(5))


def test_distance_queries_follow_directed_edges_and_current_blocks():
    nav = Navigator()
    nav.use_world = False
    a, b, c = (1, 0, 0), (1, 1, 0), (1, 2, 0)
    nav.edges = {a: {'right': b}, b: {'right': c}}
    nav.blocked[(b, 'right')] = 100
    assert nav.distance_lookup(a, 50)([c]) is None
    assert nav.distance_lookup(a, 100)([c]) == 2
    assert nav.distance_lookup(c, 100)([a]) is None
    nav.story_blocks.add(c)
    assert nav.distance_lookup(a, 100)([c]) is None


def test_distances_match_individual_routes_through_real_doors():
    start = (MAPS['REDS_HOUSE_2F'], 3, 6)
    nav = Navigator()
    distance_to = nav.distance_lookup(start, 0)
    for goal in [(MAPS['PALLET_TOWN'], 10, 1), (MAPS['VIRIDIAN_MART'], 2, 5)]:
        reference = Navigator()
        assert reference.route(start, [goal], 0) is not None
        assert distance_to([goal]) == len(reference.path)


def test_postgame_collection_does_not_repeat_whole_world_routes(monkeypatch):
    import random
    from pokesim.policies.collection import Collection
    from pokesim.policies.progression import Goal
    from test_collection import state
    from test_strategy import mon

    collection = Collection()
    collection.completed_champion = True
    s = state(map=MAPS['VIRIDIAN_POKECENTER'], x=3, y=3, badges=255,
              party=(mon(level=60, hp=100, max_hp=100, moves=(15, 57, 70, 33)),))
    nav = Navigator()
    nav.update_story(s)
    neighbors = nav.neighbors
    expanded = Counter()

    def counted(pos, frame):
        expanded[pos] += 1
        yield from neighbors(pos, frame)

    def repeated_route(*args):
        raise AssertionError('Candidate selection must share its route search')

    monkeypatch.setattr(nav, 'neighbors', counted)
    monkeypatch.setattr(nav, 'route', repeated_route)
    collection.choose(s, nav, random.Random(7), Goal('champion', 'Champion', 'Explore'))
    assert collection.project is not None
    assert len(expanded) > 100
    assert max(expanded.values()) == 1
