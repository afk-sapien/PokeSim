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


def test_empty_or_broken_input_fails_plainly(tmp_path, monkeypatch, capsys):
    import io
    state = tmp_path / 'quality-hunts.json'
    monkeypatch.setattr('sys.stdin', io.StringIO(''))
    assert tool.main(['tool', 'judge', str(state)]) == 1
    assert capsys.readouterr().out == 'FAILED: no input, the collect step printed nothing\n'
    monkeypatch.setattr('sys.stdin', io.StringIO('<html>401</html>'))
    assert tool.main(['tool', 'judge', str(state)]) == 1
    assert capsys.readouterr().out.startswith('FAILED: the collect step printed something other than JSON')
    assert not state.exists()


def adventure(root, aid, version, state='running', frames=0, policy=None):
    import sqlite3
    folder = root / 'adventures' / aid
    folder.mkdir(parents=True)
    (folder / 'adventure.json').write_text(json.dumps(
        {'id': aid, 'name': aid.title(), 'version': version, 'state': state, 'rom_id': 'r'}))
    db = sqlite3.connect(folder / 'pokesim.sqlite')
    db.execute('CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)')
    db.execute('CREATE TABLE capture_receipts (dex INTEGER, recorded_at REAL)')
    # The policy's state lives in the newest autosave's manifest, and an older one holds a stale copy.
    (folder / 'states').mkdir()
    (folder / 'states' / 'auto-v1-1.json').write_text(json.dumps({'policy_state': {'decisions': 1}}))
    (folder / 'states' / 'auto-v1-2.json').write_text(json.dumps({'policy_state': policy or {'decisions': 7}}))
    db.execute("INSERT INTO kv VALUES ('play_clock', ?)", (json.dumps({'frames': frames}),))
    db.execute('INSERT INTO capture_receipts VALUES (16, 5.0)')
    db.commit()
    db.close()


def test_collect_reads_files_only_so_every_auth_mode_works(tmp_path, monkeypatch, capsys):
    """The overnight watch broke when the app moved to AUTH=accounts, since collect read its pages. It
    now reads the data folder alone, so it must work with every network connection refused."""
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError('collect must not open a connection')

    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)
    monkeypatch.setenv('AUTH', 'accounts')
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    adventure(tmp_path, 'gold', 'gold', frames=2 * 3600 * 60 + 59)
    adventure(tmp_path, 'red', 'red')
    adventure(tmp_path, 'paused', 'crystal', state='stopped')
    party = [mon(152, 30, 900, name='Chikorita'), mon(16, 100, 400, name='Pidgey')]
    storage = {'pokemon': [mon(19, 12, 300, box=1, name='Rattata')], 'can_catch': True, 'box_counts': [1]}
    read = []
    monkeypatch.setattr(tool, 'saved_game', lambda root, meta: read.append(meta['id']) or
                        {'party': party, 'storage': storage})
    tool.collect()
    rows = json.loads(capsys.readouterr().out)
    assert read == ['gold']
    assert [(row['id'], row['state']) for row in rows] == [('gold', 'running'), ('paused', 'stopped')]
    gold = rows[0]
    assert gold['hours'] == 2.0 and gold['decisions'] == 7 and gold['can_catch']
    assert gold['trainees'] == [['Chikorita', 30], ['Rattata', 12]]
    assert gold['captures'] == [[16, 5.0]]


def test_the_overnight_watch_reads_the_app_without_its_site():
    for name in ('overnight_watch.sh', 'alert_watch.sh'):
        script = (ROOT / 'tools' / name).read_text(encoding='utf-8')
        assert 'curl' not in script and 'wget' not in script and 'POKESIM_WATCH_SITE' not in script
    assert 'urllib' not in (ROOT / 'tools' / 'quality_hunt_watch.py').read_text(encoding='utf-8')


def test_the_overnight_watch_only_health_checks_the_hosted_app():
    """The tests and the quality hunts follow the local dev instance, so the hosted app gets one SSH call."""
    script = (ROOT / 'tools' / 'overnight_watch.sh').read_text(encoding='utf-8')
    calls = [line for line in script.splitlines() if 'ssh -o' in line]
    assert len(calls) == 1 and 'docker exec $CONTAINER pokesim smoke' in script
    assert 'alert_watch.sh' not in script and 'org.opencontainers.image.revision' not in script
    assert 'DEV_UNIT' in script and 'quality-hunts-dev.json' in script
