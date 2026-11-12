from dataclasses import replace
import json
import sqlite3

import pytest

from pokesim.policies.navigation import Navigator
from pokesim.store import Store
from test_events import snap
from test_strategy import mon


def state(nav):
    return (nav.tile_overrides, nav.closed_passages, nav.story_blocks,
            nav.cleared_objects, nav.can_surf, nav.can_cut)


def test_story_reuse_preserves_mutations_input_changes_and_restore(monkeypatch):
    cached, reference = Navigator(), Navigator()
    reference._cache_story = False
    calls = []
    rebuild = cached._rebuild_story
    def record(*args, **kwargs):
        calls.append(1)
        return rebuild(*args, **kwargs)
    monkeypatch.setattr(cached, '_rebuild_story', record)
    original = snap(party=(mon(moves=(15, 57, 70, 0)),))
    samples = [original, original, replace(original, badges=18),
               replace(original, map=61), replace(original, saffron_open=True),
               replace(original, party=(mon(moves=(0, 0, 0, 0)),)),
               replace(original, items=((30, 1),)),
               replace(original, event_flags=bytes([255]) * 320),
               replace(original, hidden_objects=bytes([255]) * 32)]
    for sample in samples:
        for nav in (cached, reference):
            nav.tile_overrides[(999, 1, 1)] = 42
            nav.story_blocks.add((999, 1, 1))
            nav.closed_passages.add((999, 1, 1))
            nav.cleared_objects.add((999, 1, 1))
            nav.path.append('stale')
            nav.update_story(sample)
        assert state(cached) == state(reference)
        assert cached.path == reference.path
    assert len(calls) == len(samples) - 1
    cached.restore()
    cached.update_story(samples[-1])
    assert len(calls) == len(samples)
    cached.update_story(samples[-1], allow_remote_puzzles=False)
    reference.update_story(samples[-1], allow_remote_puzzles=False)
    assert state(cached) == state(reference)


def test_scoped_reads_are_detached_and_direct_writes_invalidate(tmp_path):
    store = Store(tmp_path)
    key = 'cartridge-steps-v1'
    store.set(key, {'total': 1, 'nested': [1]})
    queries = []
    store.db.set_trace_callback(queries.append)
    with store.observation_reads():
        first = store.get(key)
        first['nested'].append(2)
        assert store.get(key) == {'total': 1, 'nested': [1]}
        assert sum(q.startswith('SELECT v FROM kv') for q in queries) == 1
        with store.lock, store.db:
            store.db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps({'total': 2}), key))
        assert store.get(key) == {'total': 2}
        assert store.get('mew-returns-v1', 1) == 1
        assert store.get('mew-returns-v1', 2) == 2
    store.close()


def test_rollback_external_commit_and_trade_reads_remain_visible(tmp_path):
    store = Store(tmp_path)
    key = 'cartridge-steps-v1'
    store.set(key, {'total': 1})
    with store.observation_reads():
        assert store.get(key)['total'] == 1
        with pytest.raises(RuntimeError), store.db:
            store.db.execute('UPDATE kv SET v=? WHERE k=?', ('{"total":2}', key))
            assert store.get(key)['total'] == 2
            raise RuntimeError('rollback')
        assert store.get(key)['total'] == 1
        assert store.get('trade_hold') is None
        with sqlite3.connect(tmp_path / 'pokesim.sqlite') as external:
            external.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', ('trade_hold', 'true'))
            external.execute('UPDATE kv SET v=? WHERE k=?', ('{"total":3}', key))
        assert store.get('trade_hold') is True
    with store.observation_reads():
        assert store.get(key)['total'] == 3
    with sqlite3.connect(tmp_path / 'pokesim.sqlite') as external:
        external.execute('UPDATE kv SET v=? WHERE k=?', ('{"total":4}', key))
    assert store.get(key)['total'] == 4
    store.close()


def test_trade_settings_and_league_marks_are_read_again_only_after_a_change(tmp_path):
    """A Gen II PC decision reads both once per boxed egg, so they are kept until the database changes."""
    from pokesim import rewards
    from pokesim.state import claims
    store = Store(tmp_path)
    store.set('trade_offer:a', {'state': 'never'})
    queries = []
    store.db.set_trace_callback(queries.append)
    first = store.trade_preferences()
    first['a']['state'] = 'changed'
    assert store.trade_preferences() == {'a': {'state': 'never'}}
    assert store.league_marks(2) == store.league_marks(2) == frozenset()
    assert sum('FROM kv WHERE substr' in q for q in queries) == 1
    assert sum('FROM claims' in q for q in queries) == 1
    store.set('trade_offer:b', {'state': 'first'})
    assert set(store.trade_preferences()) == {'a', 'b'}
    with store.transaction():
        claims.put(store.db, rewards.SOURCE, 'seed-1', claims.DELIVERED, seed='seed-1')
        assert len(store.league_marks(2)) == 1
    assert store.league_marks(2) == rewards.marks(store.db, 2)
    external = sqlite3.connect(tmp_path / 'pokesim.sqlite')
    with external:
        external.execute('DELETE FROM kv WHERE k=?', ('trade_offer:a',))
        claims.put(external, rewards.SOURCE, 'seed-2', claims.DELIVERED, seed='seed-2')
    external.close()
    assert set(store.trade_preferences()) == {'b'}
    assert len(store.league_marks(2)) == 2 and store.league_marks(2) == rewards.marks(store.db, 2)
    store.close()
