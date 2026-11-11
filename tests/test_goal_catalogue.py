"""The goal catalogue (docs/design/typed-goals.md section 4): what a director can ask for, read only.

Serving the catalogue draws no random numbers and writes no state, so a run that serves it plays the
same game as one that does not. Cost and worth are the prices the planners' own candidates carry.
"""
import os
import random
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pokesim import config
from pokesim.gen2 import collection as ladder_module
from pokesim.gen2.collection import ERRAND_FRAMES, GOAL_PARAM, RUNGS
from pokesim.gen2.policy import Policy
from pokesim.gen2.standdown import rung_key, stand_down
from pokesim.planning import arbiter, catalogue, decide, values
from pokesim.planning.arbiter import Candidate, Tier
from pokesim.planning.monitor import Monitor
from pokesim.policies import kinds
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.web.app import create_app
from test_next_activity import PLAN, full_postgame, gen2_goal, gen2_policy, postgame, weigh

REPLAY_FRAMES = 20000
READ_EVERY = 1000


def test_reading_why_a_goal_waits_writes_nothing():
    state = {}
    monitor = Monitor(state)
    assert monitor.failure('hunt', 0) is None and state == {}
    monitor.stand_down('hunt', 0, failure=decide.STUCK.kind)
    saved = deepcopy(state)
    assert monitor.failure('hunt', 1) == decide.STUCK.kind and state == saved
    assert monitor.failure('hunt', 10 ** 12) is None and state == saved


def test_the_body_finds_goals_by_name_keeps_the_first_and_says_why_it_is_empty():
    rows = [catalogue.goal('a', 'grass', {'species': 35}, 'Catch Clefairy', Tier.PROGRESS, cost=120.25, worth=1),
            catalogue.goal('b', 'fish', {}, 'Catch Magikarp', failure=decide.Failure(decide.NEEDS, 'a rod'),
                           cost=float('inf'))]
    assert rows[0]['tier'] == 'progress' and rows[0]['feasible'] and rows[0]['why_not'] is None
    assert (rows[0]['cost'], rows[0]['worth']) == (120.25, 1)
    assert rows[1]['why_not'] == {'kind': 'needs', 'detail': 'a rod'} and not rows[1]['feasible']
    assert rows[1]['tier'] is None and rows[1]['cost'] is None and rows[1]['worth'] is None
    every = catalogue.body(1, [], rows, None)
    assert every == {'generation': 1, 'kinds': [], 'goals': rows, 'pin': None, 'reason': None}
    assert catalogue.body(1, [], rows, None, query=' MAGIKARP ')['goals'] == rows[1:]
    assert catalogue.body(1, [], rows, None, limit=1)['goals'] == rows[:1]
    assert catalogue.body(1, [], rows, None, query='Mew') == {**every, 'goals': [], 'reason': 'No goal matches that name'}
    assert catalogue.body(2, [], [], None, 'Finish the story first')['reason'] == 'Finish the story first'


@pytest.mark.parametrize('make', [postgame, full_postgame], ids=['postgame', 'full'])
def test_gen1_serving_the_catalogue_draws_no_numbers_and_writes_nothing(make):
    c, s, nav = make()
    goals, _ = c.goal_list(s, nav, random.Random(3))
    c.set_pin(s, nav, random.Random(3), goals[-1]['key'])
    rng = random.Random(3)
    before, saved, tables, pinned = rng.getstate(), deepcopy(c.state_dict()), deepcopy(dict(c.director.progress)), c.pin.to_dict()
    rows, reason = c.catalogue(s, nav, rng)
    assert reason is None and rows
    assert rng.getstate() == before and c.state_dict() == saved and dict(c.director.progress) == tables
    assert c.pin.to_dict() == pinned and c.project is None


def test_gen1_the_catalogue_prices_the_draws_goals_and_says_why_the_rest_wait():
    c, s, nav = postgame()
    drawn, *place = postgame()
    ranked = arbiter.rank(drawn.offers(*place, random.Random(3))[0])
    stuck = ranked[0].key
    c.director.monitor.stand_down(stuck, c.clock, failure=decide.STUCK.kind)
    rows, reason = c.catalogue(s, nav, random.Random(3))
    open_now = [row for row in rows if row['feasible']]
    assert reason is None and rows[:len(open_now)] == open_now
    # The goals the draw ranks come first in its order, each with the price its candidate carries.
    assert [row['key'] for row in open_now] == [option.key for option in ranked[1:]]
    for row, option in zip(open_now, ranked[1:]):
        assert row['tier'] == catalogue.tier_name(option.tier)
        assert (row['cost'], row['worth']) == (round(option.expected_frames, 3), round(option.value, 3))
    waiting = {row['key']: row for row in rows[len(open_now):]}
    assert len(waiting) == len(rows) - len(open_now)
    assert waiting[stuck]['why_not'] == {'kind': 'stuck', 'detail': 'it stopped moving'}
    assert {row['why_not']['kind'] for row in waiting.values()} >= {'stuck', 'no_route', 'needs', 'not_now'}
    assert all(row['why_not']['detail'] for row in waiting.values())


