"""The overnight watch's Gen II quality hunt check decides from its rows alone, without the app."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('quality_hunt_watch_tool', ROOT / 'tools' / 'quality_hunt_watch.py')
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def mon(species, level, power, box=None, tid=1, dvs=(8, 8, 8, 8, 8), name=None, **extra):
    return {'species': species, 'name': name or f'Mon{species}', 'level': level, 'potential_power': power,
            'box': box, 'trainer_id': tid, 'dvs': list(dvs), **extra}


def never(identity):
    return False


def row(**extra):
    base = {'id': 'a', 'name': 'Run', 'version': 'gold', 'state': 'running', 'hours': 100.0, 'wall': 1000.0,
            'decisions': 5000, 'can_catch': True, 'trainees': [], 'searches': {'10': 3}, 'hunt': None,
            'captures': []}
    return {**base, **extra}


def test_upgrade_margin_matches_the_policy():
    from pokesim.investment import MIN_UPGRADE
    assert tool.MIN_UPGRADE == MIN_UPGRADE


def test_trainee_is_the_best_copy_below_level_100():
    mons = [mon(1, 100, 500), mon(2, 40, 600), mon(2, 100, 550)]
    assert tool.trainees(mons, never, False, 0.02) == [['Mon2', 40]]


def test_a_level_100_copy_about_as_strong_leaves_no_trainee():
    assert tool.trainees([mon(2, 40, 560), mon(2, 100, 550)], never, False, 0.02) == []
    perfect = mon(2, 40, 560, perfect_dvs=True)
    assert tool.trainees([perfect, mon(2, 100, 550)], never, False, 0.02) == [['Mon2', 40]]


def test_standing_down_and_sealed_boxes_and_eggs_leave_no_trainee():
    assert tool.trainees([mon(3, 30, 400, tid=7)], lambda identity: identity[0] == 7, False, 0.02) == []
    assert tool.trainees([mon(3, 30, 400, box=2)], never, True, 0.02) == []
    assert tool.trainees([mon(3, 30, 400, box=2)], never, False, 0.02) == [['Mon3', 30]]
    assert tool.trainees([mon(3, 5, 400, egg=True)], never, False, 0.02) == []


def test_no_adventure_qualifies():
    lines, failed, kept = tool.judge([row(trainees=[['Raticate', 87], ['Golem', 32]])], {})
    assert not failed and kept == {}
    assert lines == ['Run (Gold): 2 trainees left, such as Raticate 87, Golem 32',
                     'no Gen 2 adventure has run out of trainees yet']


def test_stopped_adventure_is_skipped_and_keeps_its_state():
    lines, failed, kept = tool.judge([{'id': 'a', 'name': 'Run', 'version': 'silver', 'state': 'stopped'}],
                                     {'a': {'hours': 1}})
    assert not failed and kept == {'a': {'hours': 1}}
    assert lines[0] == 'Run (Silver): stopped, skipped'


def test_first_sighting_waits_and_records_the_game_hour():
    lines, failed, kept = tool.judge([row()], {})
    assert not failed
    assert kept == {'a': {'hours': 100.0, 'wall': 1000.0, 'decisions': 5000, 'searches': {'10': 3}}}
    assert 'no quality hunt yet after 0.0 of 6 game hours' in lines[0]


def test_no_hunt_after_six_game_hours_fails():
    saved = {'a': {'hours': 90.0, 'wall': 0.0, 'decisions': 1000, 'searches': {'10': 3}}}
    lines, failed, kept = tool.judge([row(can_catch=False)], saved)
    assert failed and 'a' in kept
    assert lines[0] == ('Run (Gold): FAILED, training ran out by game hour 90.0 and no quality hunt started '
                        'in 10.0 game hours, and its boxes are full so it cannot catch')


def test_current_hunt_is_placed_by_decisions():
    saved = {'a': {'hours': 80.0, 'wall': 0.0, 'decisions': 1000, 'searches': {'10': 3}}}
    # Started a fifth of the way through 20 game hours, so 4 hours after training ran out.
    lines, failed, kept = tool.judge([row(hunt={'species': 10, 'started': 1800})], saved)
    assert not failed and kept['a']['proven'] == 84.0
    assert lines[0] == 'Run (Gold): training ran out by game hour 80.0, quality hunt started 4.0 game hours later'
    # Once shown, later nights keep passing on the recorded start.
    lines, failed, _ = tool.judge([row(hours=200.0)], kept)
    assert not failed and 'started 4.0 game hours later' in lines[0]


def test_late_hunt_fails():
    saved = {'a': {'hours': 80.0, 'wall': 0.0, 'decisions': 1000, 'searches': {'10': 3}}}
    lines, failed, kept = tool.judge([row(hunt={'species': 10, 'started': 4000})], saved)
    assert failed and 'proven' not in kept['a']
    assert lines[0].endswith('the first quality hunt started 15.0 game hours later, past the 6 hour limit')


def test_finished_hunt_is_placed_by_its_first_catch():
    saved = {'a': {'hours': 80.0, 'wall': 0.0, 'decisions': 1000, 'searches': {'10': 3}}}
    # Species 12 gained a finished hunt. Its first catch came a tenth of the way through, 2 hours in.
    captures = [[12, -5.0], [99, 50.0], [12, 100.0], [12, 600.0]]
    lines, failed, kept = tool.judge([row(searches={'10': 3, '12': 1}, captures=captures)], saved)
    assert not failed and kept['a']['proven'] == 82.0


def test_finished_hunt_without_a_catch_counts_at_now():
    saved = {'a': {'hours': 98.0, 'wall': 0.0, 'decisions': 1000, 'searches': {}}}
    lines, failed, kept = tool.judge([row()], saved)
    assert not failed and kept['a']['proven'] == 100.0
    saved = {'a': {'hours': 80.0, 'wall': 0.0, 'decisions': 1000, 'searches': {}}}
    assert tool.judge([row()], saved)[1]


def test_trainee_coming_back_clears_the_state():
    saved = {'a': {'hours': 80.0, 'wall': 0.0, 'decisions': 1000, 'searches': {}}}
    _, failed, kept = tool.judge([row(trainees=[['Pidgey', 12]])], saved)
    assert not failed and kept == {}


def test_main_writes_the_state(tmp_path, monkeypatch, capsys):
    import io
    state = tmp_path / 'quality-hunts.json'
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps([row()])))
    assert tool.main(['tool', 'judge', str(state)]) == 0
    assert json.loads(state.read_text())['a']['hours'] == 100.0
    assert 'no quality hunt yet' in capsys.readouterr().out
