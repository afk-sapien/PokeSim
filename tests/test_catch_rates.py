"""Catch pace, wild encounters per catch and the dated shiny log."""
from contextlib import closing
import sqlite3

import pytest

from pokesim import shiny
from pokesim.activity_ledger import KEY, increment
from pokesim.catch_rates import status
from pokesim.store import Store


@pytest.mark.parametrize('generation', [1, 2])
def test_old_shiny_receipts_stay_undated_and_new_ones_are_dated(tmp_path, generation):
    _, table, _ = shiny.LEDGERS[generation]
    with closing(Store(tmp_path)) as store, store.lock, store.db:
        # A receipt table from before dates were kept.
        store.db.execute(f'CREATE TABLE {table} (kind TEXT NOT NULL, fingerprint TEXT NOT NULL, '
                         'dex INTEGER NOT NULL, PRIMARY KEY(kind,fingerprint))')
        store.db.execute(f"INSERT INTO {table} VALUES ('seen', 'old', 25)")
    with closing(Store(tmp_path)) as store:
        with store.lock, store.db:
            assert shiny.log(store.db, generation, {}) == [{'kind': 'seen', 'dex': 25, 'name': '#025', 'ts': None}]
            for _ in range(2):
                shiny.initialize(store.db, generation)
            assert shiny.record(store.db, 'acquired', 'new', 25, generation=generation)
            assert not shiny.record(store.db, 'acquired', 'new', 25, generation=generation)
            log = shiny.log(store.db, generation, {25: 'PIKACHU'})
        assert [(entry['kind'], entry['name']) for entry in log] == [('seen', 'PIKACHU'), ('acquired', 'PIKACHU')]
        assert log[0]['ts'] is None and log[1]['ts'] > 0
    db = sqlite3.connect(tmp_path / 'pokesim.sqlite')
    assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 2
    db.close()


def test_an_adventure_without_receipts_has_an_empty_shiny_log(tmp_path):
    with closing(Store(tmp_path)) as store:
        assert shiny.log(store.db, 1, {}) == shiny.log(store.db, 2, {}) == []


def test_catch_pace_needs_catches_playtime_and_counted_encounters(tmp_path):
    with closing(Store(tmp_path)) as store:
        catches = {'total': 6, 'available': True, 'complete_history': False, 'started_at': 1.0}
        # The activity ledger has not started, so its encounters are unknown.
        assert status(store, catches, {'seconds': 7200}) == {
            'catches_per_hour': 3.0, 'encounters_per_catch': None, 'partial': True}
        store.set(KEY, {'started_at': 1.0, 'available': True})
        with store.lock, store.db:
            increment(store.db, 'wild', 16, 25)
            increment(store.db, 'wild', 19, 25)
            increment(store.db, 'caught', 16, 4)
        assert status(store, catches, {'seconds': 7200})['encounters_per_catch'] == 12.5
        assert status(store, catches, None)['catches_per_hour'] is None
        assert status(store, {'available': False}, {'seconds': 60})['catches_per_hour'] is None
