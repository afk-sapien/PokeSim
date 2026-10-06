"""Completed exchanges count once, including the verified received evolution."""
from contextlib import closing
import json
from types import SimpleNamespace

import pytest

from pokesim import activity_ledger, trade_statistics
from pokesim.app.registry import identifier
from pokesim.runtime.participant import PREFIX, Participant
from pokesim.store import Store
from pokesim.strategy_data import SPECIES


def sid(dex):
    return next(species for species, mon in SPECIES.items() if mon['dex'] == dex)


def completed(*, phase='released', decision='COMMIT', tid=None, final=True):
    raw = bytes((sid(64),)) + bytes(43)
    return {'id': tid or identifier(), 'decision': decision, 'phase': phase,
            'outgoing': {'struct': raw.hex()},
            'incoming': {'struct': (bytes((sid(93),)) + bytes(43)).hex()},
            'staged': {'evidence': {'received_species': sid(94)} if final else {}}}


def totals(store, dex):
    return next(row for row in activity_ledger.status(store)['pokemon'] if row['id'] == dex)


def test_released_trades_count_final_form_once_without_counting_catches(tmp_path):
    with closing(Store(tmp_path)) as store:
        receipt = completed()
        for _ in range(2):
            with store.db:
                trade_statistics.managed(store.db, receipt)
        assert totals(store, 64)['traded_out'] == 1
        assert totals(store, 94)['traded_in'] == 1
        assert totals(store, 93)['traded_in'] == 0
        assert totals(store, 94)['gift'] == 0
        assert totals(store, 94)['caught'] is None
        with store.db:
            trade_statistics.managed(store.db, completed())
        assert totals(store, 94)['traded_in'] == 2


@pytest.mark.parametrize('phase,decision', [('prepared', None), ('staged', None),
    ('committed', 'COMMIT'), ('applied', 'COMMIT'), ('aborted', 'ABORT'), ('released', 'ABORT')])
def test_unfinished_or_aborted_trades_do_not_count(tmp_path, phase, decision):
    with closing(Store(tmp_path)) as store:
        with store.db:
            trade_statistics.managed(store.db, completed(phase=phase, decision=decision))
        assert totals(store, 64)['traded_out'] == totals(store, 94)['traded_in'] == 0


def test_migration_recovers_verified_records_and_marks_missing_history(tmp_path):
    with closing(Store(tmp_path)) as store:
        for receipt in [completed(), completed(final=False), completed(phase='applied'), completed(decision='ABORT')]:
            store.set(PREFIX + receipt['id'], receipt)
        with store.db:
            store.db.execute('DELETE FROM kv WHERE k=?', (trade_statistics.KEY,))
    for _ in range(2):
        with closing(Store(tmp_path)) as store:
            assert totals(store, 64)['traded_out'] == 1
            assert totals(store, 94)['traded_in'] == 1
            assert totals(store, 93)['traded_in'] == 0
            assert store.get(trade_statistics.KEY)['missing_history'] == 1
            store.prune_events(0)
            with store.db:
                store.db.execute("DELETE FROM kv WHERE k LIKE 'managed_interaction:%'")


def participant(store):
    result = Participant(SimpleNamespace(store=store, emulator=None), SimpleNamespace())
    result.emu = SimpleNamespace(paused=True, policy=SimpleNamespace(on_restore=lambda: None), stuck_since=0)
    return result


def test_release_commits_counter_and_state_together_and_retries_are_inert(tmp_path):
    with closing(Store(tmp_path)) as store:
        receipt = completed(phase='applied')
        store.set(PREFIX + receipt['id'], receipt)
        store.set('trade_hold', {'id': receipt['id']})
        worker = participant(store)
        for _ in range(2):
            worker.release({'id': receipt['id']})
        assert store.get(PREFIX + receipt['id'])['phase'] == 'released'
        assert store.get('trade_hold') is None
        assert totals(store, 64)['traded_out'] == totals(store, 94)['traded_in'] == 1


def test_failed_count_write_preserves_hold_and_rolls_back_both_counters(tmp_path, monkeypatch):
    with closing(Store(tmp_path)) as store:
        receipt = completed(phase='applied')
        store.set(PREFIX + receipt['id'], receipt)
        store.set('trade_hold', {'id': receipt['id']})
        original = trade_statistics.increment
        def fail_second(db, kind, subject):
            if kind == 'traded_in':
                raise RuntimeError('Simulated write failure')
            original(db, kind, subject)
        monkeypatch.setattr(trade_statistics, 'increment', fail_second)
        with pytest.raises(RuntimeError, match='write failure'):
            participant(store).release({'id': receipt['id']})
        assert store.get(PREFIX + receipt['id'])['phase'] == 'applied'
        assert store.get('trade_hold')['id'] == receipt['id']
        assert totals(store, 64)['traded_out'] == 0
        assert store.db.execute('SELECT COUNT(*) FROM pokemon_trade_receipts').fetchone()[0] == 0


def test_npc_success_repeats_and_post_evolution_species(tmp_path):
    with closing(Store(tmp_path)) as store:
        tracker = activity_ledger.ActivityLedger(store, 'unknown')
        memory = bytearray(65536)
        memory[0xd163] = 2
        memory[0xcd0f] = sid(64)
        memory[0xd16b + 44] = sid(65)
        pb = SimpleNamespace(memory=memory)
        for dialogue in (1, 2, 4):
            memory[0xcd12] = dialogue
            tracker.completed(('npc_trade', pb))
        assert totals(store, 64)['traded_out'] == 0
        memory[0xcd12] = 3
        tracker.completed(('npc_trade', pb))
        tracker.completed(('npc_trade', pb))
        assert totals(store, 64)['traded_out'] == 1
        assert totals(store, 65)['traded_in'] == 1
        memory[0xda44] = 1
        tracker.completed(('npc_trade', pb))
        assert totals(store, 65)['traded_in'] == 2
        memory[0xd12b] = 1
        memory[0xda44] = 2
        tracker.completed(('npc_trade', pb))
        assert totals(store, 65)['traded_in'] == 2


def test_legacy_completed_journal_updates_once(tmp_path, monkeypatch):
    from pokesim.trade import pair
    root = tmp_path / 'coordinator'
    folder = root / 'transactions' / '42'
    folder.mkdir(parents=True)
    peer = tmp_path / 'red'
    monkeypatch.setattr(pair, 'PAIR_ROOT', tmp_path)
    with closing(Store(peer)) as store:
        row = {'instance': 'red', 'sent': {'species': sid(64), 'nick': 'GONE'},
               'received': {'species': sid(65), 'nick': 'HERE', 'name': 'Alakazam', 'level': 30, 'evolved_from': sid(64)}}
        (folder / 'result.json').write_text(json.dumps({'moved': [row], 'reason': 'Verified exchange'}))
        pair.journal(root, '42')
        pair.journal(root, '42')
        assert totals(store, 64)['traded_out'] == 1
        assert totals(store, 65)['traded_in'] == 1
        assert len(store.events(types=['trade'])) == 1
