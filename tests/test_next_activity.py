"""A manager sets the next activity from the planner's own goal list, for one run of it."""
import random
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from pokesim import config
from pokesim.emulator import Emulator
from pokesim.gen2 import collection as ladder_module
from pokesim.gen2.collection import ERRAND_FRAMES, Ladder, settle_pin
from pokesim.planning import values
from pokesim.planning.arbiter import Tier
from pokesim.planning.pin import Pin
from pokesim.play_clock import PlayClock
from pokesim.policies.collection import Collection
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import MAPS
from pokesim.web.app import create_app
from test_collection import state
from test_events import snap


def postgame():
    c = Collection()
    c.completed_champion = True
    s = state(map=MAPS['ROUTE_1'])
    nav = Navigator()
    nav.update_story(s)
    return c, s, nav


PLAN = Goal('collect_plan', 'Plan', 'Plan')


def test_gen1_a_pinned_goal_runs_next_and_clears_when_it_ends():
    c, s, nav = postgame()
    goals, reason = c.goal_list(s, nav, random.Random(3))
    assert reason is None and len(goals) > 1
    assert {'key', 'label', 'tier'} <= set(goals[0])
    last = goals[-1]
    assert c.set_pin(s, nav, random.Random(3), last['key']).label == last['label']
    c.choose(s, nav, random.Random(3), PLAN)
    assert c.project_key == last['key'] and c.pin.started
    c.abandon('The hunt ended')
    assert c.pin is None


def test_gen1_listing_the_goals_changes_nothing():
    c, s, nav = postgame()
    rng = random.Random(3)
    before = rng.getstate()
    c.goal_list(s, nav, rng)
    assert rng.getstate() == before and c.project is None and c.pin is None


def test_gen1_an_unknown_or_story_time_key_is_refused_and_changes_nothing():
    c, s, nav = postgame()
    with pytest.raises(ValueError, match='Not available now'):
        c.set_pin(s, nav, random.Random(3), 'no-such-goal')
    assert c.pin is None and c.project is None
    c.completed_champion = False
    goals, reason = c.goal_list(s, nav, random.Random(3))
    assert goals == [] and reason == 'The story comes first until the Champion is beaten'
    with pytest.raises(ValueError, match='The story comes first'):
        c.set_pin(s, nav, random.Random(3), 'no-such-goal')
    assert c.pin is None


def test_gen1_a_pin_that_drops_out_of_the_list_is_journaled():
    c, s, nav = postgame()
    c.pin = Pin('gone', 'Find Mew')
    c.choose(s, nav, random.Random(3), PLAN)
    assert c.pin is None
    [event] = c.take_activity_events()
    assert event.title == 'Gave up on Find Mew: not available now'


def pinned_emulator():
    emu = Emulator.__new__(Emulator)
    emu.policy = StrategicPolicy(7)
    emu.policy.collection.pin = Pin('hunt', 'Find Clefairy')
    emu.snapshot = snap(frame=1000)
    emu.journal = []
    emu._handle_events = lambda events, snapshot: emu.journal.extend(event.title for event in events)
    return emu


def test_gen1_a_stall_recovery_drops_the_pin(monkeypatch):
    emu = pinned_emulator()
    emu.last_reload, emu.stuck_since, emu.invalid_since, emu.battle_since, emu.input_epoch = 0, 1, None, None, 0
    emu._unstick = Mock()
    monkeypatch.setattr('pokesim.emulator.time.time', lambda: config.STUCK_RELOAD_SECONDS + 2)
    emu._check_guards()
    assert emu.policy.pin is None
    assert emu.journal == ['Gave up on Find Clefairy: stuck']


def test_gen1_an_unstick_drops_the_pin_before_it_reloads():
    emu = pinned_emulator()
    emu.store = Mock(autosaves=Mock(side_effect=RuntimeError('reload')))
    with pytest.raises(RuntimeError):
        emu._unstick(0, 'stuck')
    assert emu.policy.pin is None
    assert emu.journal == ['Gave up on Find Clefairy: stuck']


def test_gen1_loading_a_save_clears_the_pin(tmp_path, monkeypatch):
    from pokesim.store import Store
    path = tmp_path / 'checkpoint.state'
    path.write_bytes(b'checkpoint')
    emu = pinned_emulator()
    emu.pb = Mock()
    emu.store = Store(tmp_path)
    emu.input_epoch, emu.frame, emu.play_clock, emu.pending = 0, 900, PlayClock(), []
    monkeypatch.setattr('pokesim.emulator.read_snapshot', lambda memory, frame: snap(frame=900))
    emu._load_state_file(path)
    assert emu.policy.pin is None
    emu.store.close()


