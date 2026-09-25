"""The adventure's headline numbers over time, recorded with the journal and rebuilt from it."""
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

from pokesim.events import Event
from pokesim.ram import HALL_OF_FAME_MAP
from pokesim.store import Store
from pokesim.web.app import create_app
from test_events import snap


def history(store):
    return [(row['badges'], row['owned'], row['seen'], row['league']) for row in store.progress()]


def test_a_row_is_written_only_when_a_number_changes(tmp_path):
    store = Store(tmp_path)
    store.add_event(Event('map', 'Pallet Town', ''), snap(), None, None)
    store.add_event(Event('map', 'Route 1', ''), snap(), None, None)
    store.add_event(Event('seen', 'Saw PIDGEY', ''), snap(seen=frozenset({1, 16})), None, None)
    store.add_event(Event('catch', 'Caught PIDGEY', ''), snap(owned=frozenset({1, 16}), seen=frozenset({1, 16})),
                    None, None)
    store.add_event(Event('badge', 'Boulder Badge', ''), snap(badges=1, owned=frozenset({1, 16}),
                                                                   seen=frozenset({1, 16})), None, None)
    assert history(store) == [(0, 1, 1, 0), (0, 1, 2, 0), (0, 2, 2, 0), (1, 2, 2, 0)]
    assert all(row['ts'] > 0 for row in store.progress())


def test_a_league_victory_counts_once_even_when_replayed(tmp_path):
    store = Store(tmp_path)
    hall = snap(map=HALL_OF_FAME_MAP, badges=255)
    for number in (1, 1, 2):
        store.add_event(Event('champion', f'Champion! League victory #{number}'), hall, None, None)
    assert [row[3] for row in history(store)] == [1, 2]


def test_an_unstarted_or_invalid_screen_is_not_recorded(tmp_path):
    store = Store(tmp_path)
    store.add_event(Event('map', 'Title', ''), snap(map=0, party=(), playtime=(0, 0, 0)), None, None)
    assert store.progress() == []


def journal(path, rows):
    db = sqlite3.connect(path / 'pokesim.sqlite')
    db.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, type TEXT NOT NULL, "
               "title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', notable INTEGER NOT NULL DEFAULT 1, "
               "map TEXT NOT NULL DEFAULT '', playtime TEXT NOT NULL DEFAULT '', shot TEXT, state TEXT)")
    db.executemany('INSERT INTO events(ts, type, title, body) VALUES (?,?,?,?)', rows)
    db.commit()
    db.close()


def test_an_older_adventure_is_rebuilt_from_its_journal(tmp_path):
    journal(tmp_path, [
        (10, 'catch', 'Caught PIDGEY', 'A level 3 PIDGEY on Route 1. Pokédex: 2 owned.'),
        (20, 'level', 'PIDGEY grew', 'Level 4.'),
        (30, 'badge', 'Beat Brock! Got the Boulder Badge', '1/8 badges after 1h of play.'),
        (40, 'playtime', '10 hours of play time', '20 owned, 3 badges, on Route 9.'),
        (50, 'champion', 'Champion! League victory #1', 'The Hall of Fame.'),
        (60, 'champion', 'Champion! League victory #1', 'Replayed after a rewind.'),
        (70, 'obtain', 'Got LAPRAS', 'New Pokédex entry on Silph Co. 7F. 21 owned.'),
    ])
    store = Store(tmp_path)
    assert [(row['ts'], row['badges'], row['owned'], row['seen'], row['league']) for row in store.progress()] == [
        (10, 0, 2, None, 0), (30, 1, 2, None, 0), (40, 3, 20, None, 0), (50, 3, 20, None, 1),
        (70, 3, 21, None, 1)]
    store.db.close()
    assert len(Store(tmp_path).progress()) == 5


def test_the_game_serves_the_history(tmp_path):
    store = Store(tmp_path)
    store.add_event(Event('catch', 'Caught PIDGEY', ''), snap(owned=frozenset({1, 16})), None, None)
    client = TestClient(create_app(SimpleNamespace(status=lambda: {}), store))
    [row] = client.get('/api/progress').json()
    assert (row['badges'], row['owned'], row['league']) == (0, 2, 0)


def test_the_journal_chart_uses_no_id_the_shared_page_script_writes(tmp_path):
    # app.js runs on every adventure page and fills elements by id. It once wrote the live page's
    # "tiles explored" line into the Journal's chart section, which shared its id, and erased it.
    import re
    from pathlib import Path
    static = Path(__file__).parents[1] / 'pokesim/web/static'
    written = set(re.findall(r"set\('#([\w-]+)'", (static / 'app.js').read_text()))
    chart = re.search(r'<section class="progress".*?</section>', (static / 'journal.html').read_text(), re.S)[0]
    assert written.isdisjoint(re.findall(r'id="([\w-]+)"', chart))


def goals(store):
    return [(row['level100'], row['perfect']) for row in store.progress()]


def test_a_row_follows_each_new_level_100_or_perfect_find(tmp_path):
    from pokesim.milestones import KEY, empty
    from pokesim import progress
    store = Store(tmp_path)
    progress.goals_changed(store.db, 1)
    assert store.progress() == []  # nothing to carry before the adventure's first row
    store.add_event(Event('catch', 'Caught PIDGEY', ''), snap(owned=frozenset({1, 16})), None, None)
    for level_100, groups in ((['16'], {}), (['16'], {}), (['16', '17'], {'1:16': 1})):
        store.set(KEY, {**empty(), 'level_100': level_100, 'perfect_groups': groups})
        with store.db:
            progress.goals_changed(store.db, 2)
    assert goals(store) == [(0, 0), (1, 0), (2, 1)]
    assert history(store)[-1] == (0, 2, 1, 0)
    store.add_event(Event('badge', 'Boulder Badge', ''), snap(badges=1, owned=frozenset({1, 16})), None, None)
    assert goals(store)[-1] == (2, 1)


def test_a_040_table_gains_the_long_goals_empty(tmp_path):
    db = sqlite3.connect(tmp_path / 'pokesim.sqlite')
    db.execute('CREATE TABLE progress (ts REAL NOT NULL, badges INTEGER NOT NULL, owned INTEGER NOT NULL, '
               'seen INTEGER, league INTEGER NOT NULL)')
    db.execute('INSERT INTO progress VALUES (1, 8, 149, 150, 134)')
    db.commit()
    db.close()
    [row] = Store(tmp_path).progress()
    assert (row['owned'], row['league'], row['level100'], row['perfect']) == (149, 134, None, None)
