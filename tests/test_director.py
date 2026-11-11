import json
import random
from dataclasses import replace
from unittest.mock import Mock

from pokesim.policies.collection import Collection, candidate, training_targets
from pokesim.policies.director import AdventureDirector
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.planning.monitor import STAND_DOWNS
from pokesim.runtime.supervision import MONITOR_KEY, Tables
from pokesim.strategy_data import ITEMS, MAPS, WORLD
from test_collection import reloaded, sid, state
from test_strategy import flags, mon


class Kv(dict):
    """An adventure store with only the get and set the supervisor's tables use."""

    def set(self, key, value):
        self[key] = json.loads(json.dumps(value))


def stand_downs(director):
    """The director's stand-downs in a row per project key, as the monitor keeps them."""
    return director.monitor.rows(STAND_DOWNS)


def pick(director, *projects):
    """The director's pick among ``projects``, each a (Candidate, project) pair."""
    return director.select([option for option, _ in projects], {option.key: project for option, project in projects})


def test_restarts_preserve_repeated_failure_backoff_and_ignore_the_old_recent_picks():
    store = Kv()
    director = AdventureDirector()
    director.attach(Tables(store))
    catch = {'method': 'grass', 'species': sid(16), 'key': 'pidgey', 'repeat': True}
    first_retry = director.finish(catch, 0, False, 'No encounter')
    # The autosave writes the tables to the store, and the restarted worker reads them back.
    director.progress.flush()
    restored = AdventureDirector()
    restored.attach(Tables(store))
    restored.load({**json.loads(json.dumps(director.state_dict())), 'recent': [{'category': 'collection', 'key': 'pidgey'}]})
    assert 'recent' not in restored.state_dict()
    second_retry = restored.finish(catch, first_retry, False, 'No encounter')
    assert second_retry - first_retry == 120000
    assert restored.outcomes[-1]['reason'] == 'No encounter'
    restored.finish(catch, second_retry, True, 'Caught Pidgey')
    assert 'pidgey' not in stand_downs(restored)
    assert restored.completed == {'collection': 1}


def test_a_rematch_waits_behind_every_other_project_unless_money_is_short():
    rematch = {'method': 'rematch', 'hof_count': 3, 'key': 'rematch'}
    explore = {'method': 'explore', 'map': 1, 'target': (1, 2, 3), 'key': 'explore'}
    train = {'method': 'train', 'parent': sid(113), 'key': 'chansey', 'initial_level': 50, 'target_level': 60,
             'mastery_needed': True}
    rows = [(candidate(project, 0, {}, False, set()), project) for project in (rematch, explore, train)]
    assert pick(AdventureDirector(), *rows) == train
    # A filler explore goes before a rematch, which takes the longest.
    assert pick(AdventureDirector(), *rows[:2]) == explore
    assert pick(AdventureDirector(), rows[0]) == rematch
    short = [(candidate(project, 0, {}, True, set()), project) for project in (rematch, train)]
    assert pick(AdventureDirector(), *short) == rematch
    assert AdventureDirector().select([], {}) is None


def test_productive_training_hard_limit_is_advanced_and_does_not_escalate_failure():
    c = Collection()
    c.completed_champion = True
    c.project = {'method': 'train', 'parent': sid(113), 'family': [sid(113)],
                 'initial_level': 65, 'target_level': 70, 'key': 'train:chansey:70'}
    c.remaining = 120
    c.observe(state(frame=0, party=(mon(species=sid(113), level=65, experience=10000),)))
    c.project['training_session']['active_frames'] = 360000 - 120
    c.observe(state(frame=120, party=(mon(species=sid(113), level=65, experience=10500),)))
    assert c.project is None
    assert c.director.outcomes[-1]['status'] == 'advanced'
    assert c.director.outcomes[-1]['gains']['experience'] == 500
    assert not stand_downs(c.director)
    assert not c.director.completed


def test_training_target_and_gains_survive_a_checkpoint_until_the_actual_level():
    c = Collection()
    c.completed_champion = True
    c.project = {'method': 'train', 'parent': sid(113), 'family': [sid(113)],
                 'initial_level': 69, 'target_level': 70, 'key': 'train:chansey:70'}
    c.remaining = 72000
    start = state(party=(mon(species=sid(113), level=69, experience=10000),), owned=frozenset({113}))
    c.observe(start)
    assert c.project is not None
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    restored.observe(replace(start, frame=200, party=(replace(start.party[0], level=70, experience=11000),)))
    assert restored.project is None
    outcome = restored.director.outcomes[-1]
    assert outcome['status'] == 'completed'
    assert outcome['target'] == 70
    assert outcome['gains'] == {'experience': 1000, 'levels': 1}


