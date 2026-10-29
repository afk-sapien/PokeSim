"""Faints, blackouts, trainer wins, evolutions and releases are kept after the journal is pruned."""
import sqlite3
import time

from pokesim import adventure_counters
from pokesim.events import Event
from pokesim.store import Store
from test_events import snap

MOMENTS = [('faint', 'PIDGEY fainted', ''), ('blackout', 'Blacked out!', 'The whole party fainted on ROUTE 1 fighting a RATTATA.'),
           ('blackout', 'Blacked out!', 'The whole party fainted on VIRIDIAN FOREST.'), ('trainer', 'Defeated Bug Catcher', ''),
           ('trainer', 'Defeated Brock', ''), ('evolve', 'PIDGEY evolved into Pidgeotto!', ''),
           ('release', 'Said goodbye to a spare Rattata', ''), ('catch', 'Caught Rattata!', '')]


def counts(store):
    result = adventure_counters.status(store)
    return {key: result[key] for key in (*adventure_counters.NAMES, 'trainer_battles', 'trainer_win_rate')}


EXPECTED = {'faints': 1, 'blackouts': 2, 'trainers_defeated': 2, 'evolutions': 1, 'releases': 1,
            'trainer_losses': 1, 'trainer_battles': 3, 'trainer_win_rate': 66.7}


def test_each_journal_moment_is_counted_as_it_is_written(tmp_path):
    store = Store(tmp_path)
    for kind, title, body in MOMENTS:
        store.add_event(Event(kind, title, body), snap(), None, None)
    assert counts(store) == EXPECTED
    store.db.execute("UPDATE events SET ts = 0")
    store.db.commit()
    assert store.prune_events(1) == len(MOMENTS)
    assert store.events() == []
    assert counts(store) == EXPECTED
    store.close()
    # Reopening never counts the same entries twice.
    reopened = Store(tmp_path)
    assert counts(reopened) == EXPECTED and adventure_counters.status(reopened)['complete_history']
    reopened.close()


def old_database(path, rows):
    """A journal from before priorities, details and tallies, with only the original columns."""
    path.mkdir()
    db = sqlite3.connect(path / 'pokesim.sqlite')
    db.executescript("""
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, type TEXT NOT NULL,
  title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', notable INTEGER NOT NULL DEFAULT 1,
  map TEXT NOT NULL DEFAULT '', playtime TEXT NOT NULL DEFAULT '', shot TEXT, state TEXT);
CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);""")
    db.executemany('INSERT INTO events(ts, type, title, body) VALUES (?, ?, ?, ?)', rows)
    db.commit()
    return db


def test_an_old_journal_backfills_once_and_later_entries_from_an_older_version_count_once(tmp_path):
    path = tmp_path / 'red'
    db = old_database(path, [(time.time(), kind, title, body) for kind, title, body in MOMENTS])
    db.close()
    store = Store(path)
    assert counts(store) == EXPECTED
    assert adventure_counters.status(store)['complete_history']
    store.close()
    # An older version keeps writing entries without counting them.
    db = sqlite3.connect(path / 'pokesim.sqlite')
    db.execute("INSERT INTO events(ts, type, title) VALUES (?, 'faint', 'RATTATA fainted')", (time.time(),))
    db.commit()
    db.close()
    for _ in range(2):
        store = Store(path)
        assert counts(store) == {**EXPECTED, 'faints': 2}
        store.close()
    # The original rows are untouched.
    db = sqlite3.connect(path / 'pokesim.sqlite')
    assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == len(MOMENTS) + 1
    db.close()


def test_a_pruned_journal_says_when_its_tallies_start(tmp_path):
    path = tmp_path / 'red'
    db = old_database(path, [(100.0, 'faint', 'gone', ''), (200.0, 'faint', 'PIDGEY fainted', '')])
    db.execute('DELETE FROM events WHERE id = 1')
    db.commit()
    db.close()
    store = Store(path)
    result = adventure_counters.status(store)
    assert (result['faints'], result['complete_history'], result['since']) == (1, False, 200.0)
    store.close()


def test_a_stopped_adventure_counts_without_writing(tmp_path):
    path = tmp_path / 'red'
    old_database(path, [(time.time(), kind, title, body) for kind, title, body in MOMENTS]).close()
    (path / 'shots').mkdir()
    (path / 'states').mkdir()
    view = Store(path, read_only=True)
    assert counts(view) == EXPECTED
    view.close()
    db = sqlite3.connect(path / 'pokesim.sqlite')
    assert db.execute("SELECT name FROM sqlite_master WHERE name='kv'").fetchone()
    assert db.execute('SELECT COUNT(*) FROM kv').fetchone()[0] == 0
    db.close()
