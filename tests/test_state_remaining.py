"""Slice R4 of docs/design/adventure-state-store.md: the modules no earlier slice named keep no SQL of their own.

The progress history, the trade settings, the walking returns of both generations and the legacy pair
trade pass their handle to pokesim/state/kv.py, pokesim/state/tracking.py, pokesim/state/journal.py and
pokesim/state/ledgers.py. The pair trade opens each adventure through ``state.connect``.
"""
import ast
from contextlib import closing
from pathlib import Path

import pytest

from pokesim import progress
from pokesim.state import journal, kv, ledgers, tracking
from pokesim.store import Store
from pokesim.trade import preferences

PACKAGE = Path(__file__).resolve().parents[1] / 'pokesim'
MODULES = ('progress.py', 'trade/preferences.py', 'trade/event.py', 'trade/pair.py', 'trade/service.py',
           'legendary_returns.py', 'gen2/returns.py')
RAW = {'execute', 'executemany', 'executescript', 'db', 'lock', 'connect'}


@pytest.mark.parametrize('name', MODULES)
def test_a_module_reaches_the_database_only_through_pokesim_state(name):
    tree = ast.parse((PACKAGE / name).read_text(encoding='utf-8'))
    raw = [f'{name}:{node.lineno} .{node.attr}' for node in ast.walk(tree)
           if isinstance(node, ast.Attribute) and node.attr in RAW]
    raw += [f'{name}:{node.lineno} import sqlite3' for node in ast.walk(tree)
            if isinstance(node, ast.Import) and any(alias.name == 'sqlite3' for alias in node.names)]
    assert raw == [], 'Put the statement in pokesim/state, and open an adventure with state.connect.'


@pytest.fixture
def store(tmp_path):
    with closing(Store(tmp_path)) as store:
        yield store


def test_a_prefix_scan_matches_the_prefix_exactly(store):
    with store.transaction() as db:
        kv.put(db, 'trade_offer:a', {'state': 'locked'})
        kv.put_text(db, 'trade_offer:b', 'not json')
        kv.put(db, 'tradeXoffer:c', 1)
        kv.put(db, 'TRADE_OFFER:d', 1)
    with store.reading() as db:
        assert sorted(map(tuple, kv.starting(db, 'trade_offer:'))) == [('trade_offer:a', '{"state": "locked"}'),
                                                          ('trade_offer:b', 'not json')]
        assert kv.text(db, 'trade_offer:b') == 'not json'
        assert kv.text(db, 'missing') is None
    with store.transaction() as db:
        kv.delete(db, 'trade_offer:a')
    with store.reading() as db:
        assert not kv.exists(db, 'trade_offer:a')


def test_an_upgrade_moves_an_unreadable_setting_as_it_was_stored(store):
    # A Red, Blue or Yellow Pikachu, as tests/test_trade_identity.py builds one.
    mon = {'species': 84, 'name': 'Pikachu', 'trainer_id': 4321, 'dvs': [7, 9, 3, 12, 6]}
    old, new = preferences.PREFIX + preferences.signature(mon), preferences.PREFIX + preferences.identity(mon)
    with store.transaction() as db:
        kv.put_text(db, old, '{broken')
        assert preferences.upgrade(db, [mon]) is True
        assert kv.text(db, new) == '{broken'
        # No family key holds a readable setting, so the older copy goes.
        assert kv.text(db, old) is None


def test_progress_rows_keep_their_numbers_and_thin_past_the_shown_count(store):
    with store.transaction() as db:
        assert not tracking.has_progress(db)
        assert tracking.last_progress(db) is None
        tracking.backfill_progress(db, [(1.0, 1, 10, None, 0)])
        tracking.add_progress_row(db, 2.0, (2, 11, 20, 0, 1, 0))
        assert tracking.has_progress(db)
        assert tracking.last_progress(db) == (2, 11, 20, 0, 1, 0)
        assert [tuple(row) for row in tracking.progress_history(db)] == [
            (1.0, 1, 10, None, 0, None, None), (2.0, 2, 11, 20, 0, 1, 0)]
        for ts in range(3, 1300):
            tracking.add_progress_row(db, float(ts), (8, ts, ts, 0, 0, 0))
        rows = tracking.progress_history(db)
        shown = progress.history(db)
    # 1299 rows thin to the first row and the newest of each span of 3.
    assert len(rows) == 434
    assert rows[0][0] == 1.0 and rows[-1][0] == 1299.0
    assert [row['ts'] for row in shown] == [row[0] for row in rows]
    assert shown[-1] == dict(zip(('ts', *tracking.PROGRESS_FIELDS), rows[-1]))


def test_the_journal_reads_every_entry_in_order(store):
    with store.transaction() as db:
        first = journal.add(db, 1.0, 'badge', 'Boulder Badge', '1 badges', 1, 4, 'PEWTER CITY')
        second = journal.add(db, 2.0, 'catch', 'Caught Pikachu', '12 owned', 1, 3, 'VIRIDIAN FOREST')
    with store.reading() as db:
        assert [tuple(row) for row in journal.every_entry(db)] == [
            (first, 1.0, 'badge', 'Boulder Badge', '1 badges'), (second, 2.0, 'catch', 'Caught Pikachu', '12 owned')]


def test_a_pair_trade_and_a_pair_gift_complete_once(store):
    with store.transaction() as db:
        assert ledgers.complete_pair_trade(db, 'trade:7') is True
        assert ledgers.complete_pair_trade(db, 'trade:7') is False
        assert ledgers.complete_pair_event(db, '7') is True
        assert ledgers.complete_pair_event(db, '7') is False
