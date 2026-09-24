import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim.app.registry import identifier
from pokesim.runtime.participant import (PREFIX, _compact_released, _promote, _records,
                                          recover_storage, Participant)
from pokesim.store import Store


def committed(store):
    tid = identifier()
    stage = store.dir / 'interactions' / tid
    stage.mkdir(parents=True)
    raw = b'complete-private-checkpoint'
    path = stage / 'staged.state'
    path.write_bytes(raw)
    result = {'id': tid, 'decision': 'COMMIT', 'phase': 'committed', 'source_name': 'source.state',
              'source_metadata': {'format': 1, 'policy_state': {}, 'run_memory': {}},
              'staged': {'state_path': str(path), 'checkpoint_sha256': hashlib.sha256(raw).hexdigest()}}
    store.set(PREFIX + tid, result)
    return result


def test_recovery_publishes_only_committed_state_once(tmp_path):
    store = Store(tmp_path)
    record = committed(store)
    recover_storage(store)
    path = store.latest_state()
    assert store.checkpoint_metadata(path)['trade_id'] == record['id']
    assert store.get('trade_barrier') == record['id']
    assert len(store.events(types=['trade'])) == 1
    recover_storage(store)
    assert len(store.events(types=['trade'])) == 1
    assert store.get('trade_hold')['id'] == record['id']
    store.close()


@pytest.mark.parametrize('map_id,location', [(174, 'Indigo Plateau lobby'),
                                           (89, 'Vermilion Pokémon Center'),
                                           (None, 'Pokémon Center')])
def test_trade_journal_uses_the_owning_adventures_center(tmp_path, map_id, location):
    store = Store(tmp_path)
    try:
        record = committed(store)
        if map_id is not None:
            record['source_center_map'] = map_id
        _promote(store, record)
        assert store.events(types=['trade'])[0]['map'] == location
    finally:
        store.close()


def test_uncommitted_files_never_become_autosaves(tmp_path):
    store = Store(tmp_path)
    record = committed(store)
    record.update(decision=None, phase='staged')
    store.set(PREFIX + record['id'], record)
    recover_storage(store)
    assert store.latest_state() is None
    assert store.get('trade_hold')['id'] == record['id']
    with pytest.raises(ValueError, match='commit'):
        _promote(store, record)
    store.close()


def test_released_trade_cannot_rewind_later_gameplay(tmp_path):
    store = Store(tmp_path)
    record = committed(store)
    recover_storage(store)
    record['phase'] = 'released'
    store.set(PREFIX + record['id'], record)
    newer = store.write_checkpoint(b'newer-gameplay', {'policy_state': {}, 'run_memory': {}, 'trade_id': record['id']})
    before = newer.read_bytes()
    recover_storage(store)
    assert store.latest_state() == newer
    assert newer.read_bytes() == before
    store.close()


def test_damaged_commit_fails_closed_without_barrier_change(tmp_path):
    store = Store(tmp_path)
    record = committed(store)
    Path(record['staged']['state_path']).write_bytes(b'damaged')
    with pytest.raises(ValueError, match='checksum'):
        recover_storage(store)
    assert store.get('trade_barrier') is None
    assert not store.autosaves()
    store.close()


def test_abort_recovery_clears_only_its_own_hold(tmp_path):
    store = Store(tmp_path)
    tid = identifier()
    record = {'id': tid, 'decision': 'ABORT', 'phase': 'aborting'}
    store.set(PREFIX + tid, record)
    store.set('trade_hold', {'id': tid, 'phase': 'prepared'})
    store.set('interaction_preparation', {'id': tid, 'phase': 'ready'})
    recover_storage(store)
    assert store.get('trade_hold') is None
    assert store.get('interaction_preparation') is None
    assert store.get(PREFIX + tid)['phase'] == 'aborted'
    store.close()


def test_abort_before_prepare_leaves_a_permanent_tombstone(tmp_path):
    store = Store(tmp_path)
    participant = Participant(SimpleNamespace(store=store, emulator=None), SimpleNamespace())
    tid = identifier()
    assert participant.abort({'id': tid})['phase'] == 'aborted'
    assert store.get(PREFIX + tid)['decision'] == 'ABORT'
    with pytest.raises(ValueError, match='parameters changed'):
        participant.prepare({'id': tid, 'plan_digest': 'late', 'selected_key': 'late'})
    store.close()


def test_startup_never_reads_finished_exchanges(tmp_path):
    """A released record holds a whole policy snapshot and recovery acts on none of it."""
    store = Store(tmp_path)
    record = committed(store)
    record['phase'] = 'released'
    store.set(PREFIX + record['id'], record)
    pending = {'id': identifier(), 'decision': None, 'phase': 'preparing'}
    store.set(PREFIX + pending['id'], pending)
    assert [row['id'] for row in _records(store)] == [pending['id']]
    store.close()


