import json
import random
from dataclasses import replace

from pokesim.policies import marathon
from pokesim.policies.collection import Collection
from pokesim.policies.director import AdventureDirector, category, new_entry
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.strategy_data import MAPS
from test_collection import state
from test_journal_shots import game, scene
from test_strategy import mon


def race():
    collection = Collection()
    collection.project = dict(marathon.candidate(), key='race')
    collection.remaining = marathon.BUDGET
    collection.completed_champion = True
    return collection


def checkpoint(index, frame=0, **kwargs):
    map_id, x, y = marathon.COURSE[index]
    return state(map=map_id, x=x, y=y, frame=frame, **kwargs)


def test_course_is_navigable_in_both_directions_without_surf():
    nav = Navigator()
    nav.update_story(checkpoint(0, badges=255, saffron_open=True,
                                party=(mon(moves=(15,), pp=(30,)),)))
    for source, target in zip(marathon.COURSE, marathon.COURSE[1:]):
        assert nav.route(source, (target,), 0) is not None, (source, target)
    assert marathon.COURSE[0] == marathon.COURSE[-1]


def test_start_line_and_ordered_checkpoints_are_required():
    c = race()
    c.observe(checkpoint(3))
    assert c.project['checkpoint'] == 0
    c.observe(checkpoint(0, 60), overworld=False)
    assert c.project['checkpoint'] == 0
    c.observe(checkpoint(0, 120))
    assert c.project['checkpoint'] == 1
    assert c.project['race_frames'] == 0
    assert len(c.take_activity_events()) == 1
    c.observe(checkpoint(11, 180))
    assert c.project['checkpoint'] == 1
    assert not c.marathon_records
    assert not c.take_activity_events()


def test_finish_report_and_personal_best_are_saved_and_journaled(tmp_path):
    c = race()
    for index in range(len(marathon.COURSE)):
        c.observe(checkpoint(index, index * 60))
    assert c.project is None
    assert c.director.completed['recreation'] == 1
    assert c.marathon_records['completed'] == 1
    assert c.marathon_records['best_frames'] == 660
    assert c.marathon_records['last']['checkpoints'] == 11
    events = c.take_activity_events()
    assert len(events) == 2
    assert events[-1].title == 'Kanto Marathon finished!'
    assert '11/11 checkpoints' in events[-1].body
    assert '0:11 game time' in events[-1].body
    emu = game(tmp_path, [scene()])
    emu._handle_events(events, checkpoint(11))
    assert len(emu.store.events()) == 2
    assert all((emu.store.shots / row['shot']).is_file() for row in emu.store.events())
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    assert restored.marathon_records == c.marathon_records
    assert restored.next_marathon == c.elapsed + marathon.INTERVAL
    assert restored.take_activity_events() == []


def test_counts_adjacent_movement_and_battle_entries_without_warps_or_idle_credit():
    c = race()
    start = checkpoint(0)
    c.observe(start)
    c.observe(replace(start, x=start.x + 1, frame=60))
    c.observe(replace(start, x=start.x + 1, frame=120))
    c.observe(replace(start, x=start.x + 10, frame=180))
    c.observe(checkpoint(2, 240))
    c.observe(checkpoint(2, 300, in_battle=1))
    c.observe(checkpoint(2, 360, in_battle=1))
    c.observe(checkpoint(2, 420))
    c.observe(checkpoint(2, 480, in_battle=1))
    assert c.project['gains']['steps'] == 1
    assert c.project['gains']['battles'] == 2
    assert c.project['checkpoint'] == 1


def test_healing_counts_one_restoration_per_center_visit_and_not_party_swaps():
    c = race()
    c.observe(checkpoint(0))
    hurt = state(frame=60, map=MAPS['VIRIDIAN_POKECENTER'], party=(mon(hp=10, max_hp=100),))
    c.observe(hurt)
    c.observe(replace(hurt, frame=120, party=(mon(hp=30, max_hp=100),)))
    c.observe(replace(hurt, frame=180, party=(mon(hp=100, max_hp=100),)))
    assert c.project['gains']['healing_stops'] == 1
    c.observe(checkpoint(1, 240))
    c.observe(replace(hurt, frame=300))
    c.observe(replace(hurt, frame=360, party=(mon(hp=100, max_hp=100, nick='OTHER'),)))
    assert c.project['gains']['healing_stops'] == 1


