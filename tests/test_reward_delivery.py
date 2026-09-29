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


@pytest.mark.parametrize('kind', ['league_reward', 'mew_event', 'mew_return'])
@pytest.mark.parametrize('fail_receipt', [False, True])
def test_delivery_counts_gift_atomically_with_ownership(tmp_path, monkeypatch, fail_receipt, kind):
    import sqlite3
    from pokesim import ram
    from pokesim.catches import CatchTracker, SUPPORTED, status
    from pokesim.runtime import reward_delivery
    from test_trade_save import Memory, populate

    store = Store(tmp_path)
    try:
        CatchTracker(store, sorted(SUPPORTED)[0])
        rewards.earn(store, 1)
        before = snap(hall_of_fame_count=1, box_counts=(0,) * 12)
        memory = populate(Memory(), contents=())
        clone_memory = populate(Memory(), contents=())
        species = select_reward(before, rewards.ledger(store.db), True, league_rewards=True)[2] if kind == 'league_reward' else 21
        if kind == 'mew_return':
            from pokesim import mew_returns
            from pokesim.legendary_returns import STEPS
            store.set('pokesim-mew-v1', 'previous-Mew')
            store.set(STEPS, {'available': True, 'total': 1000000})
            store.set(mew_returns.KEY, {'interval': 1000000, 'next_at': 1000000, 'armed_after_win': 0, 'delivered': 0})
        from pokesim.strategy_data import SPECIES
        after = replace(before, box_counts=(1,) + (0,) * 11, owned=before.owned | {SPECIES[species]['dex']})
        monkeypatch.setattr(ram, 'read_snapshot', lambda mem, _: before if mem is memory else after)
        clone = SimpleNamespace(memory=clone_memory, load_state=lambda _: None,
                                save_state=lambda stream: stream.write(b'reward-checkpoint'), stop=lambda **_: None)
        monkeypatch.setattr(store, 'latest_state', lambda: tmp_path / 'source.state')
        monkeypatch.setattr(store, 'checkpoint_metadata', lambda _: {'run_memory': {}})
        emu = SimpleNamespace(store=store, paused=False, manual_mode=False, pb=SimpleNamespace(memory=memory),
                              frame=100, _state_bytes=lambda: b'source', _autosave=lambda: None,
                              _boot=lambda: clone, _load_state_file=lambda _: None,
                              policy=SimpleNamespace(on_restore=lambda: None), input_epoch=0)
        if fail_receipt:
            store.db.execute("CREATE TRIGGER reject_gift BEFORE INSERT ON capture_receipts "
                             "BEGIN SELECT RAISE(ABORT, 'receipt failed')" + chr(59) + " END")
            with pytest.raises(sqlite3.IntegrityError, match='receipt failed'):
                deliver(emu, league_rewards=kind == 'league_reward', mew_event=kind != 'league_reward')
            assert rewards.status(store)['delivered'] == 0
            assert status(store)['total'] == 0
            assert store.events() == []
            assert store.get(PENDING)['decision'] is None
            if kind == 'mew_return':
                assert mew_returns.ready(store, 1)
        else:
            result = deliver(emu, league_rewards=kind == 'league_reward', mew_event=kind != 'league_reward')
            assert result['decision'] == 'COMMIT'
            assert rewards.status(store)['delivered'] == (1 if kind == 'league_reward' else 0)
            if kind == 'mew_return':
                assert not mew_returns.ready(store, 1)
                assert store.get(mew_returns.KEY)['next_at'] == 2000000
            assert status(store)['counts'] == {str(SPECIES[species]['dex']): 1}
            assert reward_delivery.recover_storage(store) is None
            CatchTracker(store, sorted(SUPPORTED)[0])
            assert status(store)['total'] == 1
    finally:
        store.close()