def test_release_drops_the_staged_snapshot(tmp_path):
    store = Store(tmp_path)
    record = committed(store)
    recover_storage(store)
    participant = Participant(SimpleNamespace(store=store, emulator=None),
                              SimpleNamespace())
    participant.emu = SimpleNamespace(paused=True, policy=SimpleNamespace(on_restore=lambda: None),
                                      stuck_since=0)
    store.set(PREFIX + record['id'], {**store.get(PREFIX + record['id']), 'phase': 'applied'})
    released = participant.release({'id': record['id']})
    assert released['phase'] == 'released'
    assert 'source_metadata' not in store.get(PREFIX + record['id'])
    store.close()


def test_compaction_only_strips_released_snapshots(tmp_path):
    store = Store(tmp_path)
    stale = committed(store)
    stale['phase'] = 'released'
    store.set(PREFIX + stale['id'], stale)
    live = committed(store)
    _compact_released(store)
    assert 'source_metadata' not in store.get(PREFIX + stale['id'])
    assert store.get(PREFIX + live['id'])['source_metadata'] == live['source_metadata']
    store.close()


def test_a_busy_emulator_answers_retryable_rather_than_internal_error(tmp_path):
    """runtime.call raises TimeoutError when the emulator thread is still busy.

    TimeoutError is an OSError, not a RuntimeError, so it escaped the handler's tuple and
    surfaced as a 500 with a traceback, even though its own message asks the caller to
    retry the same operation. This drives the real route, not a copy of it.
    """
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pokesim.runtime.participant import install

    app = FastAPI()
    app.state.bootstrap = {'adventure_id': 'a' * 32, 'generation': 'b' * 32,
                           'settings': {'data_dir': str(tmp_path)}}
    store = SimpleNamespace(dir=tmp_path, get=lambda key: None, set=lambda key, value: None)

    def call(function, timeout=30):
        raise TimeoutError('The operation is still pending. Retry the same operation ID.')

    install(app, SimpleNamespace(call=call, store=store, emulator=SimpleNamespace()))
    response = TestClient(app).post('/internal/participant/stage', json={})
    assert response.status_code == 409, response.text
    assert 'Retry the same operation' in response.json()['detail']


def finished(store, phase, age):
    import os
    tid = identifier()
    folder = store.dir / 'interactions' / tid
    folder.mkdir(parents=True)
    (folder / 'staged.state').write_bytes(b'x' * 64)
    os.utime(folder, (age, age))
    store.set(PREFIX + tid, {'id': tid, 'phase': phase, 'decision': 'COMMIT' if phase == 'released' else 'ABORT',
                             'source_metadata': {'policy_state': 'p' * 4096}})
    return tid


def test_startup_keeps_only_the_newest_finished_exchange_folders(tmp_path):
    from pokesim.runtime.participant import _prune_finished
    store = Store(tmp_path)
    try:
        old = [finished(store, phase, 1000 + index) for index, phase in enumerate(['released', 'aborted'] * 3)]
        live = committed(store)['id']
        stray = store.dir / 'interactions' / 'no-record'
        stray.mkdir()
        assert _prune_finished(store, keep=2) == 4
        left = {path.name for path in (store.dir / 'interactions').iterdir()}
        assert left == {old[-2], old[-1], live, 'no-record'}
        assert _prune_finished(store, keep=0) == 0
    finally:
        store.close()


def test_aborted_exchanges_lose_their_snapshot_like_released_ones(tmp_path):
    store = Store(tmp_path)
    try:
        tids = [finished(store, phase, 1000) for phase in ('released', 'aborted')]
        live = committed(store)['id']
        _compact_released(store)
        assert all('source_metadata' not in store.get(PREFIX + tid) for tid in tids)
        assert 'source_metadata' in store.get(PREFIX + live)
    finally:
        store.close()


def test_startup_gives_back_a_large_amount_of_free_database_space(tmp_path):
    from pokesim.runtime.participant import _reclaim
    store = Store(tmp_path)
    try:
        path = store.dir / 'pokesim.sqlite'
        for index in range(40):
            store.set(f'bulk:{index}', 'x' * 100_000)
        store.db.execute("DELETE FROM kv WHERE k LIKE 'bulk:%'")
        store.db.commit()
        grown = path.stat().st_size
        assert _reclaim(store, threshold=10 ** 9) == 0 and path.stat().st_size == grown
        assert _reclaim(store, threshold=2 ** 20) > 2 ** 20
        assert path.stat().st_size < grown / 4
        store.set('after', 1)
        assert store.get('after') == 1
    finally:
        store.close()
