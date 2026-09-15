import hashlib
import json

import pytest

from pokesim.runtime.reward_delivery import BARRIER, PENDING, recover_storage
from pokesim.store import Store
from pokesim import rewards


def committed(store, *, raw=b'committed-checkpoint'):
    identifier = 'reward-1'
    directory = store.dir / 'custom-rewards' / identifier
    directory.mkdir(parents=True)
    (directory / 'result.state').write_bytes(raw)
    record = {'id': identifier, 'decision': 'COMMIT', 'phase': 'committed',
              'sha256': hashlib.sha256(raw).hexdigest(), 'trade_id': 'trade-previous',
              'metadata': {'format': 1, 'sha256': hashlib.sha256(raw).hexdigest(),
                           'reward_id': identifier, 'trade_id': 'trade-previous',
                           'policy_state': {}, 'run_memory': {}}}
    store.set(PENDING, record)
    store.set(BARRIER, identifier)
    store.set('trade_barrier', 'trade-previous')
    store.set(rewards.KEY, {'earned': 3, 'delivered': 1, 'seed': 'stable'})
    return record


def test_committed_reward_recovers_once_and_preserves_high_water(tmp_path):
    store = Store(tmp_path)
    try:
        committed(store)
        path = recover_storage(store)
        assert path.read_bytes() == b'committed-checkpoint'
        assert store.checkpoint_metadata(path)['reward_id'] == 'reward-1'
        assert store.get(PENDING)['phase'] == 'complete'
        assert rewards.status(store) == {'earned': 3, 'delivered': 1, 'pending': 2}
        path.unlink()
        # Completion must not recreate a superseded checkpoint after later play.
        assert recover_storage(store) is None
        assert not path.exists()
    finally:
        store.close()


def test_precommit_stage_never_becomes_a_startup_checkpoint(tmp_path):
    store = Store(tmp_path)
    try:
        record = committed(store)
        store.set(PENDING, {**record, 'decision': None, 'phase': 'staged'})
        assert recover_storage(store) is None
        assert not store.autosaves()
        assert store.get(PENDING) is None
    finally:
        store.close()


def test_reward_recovery_refuses_corruption_and_newer_trade(tmp_path):
    store = Store(tmp_path)
    try:
        committed(store)
        store.set('trade_barrier', 'newer-trade')
        with pytest.raises(ValueError, match='newer trade'):
            recover_storage(store)
        store.set('trade_barrier', 'trade-previous')
        (tmp_path / 'custom-rewards' / 'reward-1' / 'result.state').write_bytes(b'broken')
        with pytest.raises(ValueError, match='verification'):
            recover_storage(store)
        assert not store.autosaves()
        assert store.get(PENDING)['phase'] == 'committed'
    finally:
        store.close()
