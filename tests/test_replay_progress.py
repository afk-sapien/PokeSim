import hashlib
import json
import sqlite3

import pytest

from pokesim.replay.progress import (Axis, Episode, Flag, connect, ground_truth, load, main, rebuild, replay, score,
                                     segments)
from pokesim.progress_events import HOUR

T0 = 1_700_000_000


def playtime(seconds):
    return f'{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'


def store(folder, version='red', events=(), receipts=(), progress=()):
    """A small adventure folder with only the tables the replay reads."""
    folder.mkdir(parents=True)
    (folder / 'adventure.json').write_text(json.dumps({'id': folder.name, 'version': version}), encoding='utf-8')
    db = sqlite3.connect(folder / 'pokesim.sqlite')
    db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, ts REAL, type TEXT, title TEXT, body TEXT, detail TEXT, '
               'map TEXT, playtime TEXT)')
    db.execute('CREATE TABLE capture_receipts (recorded_at REAL, fingerprint TEXT, dex INTEGER)')
    db.execute('CREATE TABLE progress (ts REAL, badges INTEGER, owned INTEGER, league INTEGER, level100 INTEGER, '
               'perfect INTEGER)')
    db.execute('CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)')
    for i, (ts, kind, title, body) in enumerate(events, 1):
        db.execute('INSERT INTO events VALUES (?, ?, ?, ?, ?, NULL, ?, ?)',
                   (i, ts, kind, title, body, 'Route 1', playtime(int(ts - T0) + 3600)))
    db.executemany('INSERT INTO capture_receipts VALUES (?, ?, ?)', receipts)
    db.executemany('INSERT INTO progress VALUES (?, ?, ?, ?, ?, ?)', progress)
    db.commit()
    db.close()
    return folder


def churning(tmp_path):
    """Four hours of catching the same thing every five minutes, then the live stall alert."""
    events = [(T0, 'badge', 'Won the Boulder Badge', '')]
    receipts = []
    for i in range(1, 49):
        ts = T0 + i * 300
        events.append((ts, 'catch', 'Caught Rattata', ''))
        receipts.append((ts, f'catch-{i}', 19))
    events.append((T0 + 49 * 300, 'stall', 'Stuck? 2 game hours without progress', 'after 120 real minutes'))
    return store(tmp_path / 'adv', events=events, receipts=receipts)


def test_rebuild_kinds_and_net(tmp_path):
    events = [
        (T0, 'obtain', 'Received Eevee from a gift', ''),
        (T0 + 10, 'release', 'Said goodbye to a spare Eevee Lv 25', ''),
        (T0 + 20, 'badge', 'Won the Boulder Badge', ''),
        (T0 + 30, 'map', 'Found Route 2', ''),
        (T0 + 40, 'item', 'Got a Potion', ''),
        (T0 + 50, 'item', 'Got a Potion', ''),
        (T0 + 60, 'trainer', 'Beat Youngster', ''),
        (T0 + 70, 'trainer', 'Beat Youngster', ''),
        (T0 + 80, 'marathon', 'Kanto Marathon is on!', ''),
        (T0 + 190, 'marathon', 'Kanto Marathon finished!', ''),
        (T0 + 200, 'champion', 'Became Champion', ''),
    ]
    adv = load(store(tmp_path / 'adv', events=events, receipts=[(T0 + 5, 'catch-1', 19)],
                     progress=[(T0, 0, 1, 0, 0, 0), (T0 + 100, 1, 3, 0, 1, 0)]))
    rows = rebuild(adv, Axis([], 'wall'))
    kinds = [(r.kind, r.net, r.key) for r in rows]
    assert ('receive', 0, 'eevee') in kinds and ('release', 0, 'eevee') in kinds
    assert ('catch', 0, 'dex:19') in kinds
    assert [r.net for r in rows if r.kind == 'item'] == [1, 0]
    assert sum(r.kind == 'event' for r in rows) == 1
    assert sum(r.kind == 'checkpoint' for r in rows) == 11
    assert sum(r.kind == 'dex' for r in rows) == 2 and sum(r.kind == 'improve' for r in rows) == 1
    assert {r.kind for r in rows if r.net} == {'badge', 'area', 'item', 'event', 'checkpoint', 'league', 'dex', 'improve'}


