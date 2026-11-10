"""Slice R3 of docs/design/adventure-state-store.md: the journal, progress and guards keep no SQL of their own.

The activity ledgers, the League history recovery, the loop guard, the progress and stall truth rows,
the goal time and Mew step counts and the shiny log on the status page decide what to read and write.
They pass the handle ``Store.transaction()`` or ``Store.reading()`` yields to pokesim/state/kv.py,
pokesim/state/journal.py and pokesim/state/tracking.py, which hold every statement.
"""
import ast
from contextlib import closing
from pathlib import Path

import pytest

from pokesim.stalls import RELOADS_KEY, LoopGuard
from pokesim.state import Error, journal, kv, tracking
from pokesim.store import Store

PACKAGE = Path(__file__).resolve().parents[1] / 'pokesim'
MODULES = ('activity_ledger.py', 'league_history.py', 'gen2/activity.py', 'stalls.py', 'progress_events.py',
           'stall_truth.py', 'web/app.py', 'goal_time.py', 'gen2/steps.py')
# A module that reaches past pokesim.state names one of these. ``self.lock`` is a class's own thread lock.
RAW = {'execute', 'executemany', 'executescript', 'db', 'lock', 'connect'}


def own_lock(node):
    return node.attr == 'lock' and isinstance(node.value, ast.Name) and node.value.id == 'self'


@pytest.mark.parametrize('name', MODULES)
def test_a_module_reaches_the_database_only_through_pokesim_state(name):
    tree = ast.parse((PACKAGE / name).read_text(encoding='utf-8'))
    raw = [f'{name}:{node.lineno} .{node.attr}' for node in ast.walk(tree)
           if isinstance(node, ast.Attribute) and node.attr in RAW and not own_lock(node)]
    raw += [f'{name}:{node.lineno} import sqlite3' for node in ast.walk(tree)
            if isinstance(node, ast.Import) and any(alias.name == 'sqlite3' for alias in node.names)]
    assert raw == [], 'Put the statement in pokesim/state/journal.py, or use pokesim/state/kv.py for a kv value.'


@pytest.fixture
def store(tmp_path):
    with closing(Store(tmp_path)) as store:
        yield store


def entry(db, kind, title):
    return journal.add(db, 1.0, kind, title, '', 0, 1, 'PALLET TOWN')


def test_the_loop_guard_scan_reads_marks_repeats_and_turnover(store):
    with store.transaction() as db:
        assert journal.marked(db, ('badge', 'release')) == (None, None)
        badge = entry(db, 'badge', 'Boulder Badge')
        obtain = entry(db, 'obtain', 'Received Mew')
        release = entry(db, 'release', 'Released Mew')
        entry(db, 'map', 'Arrived')
    with store.reading() as db:
        assert journal.marked(db, ('badge', 'release')) == (badge, release)
        assert [tuple(row) for row in journal.marked_after(db, badge, ('badge', 'obtain', 'release'))] == [
            (obtain, 'obtain', 'Received Mew'), (release, 'release', 'Released Mew')]
        assert journal.repeats(db, badge, release, 'obtain', 'Received Mew')
        assert not journal.repeats(db, release, release + 5, 'obtain', 'Received Mew')
        assert [tuple(row) for row in journal.turnover(db, 0, 1)] == [('release', 'Released Mew')]
        assert [tuple(row) for row in journal.turnover(db, 0, 5)] == [
            ('release', 'Released Mew'), ('obtain', 'Received Mew')]


def test_the_champion_entries_come_back_oldest_first(store):
    with store.transaction() as db:
        entry(db, 'badge', 'Earth Badge')
        first = entry(db, 'champion', 'Champion! League victory #1')
        second = entry(db, 'champion', 'Champion! League victory #2')
    with store.reading() as db:
        rows = journal.champions(db)
    assert [(row['id'], row['title'], row['state'], row['body']) for row in rows] == [
        (first, 'Champion! League victory #1', None, ''), (second, 'Champion! League victory #2', None, '')]


def test_progress_and_stall_truth_rows_keep_every_field(store):
    with store.transaction() as db:
        journal.add_progress(db, 60, 2.0, 'catch', 'dex', 'tier', 25, 'id', 3.5, 0)
        journal.add_stall_truth(db, 60, 2.0, 'help', 'owner', '{"a": 1}')
        journal.add_stall_truth(db, 61, 3.0, 'restart', 'boot', '{}')
    with store.reading() as db:
        progress = db.execute('SELECT frame, ts, kind, goal, tier, species, identity, score, net '
                              'FROM progress_events').fetchall()
        assert [tuple(row) for row in progress] == [(60, 2.0, 'catch', 'dex', 'tier', 25, 'id', 3.5, 0)]
        assert [tuple(row)[1:] for row in journal.stall_truth(db)] == [
            (60, 2.0, 'help', 'owner', '{"a": 1}'), (61, 3.0, 'restart', 'boot', '{}')]
        assert [tuple(row)[3] for row in journal.stall_truth(db, 'restart')] == ['restart']


def test_an_activity_receipt_counts_once_and_the_receipts_seed_the_counts(store):
    with store.transaction() as db:
        assert tracking.add_activity_receipt(db, 'wild', b'one') is True
        assert tracking.add_activity_receipt(db, 'wild', b'one') is False
        tracking.count_activity(db, 'wild', 25)
        tracking.count_activity(db, 'wild', 25, 2)
        tracking.count_activity(db, 'caught', 25)
        for fingerprint, dex in (('a', 25), ('b', 25), ('gift-event:7', 151)):
            tracking.add_capture(db, fingerprint, dex, 1.0)
        assert sorted(tuple(row) for row in tracking.receipt_counts(db)) == [('caught', 25, 2), ('gift', 151, 1)]
        tracking.forget_caught(db)
        assert tracking.activity_counts(db) == {('wild', 25): 3}


def test_the_loop_guard_keeps_its_reload_counts_and_shrugs_off_a_failed_write(store, monkeypatch):
    guard = LoopGuard(clock=lambda: 0)
    guard.reloaded('Route 1')
    guard.looping(store)
    with store.reading() as db:
        assert kv.get(db, RELOADS_KEY) == {'Route 1': 1}

    def fail(*args):
        raise Error('disk I/O error')
    monkeypatch.setattr(kv, 'put', fail)
    guard.reloaded('Route 1')
    guard._save(store)
    assert guard.saved == {'Route 1': 1}
    with store.reading() as db:
        assert kv.get(db, RELOADS_KEY) == {'Route 1': 1}
