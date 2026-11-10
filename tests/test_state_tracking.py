"""Slice R2 of docs/design/adventure-state-store.md: the trackers keep no SQL of their own.

The catch, shiny, statistics, tally and record trackers of both generations decide what to count.
They pass the handle ``Store.transaction()`` or ``Store.reading()`` yields to pokesim/state/kv.py
and pokesim/state/tracking.py, which hold every statement.
"""
import ast
from contextlib import closing
from pathlib import Path

import pytest

from pokesim.state import kv, tracking
from pokesim.store import Store

PACKAGE = Path(__file__).resolve().parents[1] / 'pokesim'
TRACKERS = ('shiny.py', 'catches.py', 'statistics.py', 'milestones.py', 'adventure_counters.py',
            'catch_rates.py', 'adventure_records.py', 'money_flow.py', 'gen2/tracking.py', 'gen2/statistics.py')
# A tracker that reaches past pokesim.state names one of these.
RAW = {'execute', 'executemany', 'executescript', 'db', 'lock', 'connect'}


@pytest.mark.parametrize('name', TRACKERS)
def test_a_tracker_reaches_the_database_only_through_pokesim_state(name):
    tree = ast.parse((PACKAGE / name).read_text(encoding='utf-8'))
    raw = [f'{name}:{node.lineno} .{node.attr}' for node in ast.walk(tree)
           if isinstance(node, ast.Attribute) and node.attr in RAW]
    raw += [f'{name}:{node.lineno} import sqlite3' for node in ast.walk(tree)
            if isinstance(node, ast.Import) and any(alias.name == 'sqlite3' for alias in node.names)]
    assert raw == [], 'Put the statement in pokesim/state/tracking.py, or use pokesim/state/kv.py for a kv value.'


@pytest.fixture
def store(tmp_path):
    with closing(Store(tmp_path)) as store:
        yield store


def test_the_kv_helpers_add_only_once_and_put_over(store):
    with store.transaction() as db:
        assert kv.get(db, 'r2-probe', 'none') == 'none' and not kv.exists(db, 'r2-probe')
        kv.add(db, 'r2-probe', {'n': 1})
        kv.add(db, 'r2-probe', {'n': 2})
        assert kv.get(db, 'r2-probe') == {'n': 1}
        kv.put(db, 'r2-probe', {'n': 3})
        kv.update(db, 'r2-probe', {'n': 4})
        kv.update(db, 'r2-absent', {'n': 5})
    assert store.get('r2-probe') == {'n': 4} and store.get('r2-absent') is None


def test_a_transaction_commits_together_or_not_at_all(store):
    with pytest.raises(RuntimeError), store.transaction() as db:
        kv.put(db, 'r2-probe', True)
        assert tracking.add_capture(db, 'probe', 25, 10.0)
        raise RuntimeError
    with store.reading() as db:
        assert not kv.exists(db, 'r2-probe')
        assert tracking.captures_between(db, 0, 20) == 0


def test_a_capture_receipt_counts_once(store):
    with store.transaction() as db:
        assert tracking.add_capture(db, 'probe', 25, 10.0) is True
        assert tracking.add_capture(db, 'probe', 25, 11.0) is False
    with store.reading() as db:
        assert tracking.has_capture_receipts(db)
        assert tracking.captures_between(db, 0, 20) == 1
        assert tracking.captures_between(db, 11, 20) == 0
        assert not tracking.undated_gifts(db)


@pytest.mark.parametrize('generation', (1, 2))
def test_shiny_receipts_come_newest_first_with_undated_ones_last(store, generation):
    with store.transaction() as db:
        assert tracking.add_shiny(db, generation, 'seen', 'a', 10, 5.0)
        assert tracking.add_shiny(db, generation, 'acquired', 'b', 11, 7.0)
        assert tracking.add_shiny(db, generation, 'seen', 'c', 12, None)
        assert not tracking.add_shiny(db, generation, 'seen', 'a', 10, 9.0)
        rows = [tuple(row) for row in tracking.shiny_receipts(db, generation, 10)]
    assert rows == [('acquired', 11, 7.0), ('seen', 10, 5.0), ('seen', 12, None)]


def test_a_record_is_dated_only_from_a_progress_column(store):
    with store.reading() as db, pytest.raises(ValueError):
        tracking.first_progress(db, 'ts; DROP TABLE progress', 1)