def gen2_policy(**extra):
    data = SimpleNamespace(map_ids={'HERE': 1})
    nav = SimpleNamespace(route=lambda source, target: [])
    return SimpleNamespace(data=data, nav=nav, collection={'target': None}, menu=None, completed={'red': 1},
                           decisions=10, **extra)


def gen2_goal(key):
    return SimpleNamespace(key=key, label=f'Label {key}', map_name='HERE', x=1, y=1, face=None)


def weigh(owner):
    rungs = Ladder(owner, SimpleNamespace(map=1))
    rungs.offer('hunt', Tier.PROGRESS, values.NEW_ENTRY, ERRAND_FRAMES, lambda: gen2_goal('hunt'))
    rungs.offer('league', Tier.FILLER, values.SMALL, ERRAND_FRAMES * 10, lambda: gen2_goal('league'))
    return rungs


def test_gen2_a_pinned_rung_is_asked_and_wins_but_not_over_upkeep():
    assert weigh(gen2_policy(pin=None)).rung == 'hunt'
    owner = gen2_policy(pin=Pin('league:league', 'Label league'))
    rungs = weigh(owner)
    assert rungs.rung == 'league' and 'league' in rungs.asked
    upkeep = Ladder(owner, SimpleNamespace(map=1))
    upkeep.offer('restock', Tier.UPKEEP, values.SMALL, ERRAND_FRAMES * 50, lambda: gen2_goal('restock'))
    upkeep.offer('league', Tier.FILLER, values.SMALL, ERRAND_FRAMES, lambda: gen2_goal('league'))
    assert upkeep.rung == 'restock' and 'league' in upkeep.asked


def test_gen2_a_pin_starts_when_picked_and_clears_when_its_run_ends():
    owner = gen2_policy(pin=Pin('league:league', 'Label league'))
    settle_pin(owner, weigh(owner))
    assert owner.pin.started
    rungs = Ladder(owner, SimpleNamespace(map=1))
    rungs.offer('hunt', Tier.PROGRESS, values.NEW_ENTRY, ERRAND_FRAMES, lambda: gen2_goal('hunt'))
    settle_pin(owner, rungs)
    assert owner.pin is None and not ladder_module.pin_events(owner)


def test_gen2_a_pin_whose_rung_offers_something_else_is_dropped_and_journaled():
    owner = gen2_policy(pin=Pin('league:league', 'Label league'))
    rungs = Ladder(owner, SimpleNamespace(map=1))
    rungs.offer('league', Tier.FILLER, values.SMALL, ERRAND_FRAMES, lambda: None)
    settle_pin(owner, rungs)
    assert owner.pin is None
    assert [row['title'] for row in owner.pin_events] == ['Gave up on Label league: not available now']


def test_gen2_a_survey_lists_the_rungs_and_changes_nothing(monkeypatch):
    owner = gen2_policy(pin=None, rng=random.Random(5))
    before = owner.rng.getstate()

    def journey(policy, snapshot, mem, Goal):
        rungs = weigh(policy)
        policy.collection['target'] = 'changed'
        policy.rng.random()
        ladder_module.pin_events(policy).append({'title': 'noise'})
        policy.ladder_offers, policy.ladder_labels = rungs.candidates, rungs.labels
    monkeypatch.setattr(ladder_module, 'journey', journey)
    goals, reason = ladder_module.goal_list(owner, SimpleNamespace(map=1), None, None)
    assert reason is None
    assert goals == [{'key': 'hunt:hunt', 'label': 'Label hunt', 'tier': 'progress'},
                     {'key': 'league:league', 'label': 'Label league', 'tier': 'filler'}]
    assert owner.collection == {'target': None} and owner.rng.getstate() == before
    assert owner.pin_events == [] and not hasattr(owner, 'ladder_offers')


def test_gen2_refuses_before_red_and_an_unknown_key_with_a_reason():
    from pokesim.gen2.policy import Policy
    assert ladder_module.goal_list(SimpleNamespace(completed={}), None, None, None) == ([], 'Finish the story first')
    owner = SimpleNamespace(pin=None, goals=lambda snapshot: ([], 'Finish the story first'))
    with pytest.raises(ValueError, match='Finish the story first'):
        Policy.pin_goal(owner, None, 'hunt:hunt')
    owner.goals = lambda snapshot: ([{'key': 'hunt:hunt', 'label': 'Label hunt', 'tier': 'progress'}], None)
    with pytest.raises(ValueError, match='Not available now'):
        Policy.pin_goal(owner, None, 'league:league')
    assert owner.pin is None
    assert Policy.pin_goal(owner, None, 'hunt:hunt').label == 'Label hunt'