def test_productive_training_still_stops_when_idle_and_preserves_partial_progress():
    c = Collection()
    c.project = {'method': 'train', 'parent': sid(113), 'family': [sid(113)],
                 'initial_level': 65, 'target_level': 70, 'key': 'train:chansey:70'}
    c.remaining = 72000
    stand_downs(c.director)[c.project['key']] = 3
    start = state(party=(mon(species=sid(113), level=65, experience=10000),))
    c.observe(start)
    gained = replace(start, frame=120, party=(replace(start.party[0], experience=10524),))
    c.observe(gained)
    restored = reloaded(c)
    restored.observe(gained)
    for frame in range(240, 7441, 120):
        restored.observe(replace(gained, frame=frame))
    assert restored.project is None
    outcome = restored.director.outcomes[-1]
    assert outcome['status'] == 'advanced'
    assert outcome['gains'] == {'experience': 524, 'levels': 0}
    assert 'No trainee experience gain' in outcome['reason']
    assert outcome['retry_at'] - outcome['clock'] == 60000
    assert not stand_downs(restored.director)
    assert not restored.director.completed


def test_other_party_experience_and_supply_changes_cannot_hide_failed_training():
    c = Collection()
    c.project = {'method': 'train', 'parent': sid(113), 'family': [sid(113)],
                 'initial_level': 65, 'target_level': 70, 'key': 'train:chansey:70'}
    c.remaining = 72000
    for frame in range(0, 7800, 120):
        c.observe(state(frame=frame, x=frame % 20,
                        items=((ITEMS['POKE_BALL'], 10 + frame % 240),),
                        party=(mon(species=sid(113), level=65, experience=10000),
                               mon(species=sid(3), level=100, experience=frame))))
    assert c.project is None
    assert c.director.outcomes[-1]['status'] == 'deferred'


def test_full_dex_still_selects_training_and_level_100_has_no_training_candidate():
    c = Collection()
    nav = Navigator()
    nav.visits = {(m, 0, 0): 1 for m in WORLD}
    nav.distance_lookup = Mock(return_value=lambda targets: 0 if targets else None)
    s = state(map=MAPS['ROUTE_1'], money=100000, hall_of_fame_count=1,
              event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_GOT_HITMONLEE'),
              owned=frozenset(range(1, 152)), party=(mon(species=sid(113), level=99),),
              items=tuple((ITEMS[item], 10) for item in ('POKE_BALL', 'OLD_ROD', 'GOOD_ROD', 'SUPER_ROD')))
    c.observe(s)
    c.director.select = Mock(side_effect=lambda candidates, projects:
                             next(project for project in projects.values() if project['method'] == 'train'))
    goal = c.choose(s, nav, random.Random(1), Goal('collect_plan', 'Plan', 'Plan'))
    assert goal.key == 'collect_train'
    assert c.project['target_level'] == 100
    assert goal.targets
    c = Collection()
    s = replace(s, party=(replace(s.party[0], level=100),))
    c.observe(s)
    c.director.select = Mock(wraps=c.director.select)
    assert c.choose(s, nav, random.Random(1), Goal('collect_plan', 'Plan', 'Plan')).key in ('collect_rematch', 'collect_hunt')
    assert all(project['method'] != 'train' for project in c.director.select.call_args.args[1].values())
    assert c.project['method'] != 'train'


def test_high_level_training_has_encounters_and_boxed_partner_uses_existing_pc_flow():
    assert training_targets('red', 99)
    c = Collection()
    c.project = {'method': 'train', 'parent': sid(113), 'family': [sid(113)],
                 'box': 2, 'initial_level': 65, 'target_level': 70, 'key': 'train:chansey:70'}
    s = state(stored_pokemon=((2, sid(113), 65, 'MOCHI'),))
    assert c.goal(s).key == 'party_collection'
    assert c.goal(replace(s, party=s.party + (mon(species=sid(113), level=65),))).key == 'collect_train'


def test_director_records_are_bounded_and_snapshots_do_not_alias_live_state():
    director = AdventureDirector()
    for index in range(200):
        director.finish({'method': 'explore', 'key': str(index)}, index, False, 'Unreachable')
    assert len(stand_downs(director)) == 128
    assert len(director.outcomes) == 24
    saved = director.state_dict()
    saved['outcomes'].clear()
    assert len(director.outcomes) == 24


def test_an_older_save_keeps_its_retry_times_counts_and_idle_frames():
    hunt = {'method': 'grass', 'species': sid(132), 'key': 'ditto'}
    older = {**Collection().state_dict(), 'elapsed': 1000, 'project': hunt, 'idle_frames': 3000,
             'attempts': {'pidgey': 1000 + 240000, 'spent': 500},
             'director': {'recent': [], 'outcomes': [], 'failures': {'pidgey': 3}}}
    c = Collection()
    c.load(json.loads(json.dumps(older)))
    assert stand_downs(c.director) == {'pidgey': 3}
    assert c.director.waiting('pidgey', 1000 + 239999)
    assert not c.director.waiting('pidgey', 1000 + 240000)
    assert not c.director.waiting('spent', 1000)
    assert c.idle_frames == 3000
    # The next failure doubles from the saved count, up to the cap.
    assert c.director.finish({'method': 'grass', 'key': 'pidgey'}, 2000, False, 'No encounter') == 2000 + 480000


