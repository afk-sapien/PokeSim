"""Gold, Silver and Crystal run the Johto Marathon on the Kanto Marathon's engine."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2 import marathon, postgame
from pokesim.gen2.data import GameData
from pokesim.policies import marathon as engine


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def runner(**extra):
    fields = dict(species=157, nick='TYPHLOSION', trainer_id=1, dvs=(15,) * 5, hp=200, status=0, pp=(10, 10, 0, 0),
                  moves=(53, 15, 0, 0), egg=False, box=None, level=60)
    fields.update(extra)
    return SimpleNamespace(**fields)


def at(point, frame, *, flags=None, **extra):
    mid, x, y = point
    fields = dict(frame=frame, map=mid, x=x, y=y, in_battle=0, valid=True, party=(runner(),), badges=0xFFFF, can_catch=False,
                  event=lambda name: True if flags is None else name in flags)
    fields.update(extra)
    return SimpleNamespace(**fields)


def runner_policy(data, finished=4):
    policy = SimpleNamespace(data=data, collection={}, completed={'champion': 1, 'cut': 1, 'sudowoodo': 1},
                             menu=None, decisions=1000, no_room=lambda snapshot: False, memory=None, goal=None)
    postgame.state(policy)['finished'] = finished
    return policy


def clock():
    return SimpleNamespace(byte=lambda name: {'wTimeOfDay': 1}.get(name, 0), memory=None)


def start(policy, snapshot, monkeypatch):
    """Draw the rotation with nothing else on offer, so the marathon is picked."""
    from pokesim.gen2 import collection
    for name in ('quality', 'trainee', 'shiny'):
        monkeypatch.setattr(postgame, name, lambda *args: None)
    monkeypatch.setattr(collection, 'postgame_league', lambda *args: False)
    activity = postgame.choose(policy, snapshot, clock(), 'day')
    postgame.state(policy)['activity'] = activity
    return activity


def run_course(policy, points, frame, gap=600):
    for point in points:
        frame += gap
        postgame.observe(policy, at(point, frame))
    return frame


def test_every_leg_walks_both_ways_on_land(data):
    from pokesim.gen2.routes import Regions
    points = marathon.course(data).points
    assert len(points) == 11 and points[0] == points[-1]
    regions = Regions(data)
    legs = list(zip(points, points[1:]))
    for (a, b) in legs + [(b, a) for a, b in legs]:
        route = regions.route(SimpleNamespace(map=a[0], x=a[1], y=a[2]), b[0], [b[1:]], cut=True, surf=False)
        assert route is not None, (data.maps[a[0]]['constant'], data.maps[b[0]]['constant'])
    for mid, x, y in points:
        warps = {(warp['x'], warp['y'] + 1): data.maps[warp['map']]['constant'] for warp in data.maps[mid]['warps']}
        assert warps[(x, y)].endswith('POKECENTER_1F') or warps[(x, y)] == 'ELMS_LAB'


def test_both_courses_share_one_engine(data):
    johto = marathon.course(data)
    assert engine.KANTO.points == engine.COURSE and engine.KANTO.checkpoints == 11
    assert johto.name == 'Johto Marathon' and johto.checkpoints == 10 and johto.start == 'New Bark Town'
    assert engine.start_event(engine.KANTO)['title'] == 'The Kanto Marathon is on!'
    assert engine.start_event(johto)['title'] == 'The Johto Marathon is on!'
    assert johto.center(data.map_ids['GOLDENROD_POKECENTER_1F']) and not johto.center(data.map_ids['GOLDENROD_CITY'])


def test_entry_needs_champion_four_activities_cut_sudowoodo_and_the_cooldown(data):
    point = marathon.course(data).points[0]
    policy = runner_policy(data)
    assert marathon.eligible(policy, at(point, 1000), 4)
    assert not marathon.eligible(policy, at(point, 1000), 3)
    assert not marathon.eligible(policy, at(point, 1000, badges=0xFFFD), 4)
    assert not marathon.eligible(policy, at(point, 1000, party=(runner(moves=(53, 0, 0, 0)),)), 4)
    # A returned Sudowoodo stands on Route 36 again until its sprite is hidden.
    assert not marathon.eligible(policy, at(point, 1000, flags={'EVENT_FOUGHT_SUDOWOODO'}), 4)
    assert marathon.eligible(policy, at(point, 1000, flags={'EVENT_FOUGHT_SUDOWOODO', 'EVENT_ROUTE_36_SUDOWOODO'}), 4)
    champion = runner_policy(data)
    champion.completed = {'cut': 1}
    assert not marathon.eligible(champion, at(point, 1000), 4)
    marathon.records(policy)['next'] = 2000
    assert not marathon.eligible(policy, at(point, 1000), 4)


def test_older_saves_count_their_recent_activities_as_finished(data):
    policy = SimpleNamespace(data=data, collection={'postgame': {'activity': None, 'recent': ['league'] * 6,
                                                                 'searches': {}, 'shiny_break': 0, 'shiny_maps': []}})
    assert postgame.state(policy)['finished'] == 6
    postgame.state(policy)['activity'] = {'kind': 'league'}
    postgame.finish(policy)
    assert postgame.state(policy)['finished'] == 7


def test_a_full_race_is_timed_journaled_and_recorded(data, monkeypatch):
    from pokesim.gen2.policy import Goal
    points = marathon.course(data).points
    policy = runner_policy(data)
    away = at(points[3], 1000)
    activity = start(policy, away, monkeypatch)
    assert activity['kind'] == 'marathon'
    goal = postgame.step(policy, away, clock(), Goal, 'day')
    assert goal.key == 'collection_marathon' and goal.map_name == 'NEW_BARK_TOWN' and (goal.x, goal.y) == (6, 4)
    assert 'Head to New Bark Town' in goal.label
    frame = run_course(policy, points[:1], 1000)
    assert [event['title'] for event in marathon.take_events(policy)] == ['The Johto Marathon is on!']
    goal = postgame.step(policy, at(points[0], frame), clock(), Goal, 'day')
    assert goal.map_name == 'CHERRYGROVE_CITY' and 'Checkpoint 1 of 10' in goal.label
    shown = marathon.details(policy)
    assert shown['name'] == 'Johto Marathon' and shown['current']['started'] and shown['total_checkpoints'] == 10
    frame = run_course(policy, points[1:], frame)
    assert postgame.state(policy)['activity'] is None
    [finish] = marathon.take_events(policy)
    assert finish['title'] == 'Johto Marathon finished!' and finish['tags'] == 'runner'
    assert 'Finished in 1:40 game time. 10/10 checkpoints' in finish['body'] and 'First personal best!' in finish['body']
    records = marathon.records(policy)
    assert records['records']['completed'] == 1 and records['records']['best_frames'] == 10 * 600
    assert records['next'] == frame + engine.INTERVAL
    assert marathon.details(policy)['current'] is None
    # The six hour cooldown holds the next race back, then a faster one sets a new best.
    assert not marathon.eligible(policy, at(points[0], frame + engine.INTERVAL - 1), 4)
    policy.marathon_previous = None
    activity = start(policy, at(points[0], frame + engine.INTERVAL), monkeypatch)
    run_course(policy, points, frame + engine.INTERVAL, gap=300)
    [_, faster] = marathon.take_events(policy)
    assert 'New personal best, 0:50 faster!' in faster['body']
    assert marathon.records(policy)['records']['completed'] == 2


def test_a_race_ends_at_its_budget_or_two_idle_minutes_without_a_finish(data, monkeypatch):
    points = marathon.course(data).points
    policy = runner_policy(data)
    start(policy, at(points[0], 1000), monkeypatch)
    run_course(policy, points[:2], 1000)
    marathon.take_events(policy)
    # Standing still in battle is not idle time.
    for frame in range(2300, 2300 + 2 * engine.IDLE_LIMIT, 600):
        postgame.observe(policy, at(points[1], frame, in_battle=1))
    assert postgame.state(policy)['activity'] is not None
    # Nor is a menu the planner works through, such as a team change at a Pokémon Center.
    policy.menu = object()
    for frame in range(2300, 2300 + 2 * engine.IDLE_LIMIT, 600):
        postgame.observe(policy, at(points[1], frame))
    assert postgame.state(policy)['activity'] is not None
    policy.menu = None
    still = 2300 + 2 * engine.IDLE_LIMIT
    postgame.observe(policy, at(points[1], still))
    postgame.observe(policy, at(points[1], still + engine.IDLE_LIMIT))
    assert postgame.state(policy)['activity'] is None
    [stopped] = marathon.take_events(policy)
    assert stopped['title'] == 'Johto Marathon called off' and 'The finish line can wait.' in stopped['body']
    assert marathon.records(policy)['records'].get('completed') is None
    # A race that keeps moving still stops at its 50 minute budget.
    policy = runner_policy(data)
    policy.marathon_previous = None
    start(policy, at(points[0], 0), monkeypatch)
    frame = 0
    while postgame.state(policy)['activity'] is not None:
        frame += 600
        postgame.observe(policy, at(points[0], frame, x=points[0][1] + frame // 600 % 2))
    assert frame == engine.BUDGET
    assert marathon.take_events(policy)[-1]['title'] == 'Johto Marathon called off'


def test_healing_stops_and_battles_count_during_the_race(data, monkeypatch):
    points = marathon.course(data).points
    policy = runner_policy(data)
    start(policy, at(points[0], 0), monkeypatch)
    postgame.observe(policy, at(points[0], 60))
    center = (data.map_ids['CHERRYGROVE_POKECENTER_1F'], 5, 3)
    hurt = at(center, 120, party=(runner(hp=10),))
    for snapshot in (hurt, at(center, 150), at(center, 180)):
        postgame.observe(policy, snapshot)
    gains = postgame.state(policy)['activity']['gains']
    assert gains['healing_stops'] == 1 and gains['battles'] == 0
    # A battle counts once when it starts, however long it lasts.
    postgame.observe(policy, at(points[1], 200, in_battle=1))
    postgame.observe(policy, at(points[1], 260, in_battle=1))
    assert postgame.state(policy)['activity']['gains']['battles'] == 1
    postgame.observe(policy, at(points[1], 300))
    postgame.observe(policy, at(points[1], 360, in_battle=1))
    assert postgame.state(policy)['activity']['gains']['battles'] == 2


def test_the_runner_never_flies_or_surfs_past_the_starting_line(data, monkeypatch):
    from pokesim.gen2 import flight
    from pokesim.gen2.collection import arrive
    points = marathon.course(data).points
    policy = runner_policy(data)
    policy.goal = SimpleNamespace(key='collection_marathon')
    assert arrive(policy, SimpleNamespace()) == 'wait'
    # The untimed way to New Bark Town may fly or surf, since a player in Kanto has no other way.
    start(policy, at(points[3], 0), monkeypatch)
    assert not marathon.racing(policy)
    postgame.observe(policy, at(points[0], 60))
    assert marathon.racing(policy)
    source = open(flight.__file__.replace('flight.py', 'policy.py')).read()
    assert "running = self.goal.key == 'collection_marathon' and racing(self)" in source
    assert 'flight = None if running else shortcut(' in source and 'surf = not running and' in source
