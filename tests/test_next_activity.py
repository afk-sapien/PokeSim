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
from pokesim.planning import arbiter, decide, pin, values
from pokesim.planning.arbiter import Tier
from pokesim.planning.pin import Pin
from pokesim.play_clock import PlayClock
from pokesim.policies.collection import Collection
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.runtime.supervision import Supervisor
from pokesim.strategy_data import EVENTS, ITEMS, MAPS, SPECIES
from pokesim.web.app import create_app
from test_collection import state
from test_events import snap
from test_strategy import flags, mon

SPECIES_ID = {row['dex']: sid for sid, row in SPECIES.items()}


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


def started_with_progress():
    """A post-game Red whose plan started a project and made progress on it."""
    c, s, nav = postgame()
    c.choose(s, nav, random.Random(3), PLAN)
    running = c.project
    assert running is not None and c.pin is None
    running.setdefault('gains', {})['catches'] = 2
    c.idle_frames = 500
    c.remaining -= 1000
    c.project_maps.append(MAPS['ROUTE_2'])
    progress = {'key': c.project_key, 'idle': c.idle_frames, 'left': c.remaining, 'maps': list(c.project_maps)}
    goals, _ = c.goal_list(s, nav, random.Random(3))
    other = next(goal for goal in goals if goal['key'] != progress['key'])
    return c, s, nav, running, progress, other


def test_gen1_a_pin_sets_the_running_project_aside_and_it_resumes_intact_after_the_pin():
    # Rule C of the decide pipeline: a pin runs next and the project under way resumes after it.
    c, s, nav, running, progress, other = started_with_progress()
    c.set_pin(s, nav, random.Random(3), other['key'])
    assert c.project is None and c.paused['project'] is running
    assert c.history[-1].startswith('Set aside: ')
    c.choose(s, nav, random.Random(3), PLAN)
    assert c.project_key == other['key'] and c.pin.started
    c.idle_frames = 90
    c.abandon('The hunt ended')
    assert c.pin is None and c.paused is not None
    c.choose(s, nav, random.Random(3), PLAN)
    assert c.project is running and running['gains']['catches'] == 2 and c.paused is None
    assert (c.idle_frames, c.remaining, c.project_maps) == (progress['idle'], progress['left'], progress['maps'])
    assert c.history[-1].startswith('Resumed: ')


def test_gen1_a_project_set_aside_is_saved_and_resumes_after_a_load():
    import json
    c, s, nav, running, progress, other = started_with_progress()
    c.set_pin(s, nav, random.Random(3), other['key'])
    c.choose(s, nav, random.Random(3), PLAN)
    # A reload keeps the monitor, which holds each project's idle count and budget.
    saved = json.loads(json.dumps(c.state_dict()))
    c.paused = None
    loaded = c
    loaded.load(saved)
    assert loaded.pin is None and loaded.project_key == other['key']
    loaded.abandon('The hunt ended')
    loaded.choose(s, nav, random.Random(3), PLAN)
    assert loaded.project_key == progress['key'] and loaded.project['gains']['catches'] == 2
    assert loaded.project_maps == progress['maps'] and loaded.idle_frames == progress['idle']


def test_gen1_a_cancelled_pin_gives_the_project_back_and_pinning_it_resumes_it():
    c, s, nav, running, progress, other = started_with_progress()
    c.set_pin(s, nav, random.Random(3), other['key'])
    c.clear_pin()
    c.choose(s, nav, random.Random(3), PLAN)
    assert c.project is running and c.idle_frames == progress['idle']
    c.set_pin(s, nav, random.Random(3), other['key'])
    c.set_pin(s, nav, random.Random(3), progress['key'])
    assert c.project is running and c.pin.started and c.paused is None


