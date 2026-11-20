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
    # A receipt table from before dates were kept, in a database from before schema versions.
    with closing(sqlite3.connect(tmp_path / 'pokesim.sqlite')) as db, db:
        db.execute(f'CREATE TABLE {table} (kind TEXT NOT NULL, fingerprint TEXT NOT NULL, '
                   'dex INTEGER NOT NULL, PRIMARY KEY(kind,fingerprint))')
        db.execute(f"INSERT INTO {table} VALUES ('seen', 'old', 25)")
    with closing(Store(tmp_path)) as store:
        with store.lock, store.db:
            assert shiny.log(store.db, generation, {}) == [{'id': 1, 'kind': 'seen', 'dex': 25, 'name': '#025', 'ts': None}]
            for _ in range(2):
                shiny.initialize(store.db, generation)
            assert shiny.record(store.db, 'acquired', 'new', 25, generation=generation)
            assert not shiny.record(store.db, 'acquired', 'new', 25, generation=generation)
            log = shiny.log(store.db, generation, {25: 'PIKACHU'})
        assert [(entry['kind'], entry['name']) for entry in log] == [('acquired', 'PIKACHU'), ('seen', 'PIKACHU')]
        assert log[0]['ts'] > 0 and log[1]['ts'] is None
    db = sqlite3.connect(tmp_path / 'pokesim.sqlite')
    assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 2
    db.close()


def test_an_adventure_without_receipts_has_an_empty_shiny_log(tmp_path):
    with closing(Store(tmp_path)) as store:
        assert shiny.log(store.db, 1, {}) == shiny.log(store.db, 2, {}) == []
        assert shiny.species(store.db, 1, {}) == shiny.species(store.db, 2, {}) == []


@pytest.mark.parametrize('generation', [1, 2])
def test_the_shiny_log_pages_back_through_every_receipt_and_counts_each_species(tmp_path, generation):
    """26 receipts page back 10 at a time with none missed or repeated, newest first, and the
    summary counts each species with nothing pruned."""
    with closing(Store(tmp_path)) as store:
        with store.lock, store.db:
            for index in range(25):
                shiny.record(store.db, 'seen', f'wild-{index}', 25 if index % 5 == 0 else 129, generation=generation)
            shiny.record(store.db, 'acquired', 'gift', 25, generation=generation)
            pages = [shiny.log(store.db, generation, {129: 'MAGIKARP'})]
            while pages[-1]:
                pages.append(shiny.log(store.db, generation, {129: 'MAGIKARP'}, 10, pages[-1][-1]['id']))
            species = shiny.species(store.db, generation, {129: 'MAGIKARP'})
    assert [len(page) for page in pages] == [10, 10, 6, 0]
    ids = [entry['id'] for page in pages for entry in page]
    assert ids == list(range(26, 0, -1))
    assert pages[0][0]['kind'] == 'acquired' and pages[0][1]['name'] == 'MAGIKARP'
    assert species == [{'dex': 129, 'name': 'MAGIKARP', 'seen': 20, 'acquired': 0},
                       {'dex': 25, 'name': '#025', 'seen': 5, 'acquired': 1}]


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