def test_called_off_marathon_has_no_checkpoints(tmp_path):
    events = [(T0, 'marathon', 'Johto Marathon is on!', ''), (T0 + 60, 'marathon', 'Johto Marathon called off', '')]
    adv = load(store(tmp_path / 'adv', version='gold', events=events))
    assert not [r for r in rebuild(adv, Axis([], 'wall')) if r.kind == 'checkpoint']


def test_duplicate_catches_stall_old_misses_new_catches(tmp_path):
    adv = load(churning(tmp_path))
    end = adv.events[-1].ts
    axis = Axis([(e.ts, (e.ts - T0 + 3600) * 60) for e in adv.events], 'playtime')
    episodes = ground_truth(adv, axis)
    assert len(episodes) == 1
    old, new, churn = replay(adv, axis, rebuild(adv, axis), end - 86400, end)
    assert not [f for f in old if f.check == 'stallwatch']
    assert [f for f in new if f.check == 'stallwatch']
    assert churn
    assert score(episodes, old, end - 86400, end)['missed'] == 1
    assert score(episodes, new, end - 86400, end)['caught'] == 1


def test_score_counts_false_alarms_and_time_to_detect():
    episode = Episode(1000, 100 * HOUR, 8200, 102 * HOUR, ['label'])
    flags = [Flag(5000, 101 * HOUR, 'stallwatch'), Flag(5060, 101 * HOUR + 60, 'watchdog'),
             Flag(90000, 200 * HOUR, 'stallwatch')]
    result = score([episode], flags, 0, 100000)
    assert (result['caught'], result['missed'], result['false_alarms']) == (1, 0, 1)
    assert result['detect_frames'] == {'median': HOUR, 'worst': HOUR}
    assert result['detect_minutes']['median'] == pytest.approx(4000 / 60, abs=0.1)


def test_labels_add_and_clear_stalls(tmp_path):
    adv = load(churning(tmp_path))
    axis = Axis([], 'wall')
    cleared = ground_truth(adv, axis, [{'adventure': 'adv', 'start': T0, 'end': T0 + 49 * 300, 'stall': False}])
    assert cleared == []
    added = ground_truth(adv, axis, [{'adventure': 'adv', 'start': T0 - 50000, 'end': T0 - 40000}])
    assert len(added) == 2 and added[0].sources == ['label']


def test_segments_split_on_long_gaps(tmp_path):
    events = [(T0, 'map', 'a', ''), (T0 + 600, 'map', 'b', ''), (T0 + 20000, 'map', 'c', '')]
    assert len(segments(load(store(tmp_path / 'adv', events=events)))) == 2


def test_connect_is_read_only(tmp_path):
    folder = churning(tmp_path)
    db = connect(folder / 'pokesim.sqlite')
    with pytest.raises(sqlite3.OperationalError):
        db.execute('DELETE FROM events')
    db.close()


def test_cli_writes_report_and_leaves_input_alone(tmp_path, capsys):
    folder = churning(tmp_path / 'stores')
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    out = tmp_path / 'out' / 'report.json'
    assert main(['run', str(tmp_path / 'stores'), '--days', '7', '--out', str(out)]) == 0
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    assert before == after
    report = json.loads(out.read_text(encoding='utf-8'))
    result = report['inputs'][0]['adventures'][0]
    assert result['new']['caught'] == 1 and result['old']['missed'] == 1
    assert 'No stall bundles in this input.' in report['inputs'][0]['notes']
    assert report['ambiguities'] and report['missing_sources']
    capsys.readouterr()
    assert main(['report', str(out)]) == 0
    assert 'Bar:' in capsys.readouterr().out


def test_cli_refuses_report_inside_input(tmp_path):
    churning(tmp_path / 'stores')
    with pytest.raises(SystemExit):
        main(['run', str(tmp_path / 'stores'), '--out', str(tmp_path / 'stores' / 'report.json')])