def full_postgame():
    """A long post-game Red: every badge and rod, half the Pokédex, two copies of each in the PC."""
    species = SPECIES_ID
    party = tuple(mon(species=species[number], level=60, hp=200, max_hp=200, moves=moves, pp=(15,) * 4)
                  for number, moves in ((9, (57, 70, 15, 148)), (18, (19, 33, 0, 0)), (65, (94, 0, 0, 0)),
                                        (6, (53, 0, 0, 0)), (130, (57, 0, 0, 0)), (143, (34, 0, 0, 0))))
    owned = frozenset(range(1, 120))
    stored = tuple((i // 20, species[number], 30 + number % 30, '') for i, number in enumerate(sorted(owned) * 2))
    items = tuple((ITEMS[item], 50) for item in ('POKE_BALL', 'ULTRA_BALL', 'OLD_ROD', 'GOOD_ROD', 'SUPER_ROD'))
    beaten = [flag for flag in EVENTS if 'BEAT' in flag or flag.startswith('EVENT_GOT')]
    s = state(map=MAPS['CELADON_CITY'], party=party, owned=owned, seen=owned, badges=0xFF, money=500000,
              items=items, stored_pokemon=stored, event_flags=flags('EVENT_GOT_POKEDEX', *beaten))
    c = Collection()
    c.completed_champion = True
    nav = Navigator()
    nav.update_story(s)
    return c, s, nav


def test_gen1_a_full_postgame_lists_each_want_once_and_at_most_the_limit():
    c, s, nav = full_postgame()
    options = c.offers(s, nav, random.Random(3))[0]
    goals, reason = c.goal_list(s, nav, random.Random(3))
    every, _ = c.goal_list(s, nav, random.Random(3), limit=None)
    # The planner keeps one option per place, many more than the picker shows.
    assert len(options) > 3 * len(every) > 3 * pin.LIMIT
    assert reason is None and len(goals) == pin.LIMIT
    assert goals == every[:pin.LIMIT]
    labels = [goal['label'] for goal in every]
    assert len(set(labels)) == len(labels)
    assert not any(label.startswith('Find ') for label in labels)
    assert sum(label.startswith('Better Pidgey') for label in labels) == 1


def test_gen1_a_search_finds_a_goal_past_the_limit_and_it_can_be_set():
    c, s, nav = full_postgame()
    every, _ = c.goal_list(s, nav, random.Random(3), limit=None)
    beyond = every[-1]
    name = beyond['label'].split(' (')[0].split()[-1]
    found, reason = c.goal_list(s, nav, random.Random(3), query=name.lower())
    assert reason is None and beyond in found and all(name.lower() in goal['label'].lower() for goal in found)
    assert c.set_pin(s, nav, random.Random(3), beyond['key']).label == beyond['label']
    assert c.goal_list(s, nav, random.Random(3), query='no such pokemon') == ([], 'No goal matches that name')


def test_gen1_setting_a_group_runs_its_best_ranked_place():
    c, s, nav = full_postgame()
    options, projects, _, _ = c.offers(s, nav, random.Random(3))
    ranked = [option.key for option in arbiter.rank(options)]
    pidgey = [key for key in ranked if projects[key].get('species') == SPECIES_ID[16] and projects[key].get('dv_hunt')]
    assert len(pidgey) > 1
    goals, _ = c.goal_list(s, nav, random.Random(3), limit=None)
    [listed] = [goal for goal in goals if goal['label'] == 'Better Pidgey (DV hunt)']
    assert listed['key'] == pidgey[0]
    c.set_pin(s, nav, random.Random(3), listed['key'])
    c.choose(s, nav, random.Random(3), PLAN)
    assert c.project_key == pidgey[0] and c.pin.started


def test_the_picker_groups_rows_once_each_in_rank_order():
    rows = [('a:1', 'pidgey', 'Better Pidgey', Tier.PROGRESS), ('b', 'mew', 'Get Mew', Tier.PROGRESS),
            ('a:2', 'pidgey', 'Better Pidgey', Tier.FILLER), ('c', 'other', 'Get Mew', Tier.FILLER)]
    assert pin.grouped(rows) == [{'key': 'a:1', 'label': 'Better Pidgey', 'tier': 'progress'},
                                 {'key': 'b', 'label': 'Get Mew', 'tier': 'progress'}]
    assert pin.grouped(rows, query=' MEW ') == [{'key': 'b', 'label': 'Get Mew', 'tier': 'progress'}]
    assert len(pin.grouped([(str(i), i, f'Goal {i}', Tier.FILLER) for i in range(100)])) == pin.LIMIT


def pinned_emulator():
    emu = Emulator.__new__(Emulator)
    emu.policy = StrategicPolicy(7)
    emu.policy.collection.pin = Pin('hunt', 'Find Clefairy')
    emu.snapshot = snap(frame=1000)
    emu.supervisor = Supervisor()
    emu.play_clock = PlayClock()
    emu.journal = []
    emu._handle_events = lambda events, snapshot: emu.journal.extend(event.title for event in events)
    return emu


def test_gen1_a_stall_recovery_drops_the_pin():
    from pokesim.runtime.reload import FRAMES_PER_SECOND
    emu = pinned_emulator()
    emu.frame, emu.input_epoch = 10 ** 6, 0
    emu.stuck_frame = emu.frame - (config.STUCK_RELOAD_SECONDS + 1) * FRAMES_PER_SECOND
    emu._unstick = Mock()
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
    nav = SimpleNamespace(walk=lambda snapshot, target: [])
    return SimpleNamespace(data=data, nav=nav, collection={'target': None}, monitor_tables={}, menu=None,
                           completed={'red': 1}, decisions=10, clock=10, **extra)


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


def test_gen2_a_pinned_rung_passes_every_check_and_a_parked_pin_says_why(monkeypatch):
    # Rule B of the decide pipeline: a pin skips no check. A pin parked before it starts waits with the
    # reason the API state carries, and a run that ends parked is journaled with it.
    owner = gen2_policy(pin=Pin('league:league', 'Label league'))
    owner.monitor_tables[ladder_module.STOOD_DOWN] = {'league': 1}
    monkeypatch.setattr(ladder_module, 'standing_down', lambda policy, key: key == ladder_module.rung_key('league'))
    rungs = weigh(owner)
    assert rungs.rung == 'hunt' and 'league' not in rungs.asked
    settle_pin(owner, rungs)
    assert owner.pin.to_dict() == {'key': 'league:league', 'label': 'Label league', 'started': False,
                                   'parked': {'kind': 'stood_down', 'detail': 'stood down'}}
    owner.monitor_tables.clear()
    owner.no_route_waiting = lambda goal: goal.key == 'league'
    rungs = weigh(owner)
    assert rungs.rung == 'hunt' and 'league' in rungs.asked
    settle_pin(owner, rungs)
    assert owner.pin.parked == decide.NO_ROUTE and not owner.pin.started
    assert not ladder_module.pin_events(owner)
    owner.no_route_waiting = lambda goal: False
    settle_pin(owner, weigh(owner))
    assert owner.pin.started and owner.pin.parked is None
    owner.no_route_waiting = lambda goal: goal.key == 'league'
    settle_pin(owner, weigh(owner))
    assert owner.pin is None
    assert [row['title'] for row in owner.pin_events] == ['Gave up on Label league: no route']


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


def test_gen2_lists_each_label_once_at_most_the_limit_and_pins_past_it(monkeypatch):
    from pokesim.gen2.policy import Policy
    offers = [SimpleNamespace(key=f'hunt:{i}', tier=Tier.PROGRESS) for i in range(60)]
    # Two rungs can offer the same want. The better ranked one is listed.
    labels = {offer.key: f'Catch Goal {i // 2}' for i, offer in enumerate(offers)}
    monkeypatch.setattr(ladder_module, 'survey', lambda *args: (offers, labels, None))
    owner = gen2_policy(pin=None)
    goals, reason = ladder_module.goal_list(owner, None, None, None)
    every, _ = ladder_module.goal_list(owner, None, None, None, limit=None)
    assert reason is None and len(goals) == pin.LIMIT and len(every) == 30 == len({g['label'] for g in every})
    assert every[1] == {'key': 'hunt:2', 'label': 'Catch Goal 1', 'tier': 'progress'}
    assert ladder_module.goal_list(owner, None, None, None, query='goal 29') == (
        [{'key': 'hunt:58', 'label': 'Catch Goal 29', 'tier': 'progress'}], None)
    assert ladder_module.goal_list(owner, None, None, None, query='mew') == ([], 'No goal matches that name')
    many = [SimpleNamespace(key=f'hunt:{i}', tier=Tier.PROGRESS) for i in range(45)]
    monkeypatch.setattr(ladder_module, 'survey', lambda *args: (many, {o.key: o.key for o in many}, None))
    picker = SimpleNamespace(pin=None, ladder_pick=None,
                             goals=lambda snapshot, every=False: ladder_module.goal_list(
                                 owner, None, None, None, limit=None if every else pin.LIMIT))
    assert len(picker.goals(None)[0]) == pin.LIMIT
    assert Policy.pin_goal(picker, None, 'hunt:44').key == 'hunt:44'


def test_gen2_refuses_before_red_and_an_unknown_key_with_a_reason():
    from pokesim.gen2.policy import Policy
    assert ladder_module.goal_list(SimpleNamespace(completed={}), None, None, None) == ([], 'Finish the story first')
    owner = SimpleNamespace(pin=None, goals=lambda snapshot, every=False: ([], 'Finish the story first'))
    with pytest.raises(ValueError, match='Finish the story first'):
        Policy.pin_goal(owner, None, 'hunt:hunt')
    owner.goals = lambda snapshot, every=False: ([{'key': 'hunt:hunt', 'label': 'Label hunt', 'tier': 'progress'}], None)
    with pytest.raises(ValueError, match='Not available now'):
        Policy.pin_goal(owner, None, 'league:league')
    assert owner.pin is None
    assert Policy.pin_goal(owner, None, 'hunt:hunt').label == 'Label hunt'


def test_gen2_an_unstick_drops_the_pin_and_journals_it():
    from pokesim.gen2.emulator import Emulator as Gen2
    from pokesim.gen2.policy import Policy
    from pokesim.runtime.supervision import MAX_RELOADS
    from test_supervision import ladder
    journal = []
    run = SimpleNamespace(pin=Pin('hunt:hunt', 'Label hunt'))
    run.drop_pin = lambda: Policy.drop_pin(run)
    emu = SimpleNamespace(policy=run, snapshot=SimpleNamespace(), supervisor=ladder(MAX_RELOADS, exhausted=True),
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
        self.query = None

    def call(self, function, timeout=None):
        return function()

    def goals(self, query=None):
        self.query = query
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
    assert game.query is None
    client.get('/api/goals', params={'q': '  Clefairy '})
    assert game.query == 'Clefairy'


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
