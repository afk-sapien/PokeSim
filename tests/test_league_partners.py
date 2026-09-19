"""Individual victories survive moves, rewinds, and repeat cable exchanges."""
from dataclasses import replace

import pytest

from pokesim import league_partners as league
from pokesim.events import Event
from pokesim.ram import PartyMon, StoredMon
from pokesim.store import Store
from pokesim.trade.preferences import identity
from test_events import snap


def mon(trainer=123, **kwargs):
    return PartyMon(84, 30, 50, 20, 'SPARK', trainer_id=trainer,
                    dvs=(15, 3, 5, 7, 9), **kwargs)


def payload(*partners):
    from dataclasses import asdict
    return {'party': [asdict(p) for p in partners], 'storage': {'pokemon': []}}


def win(store, number, *partners):
    return store.add_event(Event('champion', f'Champion! League victory #{number}'),
                           snap(map=118, party=partners), None, None)


def test_party_credit_distinguishes_individuals_and_survives_restart(tmp_path):
    a, b = mon(), mon(456)
    store = Store(tmp_path)
    win(store, 1, a, b)
    win(store, 2, a)
    win(store, 2, a)
    win(store, 1, b)
    store.close()
    store = Store(tmp_path)
    result = league.apply(payload(replace(a, species=85, nick='NEW', level=50), b, mon(789)), store)
    assert [p['elite_four_wins'] for p in result['party']] == [2, 1, 0]
    store.close()


def test_fainted_party_members_count_but_boxed_partners_do_not(tmp_path):
    store = Store(tmp_path)
    a = replace(mon(), hp=0)
    boxed = StoredMon(1, 0, 84, 20, 'BOX', (), 0, a.dvs, (0,) * 5, 789)
    s = snap(map=118, party=(a,), stored_details=(boxed,),
             stored_pokemon=((1, 84, 20, 'BOX'),))
    store.add_event(Event('champion', 'Champion! League victory #1'), s, None, None)
    p = payload(a)
    from dataclasses import asdict
    p['storage']['pokemon'] = [asdict(boxed)]
    result = league.apply(p, store)
    assert result['party'][0]['elite_four_wins'] == 1
    assert result['storage']['pokemon'][0]['elite_four_wins'] == 0
    store.close()


def test_ambiguous_identical_signatures_are_never_assigned_shared_counts(tmp_path):
    store = Store(tmp_path)
    a = mon()
    win(store, 1, a, replace(a, nick='OTHER'))
    assert league.apply(payload(a), store)['party'][0]['elite_four_wins'] is None
    assert league.apply(payload(replace(a, trainer_id=None)), store)['party'][0]['elite_four_wins'] is None
    store.close()


def test_counts_follow_return_trades_without_double_credit(tmp_path):
    left, right = Store(tmp_path / 'left'), Store(tmp_path / 'right')
    a = mon()
    key = identity(payload(a)['party'][0])
    win(left, 1, a)
    for _ in range(2):
        with right.lock, right.db:
            league.merge(right.db, league.export(left, key))
    win(right, 1, a)
    for _ in range(2):
        with left.lock, left.db:
            league.merge(left.db, league.export(right, key))
    win(left, 2, a)
    assert league.apply(payload(a), left)['party'][0]['elite_four_wins'] == 3
    left.prune_events(1)
    assert league.apply(payload(a), left)['party'][0]['elite_four_wins'] == 3
    left.close()
    right.close()


def test_historical_replay_is_idempotent_and_rejects_wrong_location(tmp_path):
    store = Store(tmp_path)
    with store.lock, store.db:
        assert not league.record(store.db, snap(map=1, party=(mon(),)), 'Champion!', 1)
        assert league.record(store.db, snap(map=118, party=(mon(),)), 'Champion! League victory #7', 2)
    win(store, 7, mon())
    assert league.apply(payload(mon()), store)['party'][0]['elite_four_wins'] == 1
    store.close()


def test_bad_transfer_record_rejected():
    with pytest.raises(ValueError):
        league.validate({'key': 'wrong', 'counts': {}, 'ambiguous': False}, 'expected')
    with pytest.raises(ValueError):
        league.validate({'key': 'expected', 'counts': {'a' * 32: -1}, 'ambiguous': False}, 'expected')


def test_failed_event_transaction_does_not_credit_a_victory(tmp_path):
    import sqlite3
    store = Store(tmp_path)
    store.db.set_authorizer(lambda action, table, *_: sqlite3.SQLITE_DENY
                            if action == sqlite3.SQLITE_UPDATE and table == 'events' else sqlite3.SQLITE_OK)
    with pytest.raises(sqlite3.DatabaseError):
        win(store, 1, mon())
    assert league.apply(payload(mon()), store)['party'][0]['elite_four_wins'] == 0
    store.db.set_authorizer(None)
    win(store, 1, mon())
    assert league.apply(payload(mon()), store)['party'][0]['elite_four_wins'] == 1
    store.close()


def test_committed_trade_recovery_imports_counts_once(tmp_path):
    from test_managed_participant import committed
    from pokesim.runtime.participant import _promote
    store = Store(tmp_path)
    key = identity(payload(mon())['party'][0])
    record = committed(store)
    record['incoming_league_record'] = {'key': key, 'counts': {'a' * 32: 12}, 'ambiguous': False}
    _promote(store, record)
    _promote(store, record)
    assert league.apply(payload(mon()), store)['party'][0]['elite_four_wins'] == 12
    store.close()
