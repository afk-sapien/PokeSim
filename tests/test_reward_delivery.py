import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pokesim.runtime.reward_delivery import BARRIER, PENDING, deliver, recover_storage, select_reward
from pokesim.store import Store
from pokesim import rewards
from test_events import snap
from test_strategy import flags


@pytest.mark.parametrize('progress', [
    {'hall_of_fame_count': 1},
    {'event_flags': flags('EVENT_BEAT_CHAMPION_RIVAL')},
])
def test_enabling_mew_after_the_milestone_grants_the_missed_event(progress):
    state = snap(**progress)
    ledger = {'earned': 100, 'delivered': 0, 'seed': 'stable'}
    assert select_reward(state, ledger, False) is None
    selected = select_reward(state, ledger, False, mew_event=True, league_rewards=True)
    assert selected[:3] == ('mew_event', None, 21)
    assert ledger == {'earned': 100, 'delivered': 0, 'seed': 'stable'}


def test_mew_requires_champion_and_never_reissues_after_ownership_or_receipt():
    ledger = {'earned': 0, 'delivered': 0}
    assert select_reward(snap(), ledger, False, mew_event=True) is None
    champion = snap(hall_of_fame_count=10)
    assert select_reward(champion, ledger, 'delivered-before', mew_event=True) is None
    assert select_reward(replace(champion, owned=frozenset({1, 151})), ledger, False,
                         mew_event=True) is None


def test_league_backlog_continues_after_mew_or_when_event_is_disabled():
    ledger = {'earned': 100, 'delivered': 2, 'seed': 'stable'}
    champion = snap(hall_of_fame_count=100)
    for received, enabled in [(False, False), ('delivered-before', True)]:
        selected = select_reward(champion, ledger, received, mew_event=enabled, league_rewards=True)
        assert selected[0:2] == ('league_reward', 3)


@pytest.mark.parametrize('changes', [
    {'in_battle': 1}, {'textbox': True}, {'start_menu': True}, {'box_counts': (20,) * 12},
])
def test_retroactive_mew_waits_for_safe_play_and_storage(tmp_path, monkeypatch, changes):
    from pokesim import ram
    store = Store(tmp_path)
    state = snap(hall_of_fame_count=10, **changes)
    monkeypatch.setattr(ram, 'read_snapshot', lambda *_: state)
    emu = SimpleNamespace(store=store, paused=False, manual_mode=False,
                          pb=SimpleNamespace(memory=None), frame=100)
    try:
        assert deliver(emu, mew_event=True, league_rewards=True) is None
        assert store.get(PENDING) is None
    finally:
        store.close()


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
        assert rewards.status(store) == {'earned': 3, 'delivered': 1, 'pending': 2, 'wins': 3, 'unlocks': []}
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