def test_gen1_the_policy_serves_every_kind_and_finds_goals_by_name():
    c, s, nav = postgame()
    owner = SimpleNamespace(collection=c, nav=nav, rng=random.Random(3))
    body = StrategicPolicy.catalogue(owner, s, 'rattata', 5)
    assert body['generation'] == 1 and body['reason'] is None and body['pin'] is None
    assert [row['kind'] for row in body['kinds']] == list(kinds.RULES)
    assert all(row['about'] and isinstance(row['params'], list) for row in body['kinds'])
    assert 0 < len(body['goals']) <= 5 and all('rattata' in row['title'].lower() for row in body['goals'])
    assert StrategicPolicy.catalogue(owner, None)['reason'] == 'Not available now'


def test_gen2_the_catalogue_lists_the_offers_then_the_rungs_left_out_and_changes_nothing(monkeypatch):
    owner = gen2_policy(pin=None, rng=random.Random(5))
    stand_down(owner, rung_key('tower'), failure=decide.STUCK.kind)
    owner.no_route_waiting = lambda goal: goal.key == 'league'
    before, tables = owner.rng.getstate(), deepcopy(owner.monitor_tables)
    priced = {offer.key: offer for offer in weigh(gen2_policy(pin=None)).candidates}

    def journey(policy, snapshot, mem, Goal):
        rungs = weigh(policy)
        rungs.offer('tower', Tier.FILLER, values.SMALL, ERRAND_FRAMES, lambda: gen2_goal('tower'))
        policy.collection['target'] = 'changed'
        policy.rng.random()
        policy.ladder_offers, policy.ladder_labels = rungs.candidates, rungs.labels
        policy.ladder_skipped = rungs.skipped
    monkeypatch.setattr(ladder_module, 'journey', journey)
    rows, reason = ladder_module.catalogue(owner, SimpleNamespace(map=1), None, None)
    hunt = priced['hunt:hunt']
    assert reason is None and rows == [
        catalogue.goal('hunt:hunt', 'hunt', {'goal': 'hunt'}, 'Label hunt', hunt.tier, None, hunt.expected_frames,
                       hunt.value),
        catalogue.goal('league:league', 'league', {'goal': 'league'}, 'Label league', failure=decide.NO_ROUTE),
        catalogue.goal('tower', 'tower', {'goal': None}, RUNGS['tower'].capitalize(), failure=decide.STUCK)]
    assert owner.collection == {'target': None} and owner.rng.getstate() == before
    assert owner.monitor_tables == tables and not hasattr(owner, 'ladder_offers')
    owner.completed = {}
    assert ladder_module.catalogue(owner, None, None, None) == ([], 'Finish the story first')


def test_gen2_the_policy_serves_every_rung_as_a_kind():
    body = Policy.catalogue(SimpleNamespace(memory=None, pin=None), None)
    assert body['generation'] == 2 and body['goals'] == [] and body['reason'] == 'Not available now'
    name, type_, about = GOAL_PARAM
    assert body['kinds'] == [{'kind': rung, 'about': words, 'params': [{'name': name, 'type': type_, 'about': about}]}
                             for rung, words in RUNGS.items()]


def offer(source, goal, key, tier, **extra):
    return decide.Offer(source, goal, Candidate(key, tier, 1.0, 100.0, goal=extra.pop('kind', None)), **extra)


def test_both_generations_record_the_running_goal_the_same_way():
    heal = Goal('heal', 'Heal the party', 'Low HP')
    gen1 = SimpleNamespace(goal=None, goal_offer=None, collection=SimpleNamespace(project=None, project_key=None))
    assert StrategicPolicy.goal_record(gen1) is None
    gen1.goal = heal
    plain = {'key': 'heal', 'kind': None, 'title': 'Heal the party', 'tier': None, 'done': False, 'stop': None,
             'parked': None}
    assert StrategicPolicy.goal_record(gen1) == plain
    gen1.goal_offer = offer('heal', heal, 'heal', Tier.UPKEEP, parked=decide.NO_ROUTE)
    assert StrategicPolicy.goal_record(gen1) == {**plain, 'kind': 'heal', 'tier': 'upkeep',
                                                 'parked': {'kind': 'no_route', 'detail': 'no route'}}
    # An offer counts only while its goal still runs.
    gen1.goal = PLAN
    assert StrategicPolicy.goal_record(gen1)['tier'] is None
    # A collection goal is known by its project.
    gen1.goal_offer = offer('collection', PLAN, 'collection', Tier.PROGRESS, kind='collection')
    gen1.collection = SimpleNamespace(project={'method': 'grass'}, project_key='4:grass:59:')
    assert StrategicPolicy.goal_record(gen1) == {**plain, 'key': '4:grass:59:', 'kind': 'grass', 'title': 'Plan',
                                                 'tier': 'progress'}
    goal = gen2_goal('hunt')
    gen2 = SimpleNamespace(goal=goal, goal_offer=offer('collection', goal, 'hunt:hunt', Tier.PROGRESS, kind='hunt'))
    assert Policy.goal_record(gen2) == {'key': 'hunt', 'kind': 'hunt', 'title': 'Label hunt', 'tier': 'progress',
                                        'done': False, 'stop': None, 'parked': None}
    gen2.goal = gen2_goal('league')
    assert Policy.goal_record(gen2)['kind'] is None
    assert set(Policy.goal_record(gen2)) == set(plain)