def test_restart_preserves_race_and_does_not_count_a_gap_or_repeat_start():
    c = race()
    c.observe(checkpoint(0))
    c.take_activity_events()
    c.observe(checkpoint(1, 60))
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    restored.observe(checkpoint(1, 300, in_battle=1))
    assert restored.project['gains']['battles'] == 0
    assert restored.project['race_frames'] == 60
    assert not restored.take_activity_events()
    assert restored.goal(checkpoint(1)).targets == (marathon.COURSE[2],)
    assert restored.goal(checkpoint(1)).title == 'Kanto Marathon'
    assert 'Pewter City' in restored.goal(checkpoint(1)).reason


def test_clock_includes_detours_but_stationary_runs_end_without_a_finish():
    c = race()
    c.observe(checkpoint(0))
    for frame in range(120, 7320, 120):
        c.observe(checkpoint(0, frame), suspended=True)
    assert c.project is None
    assert c.marathon_records['last']['finished'] is False
    assert 'best_frames' not in c.marathon_records
    assert c.take_activity_events()[-1].title == 'Kanto Marathon called off'


def test_absolute_budget_stops_a_moving_race():
    c = race()
    c.observe(checkpoint(0))
    c.remaining = 60
    c.observe(replace(checkpoint(0, 60), x=10))
    assert c.project is None
    assert not c.marathon_records['last']['finished']
    assert c.next_marathon > c.elapsed


def test_marathon_never_displaces_missing_entries_or_urgent_supplies():
    director = AdventureDirector()
    recreation = dict(marathon.candidate(), key='race')
    missing = {'method': 'grass', 'species': 1, 'key': 'missing'}
    supplies = {'method': 'rematch', 'key': 'supplies'}
    assert category(recreation) == 'recreation'
    assert not new_entry(recreation)
    for seed in range(10):
        assert director.select([(10000, recreation), (1, missing)], random.Random(seed)) == missing
        assert director.select([(10000, recreation), (1, supplies)], random.Random(seed), urgent=True) == supplies


def test_candidate_requires_postgame_prior_work_cut_open_gates_and_cooldown():
    class Selector:
        def __init__(self):
            self.candidates = []
            self.completed = {'training': 4}

        def select(self, candidates, rng, urgent=False):
            self.candidates = [p for _, p in candidates]
            return next((p for p in self.candidates if p['method'] == 'marathon'), self.candidates[0])

    for eligible, champion, cut, gates, completed, deadline in (
            (True, True, True, True, 4, 0),
            (False, True, False, True, 4, 0),
            (False, True, True, False, 4, 0),
            (False, True, True, True, 3, 0),
            (False, True, True, True, 4, 60000)):
        c = Collection()
        c.completed_champion = champion
        c.director = Selector()
        c.director.completed['training'] = completed
        c.next_marathon = deadline
        s = checkpoint(0, badges=255, saffron_open=gates, money=50000,
                       owned=frozenset(range(1, 152)), party=(mon(level=100, moves=(15,) if cut else (33,)),))
        nav = Navigator()
        nav.update_story(s)
        c.choose(s, nav, random.Random(1), Goal('collect_plan', 'Next', 'Next'))
        assert any(p['method'] == 'marathon' for p in c.director.candidates) is eligible
        if eligible:
            assert c.project['method'] == 'marathon'
            assert c.remaining == marathon.BUDGET
            assert c.next_marathon == marathon.INTERVAL


def test_legacy_state_and_invalid_observations_are_safe():
    c = Collection()
    c.next_marathon = 90000
    c.marathon_records = {'completed': 1, 'best_frames': 123}
    c.activity_events = [{'type': 'marathon', 'title': 'Old race'}]
    c.load({'elapsed': 123})
    assert c.marathon_records == {} and c.next_marathon == 0
    assert c.take_activity_events() == []
    c = race()
    c.observe(checkpoint(0))
    c.observe(checkpoint(1, 60, party=(mon(level=101),)))
    assert c.project['checkpoint'] == 1
    assert c.project['gains']['steps'] == 0