def test_a_project_budget_survives_a_restart_and_a_catch_makes_it_whole_again():
    project = {'method': 'grass', 'species': sid(16), 'key': 'pidgey', 'repeat': True, 'initial_count': 0,
               'catch_goal': 3}
    c = Collection()
    c.project = project
    c.remaining = 600
    start = state(map=MAPS['ROUTE_1'])
    for frame in range(0, 360, 120):
        c.observe(replace(start, frame=frame, in_battle=1))
    assert c.remaining == 360
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    assert restored.remaining == 360
    restored.observe(replace(start, frame=360, in_battle=1))
    caught = replace(start, frame=480, in_battle=1, party=start.party + (mon(species=sid(16)),))
    restored.observe(caught)
    assert restored.remaining == 36000
    restored.remaining = 120
    restored.observe(replace(caught, frame=600))
    assert restored.project is None
    assert restored.director.outcomes[-1]['reason'] == 'Expedition time budget reached'
    assert 'budget:pidgey' not in restored.director.progress.get('progress_frames', {})


def test_new_maps_reset_the_idle_count_but_not_the_failures_in_a_row():
    c = Collection()
    stand_downs(c.director)['ditto'] = 2
    c.project = {'method': 'grass', 'species': sid(132), 'key': 'ditto'}
    c.remaining = 36000
    for frame in range(0, 600, 120):
        c.observe(state(frame=frame, map=MAPS['ROUTE_1'] if frame % 240 else MAPS['ROUTE_2']))
    assert stand_downs(c.director)['ditto'] == 2
    c.abandon('No encounter')
    assert stand_downs(c.director)['ditto'] == 3
    assert c.director.outcomes[-1]['retry_at'] - c.clock == 240000


def test_a_reload_keeps_a_stand_down_and_the_frames_a_project_spent():
    project = {'method': 'grass', 'species': sid(16), 'key': 'pidgey', 'repeat': True, 'initial_count': 0,
               'catch_goal': 3}
    c = Collection()
    c.project, c.remaining = project, 600
    start = state(map=MAPS['ROUTE_1'])
    for frame in range(0, 360, 120):
        c.observe(replace(start, frame=frame, in_battle=1))
    saved = json.loads(json.dumps(c.state_dict()))
    assert 'progress' not in saved['director']
    c.director.finish({'method': 'grass', 'key': 'ditto'}, 5000, False, 'No encounter')
    c.observe(replace(start, frame=360, in_battle=1))
    assert c.remaining == 240
    # The reload goes back to a save from before the stand-down and the last 120 frames.
    c.load(saved)
    assert c.project['key'] == 'pidgey'
    assert c.remaining == 240
    assert c.director.waiting('ditto', 5001)


def test_an_older_save_waits_out_what_was_left_of_its_stand_downs_on_the_play_clock():
    store = Kv()
    store.clock = lambda: 90000
    c = Collection()
    c.director.attach(Tables(store))
    older = {**Collection().state_dict(), 'elapsed': 1000,
             'director': {'outcomes': [], 'progress': {'stood_down': {'ditto': 400}, 'stand_downs': {'ditto': 1}}}}
    c.load(json.loads(json.dumps(older)))
    # It stood down 600 frames before the save, so 59400 of its 60000 are left from the PlayClock's 90000.
    assert c.director.waiting('ditto', 90000 + 59399)
    assert not c.director.waiting('ditto', 90000 + 59400)
    assert stand_downs(c.director) == {'ditto': 1}
    # A second load of the same save keeps the tables the first one took.
    c.load(json.loads(json.dumps(older)))
    assert c.director.monitor.until('ditto') == 90000 + 59400
    c.director.progress.flush()
    assert store[MONITOR_KEY]['stood_down'] == {'ditto': 89400}
    assert Tables(store) == {name: table for name, table in c.director.progress.items() if table}


def test_a_headless_run_counts_an_older_save_on_from_its_own_frames():
    c = Collection()
    c.director.attach(Tables(clock=lambda: 5000))
    older = {**Collection().state_dict(), 'elapsed': 1000,
             'director': {'outcomes': [], 'progress': {'stood_down': {'ditto': 400}}}}
    c.load(json.loads(json.dumps(older)))
    assert c.director.monitor.until('ditto') == 5000 - 600 + 60000


def test_a_new_game_starts_with_empty_tables_in_the_same_store():
    from pokesim.policies.strategic import StrategicPolicy
    store = Kv()
    policy = StrategicPolicy(42)
    policy.monitor_tables = Tables(store)
    tables = policy.monitor_tables
    assert policy.collection.director.progress is tables
    policy.collection.director.finish({'method': 'grass', 'key': 'ditto'}, 0, False, 'No encounter')
    assert tables
    policy.reset()
    assert policy.monitor_tables is tables and not any(tables.values())
    tables.flush()
    assert store[MONITOR_KEY] == {}