class Game:
    """A worker's emulator as the catalogue route sees it."""

    def __init__(self):
        self.asked = []
        self.busy = False

    def call(self, function, timeout=None):
        if self.busy:
            raise TimeoutError('The game is busy')
        return function()

    def catalogue(self, query=None, limit=None):
        self.asked.append((query, limit))
        rows = [catalogue.goal('4:grass:59:', 'grass', {'species': 35, 'map': 59}, 'Catch Clefairy', Tier.PROGRESS,
                               cost=900, worth=1)]
        return catalogue.body(1, [catalogue.kind('grass', 'catch a species in the grass')], rows, None, None, query,
                              limit)

    def status(self):
        return {'strategy': {}}


@pytest.fixture
def web(tmp_path, monkeypatch):
    from pokesim.store import Store
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    store = Store(tmp_path)
    game = Game()
    with TestClient(create_app(game, store)) as client:
        yield client, game
    store.close()


def test_web_anyone_who_can_watch_reads_the_catalogue(web):
    client, game = web
    body = client.get('/api/catalogue').json()
    assert body['generation'] == 1 and body['goals'][0]['key'] == '4:grass:59:' and body['reason'] is None
    assert game.asked == [(None, catalogue.LIMIT)]
    long = 'Clefairy ' * 10
    assert client.get('/api/catalogue', params={'q': f'  {long}', 'limit': 3}).status_code == 200
    assert game.asked[-1] == (long.strip()[:40], 3)
    assert client.get('/api/catalogue', params={'limit': 0}).status_code == 422
    assert client.get('/api/catalogue', params={'limit': catalogue.LIMIT + 1}).status_code == 422
    game.busy = True
    assert client.get('/api/catalogue').status_code == 409


def post_game(generation):
    """A post-game checkpoint from the private ladder, where the catalogue lists goals, and its cartridge."""
    pytest.importorskip('pyboy_rs')
    ladder = Path(os.environ.get('DATA_DIR', 'data')) / 'ladder'
    if generation == 1:
        rom, checkpoint = Path(os.environ.get('ROM_PATH', 'roms/pokered.gb')), ladder / 'red' / 'post_game' / 'start.state'
    else:
        if not os.environ.get('GEN2_DATA_DIR'):
            pytest.skip('Set GEN2_DATA_DIR for a Crystal run')
        rom = Path(os.environ.get('GEN2_CARTRIDGE_DIR', 'roms')) / 'crystal.gbc'
        checkpoint = ladder / 'crystal' / 'post_game' / 'start.state'
    if not rom.exists() or not checkpoint.exists():
        pytest.skip('Needs the cartridge and the private post-game checkpoint')
    return rom, checkpoint


def play(generation, rom, checkpoint, folder, read):
    """Play ``REPLAY_FRAMES`` from ``checkpoint``, serving the catalogue every ``READ_EVERY`` frames when
    ``read``. Gives the trace head, the frame, the policy's save and tables, and the catalogues served."""
    if generation == 1:
        from pokesim.headless import HeadlessRun
        from pokesim.ram import read_snapshot
        run = HeadlessRun(rom, checkpoint, seed=7, trace=folder)
        snapshot = lambda: read_snapshot(run.pb.memory, run.frame)  # noqa: E731
    else:
        from pokesim.gen2.headless import HeadlessRun
        run = HeadlessRun(rom, checkpoint, seed=7, trace=folder, data_root=os.environ['GEN2_DATA_DIR'])
        snapshot = run.read
    served = []
    try:
        assert run.tracer.recording
        end, due = run.frame + REPLAY_FRAMES, run.frame
        while run.frame < end:
            now = snapshot()
            if read and run.frame >= due:
                served.append(run.policy.catalogue(now))
                due = run.frame + READ_EVERY
            run.step(now)
        return (run.tracer.recorder.head, run.frame, run.policy.state_dict(), deepcopy(dict(run.policy.monitor_tables)),
                served)
    finally:
        run.stop()


@pytest.mark.parametrize('generation', [1, 2], ids=['gen1', 'gen2'])
def test_a_run_that_serves_the_catalogue_plays_the_same_game(generation, tmp_path):
    rom, checkpoint = post_game(generation)
    plain = play(generation, rom, checkpoint, tmp_path / 'plain', read=False)
    read = play(generation, rom, checkpoint, tmp_path / 'read', read=True)
    assert plain[0] and read[:4] == plain[:4]
    served = read[4]
    assert len(served) >= REPLAY_FRAMES // READ_EVERY // 2 and any(body['goals'] for body in served)
