"""Gold, Silver and Crystal stats count what Red, Blue and Yellow count."""
import json
import os
import time
from types import SimpleNamespace

import pytest

from pokesim import progress
from pokesim.gen2.tracking import CAPTURES, Tracker, record_gift
from pokesim.statistics import recent
from pokesim.store import Store


@pytest.fixture(scope='module', params=['gold', 'crystal'])
def real_data(request):
    from pokesim.gen2.data import GameData
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def journal(store):
    return store.db.execute("INSERT INTO events(ts,type,title,body,notable,priority,map,playtime) "
                            "VALUES (?,'obtain','Received Mew from a custom PokeSim gift','',1,4,'','')",
                            (time.time(),)).lastrowid


def test_a_custom_gift_counts_toward_total_caught_once(tmp_path):
    store = Store(tmp_path)
    Tracker(store, SimpleNamespace(), fresh=True)
    with store.lock, store.db:
        entry = journal(store)
        record_gift(store.db, entry, 151)
        record_gift(store.db, entry, 151)
    captures = store.get(CAPTURES)
    assert (captures['total'], captures['counts']) == (1, {'151': 1})
    # Dated by its journal entry, like a Red, Blue and Yellow gift.
    day = recent(store)['day']
    assert day['catches'] == 1 and not day['undated_gifts']
    store.close()


def test_a_gift_before_capture_counting_starts_is_left_alone(tmp_path):
    store = Store(tmp_path)
    with store.lock, store.db:
        record_gift(store.db, journal(store), 151)
    assert store.get(CAPTURES) is None
    store.close()


def mon(species, level, dvs):
    return SimpleNamespace(species=species, level=level, dvs=dvs, trainer_id=7, egg=False)


def test_a_new_level_100_species_writes_a_progress_row(real_data, tmp_path):
    store = Store(tmp_path)
    tracker = Tracker(store, real_data, fresh=True)
    with store.lock, store.db:
        store.db.execute(f'INSERT INTO progress(ts, {progress.COLUMNS}) VALUES (?,?,?,?,?,?,?)',
                         (time.time() - 60, 8, 40, 60, 1, 0, 0))
    snapshot = SimpleNamespace(valid=True, started=True, party=[mon(130, 100, (15,) * 5)], stored=[])
    tracker.observe(snapshot)
    tracker.observe(snapshot)
    rows = store.db.execute('SELECT badges, owned, seen, league, level100, perfect FROM progress ORDER BY rowid').fetchall()
    # Gyarados at 100 also credits Magikarp, the same way the Pokédex counts it.
    assert [tuple(row) for row in rows] == [(8, 40, 60, 1, 0, 0), (8, 40, 60, 1, 2, 1)]
    tracker.observe(snapshot)
    assert store.db.execute('SELECT COUNT(*) FROM progress').fetchone()[0] == 2
    assert json.loads(store.db.execute('SELECT v FROM kv WHERE k=?', ('pokedex-milestones-v1',)).fetchone()[0])[
        'level_100'] == [129, 130]
    store.close()