def test_gen2_an_unstick_drops_the_pin_and_journals_it():
    from pokesim.gen2.emulator import MAX_RELOADS, Emulator as Gen2
    from pokesim.gen2.policy import Policy
    journal = []
    run = SimpleNamespace(pin=Pin('hunt:hunt', 'Label hunt'))
    run.drop_pin = lambda: Policy.drop_pin(run)
    emu = SimpleNamespace(policy=run, snapshot=SimpleNamespace(), unstick_streak=MAX_RELOADS, reloads_exhausted=True,
                          _reset_watch=lambda: None, _event=lambda event, snapshot: journal.append(event.title))
    Gen2._unstick(emu, 0, 'stuck')
    assert run.pin is None and journal == ['Gave up on Label hunt: stuck']


def test_gen2_loading_a_save_clears_the_pin(tmp_path, monkeypatch):
    from pokecore.emulator_state import checkpoint_metadata
    from pokesim.gen2 import emulator as module
    from pokesim.gen2.policy import Policy
    from pokesim.store import Store
    import io
    monkeypatch.setattr(module, 'read_snapshot', lambda *args: None)
    monkeypatch.setattr(module, 'open_state', lambda path: io.BytesIO(b'state'))
    emu = module.Emulator.__new__(module.Emulator)
    emu.store, emu.pb, emu.rom_sha1, emu.data = Store(tmp_path), Mock(), 'rom', None
    emu._sync_clock = Mock()
    seen = []
    run = SimpleNamespace(pin=Pin('hunt:hunt', 'Label hunt'), on_restore=lambda: None,
                          load_state_dict=lambda saved: seen.append(run.pin))
    run.unpin_goal = lambda: Policy.unpin_goal(run)
    emu.policy, emu.play_clock, emu.audio, emu._reset_watch, emu._publish_frame = run, Mock(), Mock(), Mock(), Mock()
    emu.statistics = SimpleNamespace(previous=None)
    emu.history = {}
    lock = {'base': 1_700_000_000.0, 'offset': 0.0, 'frames': 12, 'follow_frames': True}
    metadata = {**checkpoint_metadata(rtc_clock=lock), 'generation': 2, 'rom_sha1': 'rom', 'frame': 9,
                'policy_state': {}, 'run_memory': {}}
    emu._load_state_file(emu.store.write_checkpoint(b'state', metadata))
    assert run.pin is None and seen == [None]
    emu.store.close()


class Game:
    """A worker's emulator as the web routes see it."""

    def __init__(self):
        self.pin = None

    def call(self, function, timeout=None):
        return function()

    def goals(self):
        goals = [{'key': 'hunt', 'label': 'Find Clefairy', 'tier': 'progress'}]
        return {'goals': goals, 'pin': self.pin}

    def pin_goal(self, key):
        if key != 'hunt':
            raise ValueError('Not available now')
        self.pin = {'key': key, 'label': 'Find Clefairy', 'started': False}
        return self.pin

    def unpin_goal(self):
        self.pin = None

    def status(self):
        return {'strategy': {'pin': self.pin}}


@pytest.fixture
def web(tmp_path, monkeypatch):
    from pokesim.store import Store
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    store = Store(tmp_path)
    game = Game()
    with TestClient(create_app(game, store)) as client:
        yield client, game
    store.close()


def test_web_lists_goals_and_pins_and_unpins(web):
    client, game = web
    listing = client.get('/api/goals').json()
    assert listing == {'goals': [{'key': 'hunt', 'label': 'Find Clefairy', 'tier': 'progress'}], 'pin': None}
    response = client.post('/api/control', json={'action': 'pin_goal', 'value': 'hunt'})
    assert response.status_code == 200
    assert response.json() == {'ok': True, 'pin': {'key': 'hunt', 'label': 'Find Clefairy', 'started': False}}
    assert client.get('/api/state').json()['strategy']['pin']['label'] == 'Find Clefairy'
    assert client.get('/api/goals').json()['pin']['key'] == 'hunt'
    assert client.post('/api/control', json={'action': 'unpin_goal'}).json()['ok'] is True
    assert client.get('/api/state').json()['strategy']['pin'] is None


def test_web_refuses_an_unknown_or_missing_key_with_a_reason(web):
    client, game = web
    response = client.post('/api/control', json={'action': 'pin_goal', 'value': 'gone'})
    assert response.status_code == 409 and response.json()['detail'] == 'Not available now'
    response = client.post('/api/control', json={'action': 'pin_goal', 'value': ' '})
    assert response.status_code == 400 and response.json()['detail'] == 'Choose a goal from the list'
    assert game.pin is None


def test_web_view_only_cannot_read_or_set_goals(web, monkeypatch):
    client, game = web
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    assert client.get('/api/goals').status_code == 403
    assert client.post('/api/control', json={'action': 'pin_goal', 'value': 'hunt'}).status_code == 403
    assert game.pin is None
