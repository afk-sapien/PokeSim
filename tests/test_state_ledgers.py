"""Slice R1 of docs/design/adventure-state-store.md: the trade and reward ledgers keep no SQL of their own.

The managed exchange, the League and walking gifts, the Champion counter and the trade counts decide what
to write. They pass the handle ``Store.transaction()``, ``Store.reading()`` or ``Store.durable()`` yields
to pokesim/state/kv.py, pokesim/state/ledgers.py and pokesim/state/journal.py, which hold every statement.
"""
import ast
from contextlib import closing
from pathlib import Path

import pytest

from pokesim.state import journal, kv, ledgers
from pokesim.store import Store

PACKAGE = Path(__file__).resolve().parents[1] / 'pokesim'
LEDGERS = ('runtime/participant.py', 'rewards.py', 'runtime/reward_delivery.py', 'runtime/tm_purchase.py',
           'gen2/league.py', 'league_partners.py', 'gen2/celebi.py', 'gen2/rewards.py', 'fair_dvs.py',
           'trade_statistics.py', 'mew_returns.py', 'champion_shop.py', 'trade/partners.py')
# A ledger that reaches past pokesim.state names one of these.
RAW = {'execute', 'executemany', 'executescript', 'db', 'lock', 'connect'}


@pytest.mark.parametrize('name', LEDGERS)
def test_a_ledger_reaches_the_database_only_through_pokesim_state(name):
    tree = ast.parse((PACKAGE / name).read_text(encoding='utf-8'))
    raw = [f'{name}:{node.lineno} .{node.attr}' for node in ast.walk(tree)
           if isinstance(node, ast.Attribute) and node.attr in RAW]
    raw += [f'{name}:{node.lineno} import sqlite3' for node in ast.walk(tree)
            if isinstance(node, ast.Import) and any(alias.name == 'sqlite3' for alias in node.names)]
    assert raw == [], 'Put the statement in pokesim/state/ledgers.py, or use pokesim/state/kv.py for a kv value.'


@pytest.fixture
def store(tmp_path):
    with closing(Store(tmp_path)) as store:
        yield store


def exchanges(store):
    with store.transaction() as db:
        kv.put(db, ledgers.INTERACTIONS + 'staged', {'id': 'staged', 'phase': 'staged', 'source_metadata': {}})
        kv.put(db, ledgers.INTERACTIONS + 'new', {'id': 'new'})
        for phase in ledgers.FINISHED:
            kv.put(db, ledgers.INTERACTIONS + phase, {'id': phase, 'phase': phase, 'source_metadata': {}})


def test_an_unreleased_exchange_is_every_record_short_of_released(store):
    exchanges(store)
    with store.reading() as db:
        assert set(ledgers.unreleased(db)) == {
            '{"id": "staged", "phase": "staged", "source_metadata": {}}', '{"id": "new"}',
            '{"id": "aborted", "phase": "aborted", "source_metadata": {}}'}
        assert ledgers.finished(db) == {'released', 'aborted'}


def test_compaction_drops_the_snapshot_of_finished_exchanges_only(store):
    exchanges(store)
    with store.transaction() as db:
        ledgers.compact_finished(db, 1)
    snapshots = {name for name in ('staged', 'released', 'aborted')
                 if 'source_metadata' in store.get(ledgers.INTERACTIONS + name)}
    assert len(snapshots) == 2 and 'staged' in snapshots
    with store.transaction() as db:
        ledgers.compact_finished(db, 10)
    assert [name for name in ('staged', 'released', 'aborted')
            if 'source_metadata' in store.get(ledgers.INTERACTIONS + name)] == ['staged']


def test_a_released_trade_leaves_only_its_identity_and_species(store):
    record = {'id': 'abc', 'decision': 'COMMIT', 'phase': 'released', 'outgoing': {'struct': '99'},
              'staged': {'evidence': {'received_species': 25, 'sent_species': [1], 'received': [{'species': 4}]}}}
    with store.transaction() as db:
        kv.put(db, ledgers.INTERACTIONS + 'abc', record)
        kv.put(db, ledgers.INTERACTIONS + 'open', {**record, 'id': 'open', 'phase': 'staged'})
        rows = [tuple(row) for row in ledgers.released_trades(db)]
    assert rows == [('abc', '99', 25, '[1]', '[{"species":4}]')]


def test_a_trade_receipt_counts_once_and_older_trades_are_counted(store):
    with store.transaction() as db:
        assert ledgers.add_trade_receipt(db, 'managed:abc', 1, 4) is True
        assert ledgers.add_trade_receipt(db, 'managed:abc', 1, 4) is False
        assert ledgers.legacy_trades(db) == 0
        db.executemany('INSERT INTO completed_trades VALUES (?)', (('a',), ('b',)))
        assert ledgers.legacy_trades(db) == 2
        db.execute('DROP TABLE completed_trades')
        assert ledgers.legacy_trades(db) == 0


def test_a_journal_entry_commits_with_the_ledger_change_or_not_at_all(store):
    with store.durable() as db:
        first = journal.add(db, 1.0, 'obtain', 'Received', 'A gift', 1, 4, 'PALLET TOWN')
        second = journal.add(db, 2.0, 'trade', 'Traded', 'A trade', 1, 4, 'PALLET TOWN', detail='{"n": 1}')
        kv.put(db, 'r1-probe', first)
    assert second == first + 1 and store.get('r1-probe') == first
    with pytest.raises(RuntimeError), store.durable() as db:
        journal.add(db, 3.0, 'obtain', 'Lost', 'A gift', 1, 4, 'PALLET TOWN')
        kv.put(db, 'r1-probe', None)
        raise RuntimeError
    with store.reading() as db:
        rows = [tuple(row) for row in db.execute('SELECT type, title, map, playtime, detail FROM events ORDER BY id')]
    assert rows == [('obtain', 'Received', 'PALLET TOWN', '', None), ('trade', 'Traded', 'PALLET TOWN', '', '{"n": 1}')]
    assert store.get('r1-probe') == first


def test_free_pages_are_counted_in_bytes(store):
    with store.reading() as db:
        assert ledgers.free_bytes(db) >= 0
