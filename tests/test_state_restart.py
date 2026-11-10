"""An owner restart starts the next game in one transaction: the old game whole, or the new game whole."""
import json

import pytest

from pokesim.state import domains
from pokesim.store import Store

OLD = {'league-rewards-v1': {'earned': 3, 'delivered': 2}, 'capture-statistics-v1': {'total': 40},
       'policy_state': {'goal': 'old'}, 'trade_offer:abc': {'state': 'keep'},
       'boss_losses': {'giovanni': 30}, 'trade_barrier': 'trade-1', 'gen2-mythical-gift-v1': {'id': 'gift'}}


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path)
    for key, value in OLD.items():
        store.set(key, value)
    with store.db:
        store.db.execute("INSERT INTO capture_receipts VALUES ('receipt', 16, 1.0)")
        store.db.execute("INSERT INTO pokemon_trade_receipts VALUES ('trade-1', 1, 1)")
    for index in range(3):
        store.write_checkpoint(b'state', {'index': index})
    store.before = rows(store)
    yield store
    store.close()


def rows(store):
    return {row[0]: json.loads(row[1]) for row in store.db.execute('SELECT k, v FROM kv')}


def count(store, table):
    return store.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]


def test_a_restart_empties_what_the_new_game_would_contradict_and_keeps_the_lifetime(store):
    store.restart(1, {'capture-statistics-v1': {'total': 0}, 'policy_state': {}})
    values = rows(store)
    assert values['capture-statistics-v1'] == {'total': 0} and values['policy_state'] == {}
    assert 'league-rewards-v1' not in values and 'trade_offer:abc' not in values
    assert values['boss_losses'] == {'giovanni': 30} and values['trade_barrier'] == 'trade-1'
    assert values['gen2-mythical-gift-v1'] == {'id': 'gift'}, 'a Gen I restart leaves a Gen II row alone'
    assert domains.RESTART_PENDING not in values
    assert count(store, 'capture_receipts') == 0 and count(store, 'pokemon_trade_receipts') == 1
    assert store.autosaves() == []


def test_the_generations_reset_their_own_rows(store):
    store.restart(2, {})
    assert 'gen2-mythical-gift-v1' not in rows(store)


def test_a_restart_names_only_what_it_resets(store):
    with pytest.raises(ValueError, match='boss_losses'):
        store.restart(1, {'boss_losses': {}})
    assert rows(store) == store.before and len(store.autosaves()) == 3


def test_a_failure_inside_the_transaction_leaves_the_old_game_whole(store):
    with pytest.raises(TypeError):
        store.restart(1, {'policy_state': {'not json': object()}})
    assert rows(store) == store.before
    assert count(store, 'capture_receipts') == 1 and len(store.autosaves()) == 3
    assert not store.db.in_transaction


def test_a_crash_after_the_commit_starts_the_new_game_when_the_store_opens(store, monkeypatch, tmp_path):
    def crash():
        raise OSError('power lost')
    monkeypatch.setattr(store.checkpoints, 'drop_autosaves', crash)
    with pytest.raises(OSError):
        store.restart(1, {})
    assert rows(store)[domains.RESTART_PENDING] is True and len(store.autosaves()) == 3
    store.close()
    reopened = Store(tmp_path)
    try:
        assert reopened.autosaves() == [] and domains.RESTART_PENDING not in rows(reopened)
        assert 'league-rewards-v1' not in rows(reopened)
    finally:
        reopened.close()


def test_a_read_only_store_refuses_a_restart(store, tmp_path):
    viewer = Store(tmp_path, read_only=True)
    try:
        with pytest.raises(PermissionError):
            viewer.restart(1, {})
    finally:
        viewer.close()


def test_durable_puts_the_connection_setting_back(store):
    store.db.execute('PRAGMA synchronous=NORMAL')
    with store.durable() as db:
        assert db.execute('PRAGMA synchronous').fetchone()[0] == 2
        db.execute("INSERT INTO kv VALUES ('x', '1')")
    assert store.db.execute('PRAGMA synchronous').fetchone()[0] == 1
    assert store.get('x') == 1


def test_durable_rolls_back_on_an_error(store):
    with pytest.raises(RuntimeError), store.durable() as db:
        db.execute("INSERT INTO kv VALUES ('x', '1')")
        raise RuntimeError
    assert store.get('x') is None and not store.db.in_transaction


def test_each_restart_resets_every_rewinding_and_restarting_domain_of_its_generation():
    for generation in (1, 2):
        names = {domain.key for domain in domains.restarted(generation)}
        assert 'policy_state' in names and 'capture_receipts' in names and 'trade_offer:' in names
        assert not names & {'adventure-counters-v1', 'trade_barrier', 'custom-reward-barrier-v1', 'events'}
    assert 'gen2-mythical-gift-v1' not in {domain.key for domain in domains.restarted(1)}
