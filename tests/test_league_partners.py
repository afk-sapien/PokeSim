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


def test_names_distinguish_same_family_and_dvs(tmp_path):
    store = Store(tmp_path)
    a = mon()
    win(store, 1, a, replace(a, nick='OTHER'))
    assert league.apply(payload(a), store)['party'][0]['elite_four_wins'] == 1
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


def test_the_second_league_battler_does_not_depend_on_party_order():
    # Muk and Charizard were both level 54. Moving Lapras to the lead changed which of them counted as
    # the strongest, so the partner to train changed too, and Lapras and Muk traded the lead forever.
    from itertools import permutations
    from pokesim.policies.progression import league_partner
    from test_events import snap
    from test_strategy import mon
    muk = mon(species=136, level=54, max_hp=190, attack=120)
    charizard = mon(species=180, level=54, max_hp=175, attack=110)
    lapras = mon(species=19, level=30, max_hp=127, attack=60)
    for party in permutations((muk, charizard, lapras, mon(level=47))):
        assert party[league_partner(snap(party=party))] is lapras
    # An identical twin already in the lead stays the one to train.
    twins = (lapras, charizard, mon(species=19, level=30, max_hp=127, attack=60))
    assert league_partner(snap(party=twins)) == 0
    assert league_partner(snap(party=(charizard, mon(level=20)))) is None


def test_different_families_with_identical_dvs_keep_separate_wins(tmp_path):
    store = Store(tmp_path)
    a = mon()
    b = replace(a, species=59, nick='DIGGY')
    boxed = StoredMon(1, 0, b.species, b.level, b.nick, (), 0, b.dvs, (0,) * 5, b.trainer_id)
    snapshot = snap(map=118, party=(a,), stored_details=(boxed,),
                    stored_pokemon=((1, b.species, b.level, b.nick),))
    store.add_event(Event('champion', 'Champion! League victory #1'), snapshot, None, None)
    assert [p['elite_four_wins'] for p in league.apply(payload(a, b), store)['party']] == [1, 0]
    win(store, 2, b)
    assert [p['elite_four_wins'] for p in league.apply(payload(a, b), store)['party']] == [1, 1]
    store.close()


def test_same_family_distinct_names_keep_individual_counts(tmp_path):
    store = Store(tmp_path)
    a, b = mon(), replace(mon(), nick='OTHER')
    win(store, 1, a, b)
    win(store, 2, a)
    assert [p['elite_four_wins'] for p in league.apply(payload(a, b), store)['party']] == [2, 1]
    store.close()


def test_exact_twins_do_not_gain_guessed_counts_when_one_leaves(tmp_path):
    store = Store(tmp_path)
    win(store, 1, mon(), mon())
    assert league.apply(payload(mon()), store)['party'][0]['elite_four_wins'] is None
    store.close()


def test_default_name_evolution_preserves_identity(tmp_path):
    store = Store(tmp_path)
    win(store, 1, replace(mon(), nick='PIKACHU'))
    evolved = replace(mon(), species=85, nick='RAICHU')
    assert league.apply(payload(evolved), store)['party'][0]['elite_four_wins'] == 1
    store.close()


def test_trade_record_is_bound_to_evolution_family_and_nickname(tmp_path):
    from dataclasses import asdict
    store = Store(tmp_path)
    a = mon()
    win(store, 1, a)
    key = identity(asdict(a))
    incoming = league.export(store, key, asdict(a))
    assert league.validate(incoming, key, asdict(replace(a, species=85))) == incoming
    for other in (replace(a, species=59), replace(a, nick='OTHER')):
        with pytest.raises(ValueError):
            league.validate(incoming, key, asdict(other))
    store.close()


def test_recovery_replaces_false_legacy_ambiguity_and_is_restart_safe(tmp_path, monkeypatch):
    from pokesim import league_history
    import json
    store = Store(tmp_path)
    a, b = mon(), replace(mon(), species=59, nick='DIGGY')
    old_key = identity(payload(a)['party'][0])
    legacy = {'origin': 'a' * 32, 'victories': ['league:1'],
              'partners': {old_key: {'counts': {}, 'ambiguous': True}}}
    store.set(league.LEGACY_KEY, legacy)
    with store.db:
        store.db.execute("INSERT INTO events(id,ts,type,title,state) VALUES (1,0,'champion',?,?)",
                         ('Champion! League victory #1', 'event-1.state'))
    (store.states / 'event-1.state').write_bytes(b'evidence')
    class Replay:
        memory = {}
        stops = []
        def __init__(self, *args, **kwargs):
            assert kwargs['ram_file'].getvalue() == bytes(32768)
        def load_state(self, stream):
            assert stream.read() == b'evidence'
        def stop(self, *, save):
            self.stops.append(save)
    monkeypatch.setattr(league_history, 'read_snapshot', lambda *_: snap(map=118, party=(a, b)))
    league_history.recover(store, 'private.gb', factory=Replay)
    before = league.read(store.db)
    league_history.recover(store, 'private.gb', factory=lambda *_: pytest.fail('Already recovered'))
    assert league.read(store.db) == before
    assert Replay.stops == [False]
    assert json.loads(store.db.execute('SELECT v FROM kv WHERE k=?', (league.LEGACY_KEY,)).fetchone()[0]) == legacy
    assert [p['elite_four_wins'] for p in league.apply(payload(a, b), store)['party']] == [1, 1]
    assert not any(p['elite_four_wins_incomplete'] for p in league.apply(payload(a, b), store)['party'])
    store.close()


def test_missing_recovery_evidence_preserves_unambiguous_verified_count(tmp_path):
    from pokesim.league_history import recover
    store = Store(tmp_path)
    a = mon()
    old_key = identity(payload(a)['party'][0])
    store.set(league.LEGACY_KEY, {'origin': 'a' * 32, 'victories': ['league:1'],
                                'partners': {old_key: {'counts': {'a' * 32: 12}, 'ambiguous': False}}})
    recover(store, 'unused.gb')
    result = league.apply(payload(a), store)['party'][0]
    assert result['elite_four_wins'] == 12
    assert not result['elite_four_wins_incomplete']
    store.close()


def test_named_journal_evidence_recovers_unique_partners_without_guessing_duplicates():
    from pokesim.league_history import recover_named
    from dataclasses import asdict
    value = {'origin': 'a' * 32, 'victories': [], 'partners': {}}
    a, b = mon(), replace(mon(), species=59, nick='DIGGY')
    league.resolve(value, [asdict(a), asdict(b)])
    row = {'id': 1, 'title': 'Champion! League victory #1', 'body': 'Party: SPARK L50, DIGGY L30.'}
    assert recover_named(value, row)
    assert recover_named(value, row)
    assert [entry['counts']['a' * 32] for entry in value['partners'].values()] == [1, 1]
    league.resolve(value, [asdict(replace(a, species=1))], allow_rename=False)
    row.update(id=2, title='Champion! League victory #2')
    assert not recover_named(value, row)
    assert sum(entry['counts'].get('a' * 32, 0) for entry in value['partners'].values()) == 3


def test_legacy_replay_does_not_announce_a_second_total_victory(tmp_path):
    store = Store(tmp_path)
    store.set(league.LEGACY_KEY, {'origin': 'a' * 32, 'victories': ['league:1'], 'partners': {}})
    with store.db:
        assert not league.record(store.db, snap(map=118, party=(mon(),)), 'Champion! League victory #1', 1)
    assert league.apply(payload(mon()), store)['party'][0]['elite_four_wins'] == 1
    store.close()


def test_journal_recovery_does_not_assign_a_reused_name_or_exceed_legacy_total():
    from pokesim.league_history import recover_named
    from dataclasses import asdict
    value = {'origin': 'a' * 32, 'victories': [], 'partners': {}}
    a = mon()
    league.resolve(value, [asdict(a)])
    legacy = {'partners': {identity(asdict(a)): {'counts': {'a' * 32: 1}, 'ambiguous': False}}}
    for i in range(1, 4):
        recover_named(value, {'id': i, 'title': f'Champion! League victory #{i}',
                              'body': 'Party: SPARK L50.'}, legacy)
    assert sum(e['counts'].get('a' * 32, 0) for e in value['partners'].values()) == 1
    other = {'origin': 'a' * 32, 'victories': [], 'partners': {}}
    league.resolve(other, [asdict(a)])
    assert not recover_named(other, {'id': 1, 'title': 'Champion! League victory #1',
                                     'body': 'Party: SPARK L50.'}, {'partners': {}})
    assert not next(iter(other['partners'].values()))['counts']


def test_new_wins_add_to_preserved_legacy_baseline(tmp_path):
    store = Store(tmp_path)
    key = identity(payload(mon())['party'][0])
    store.set(league.LEGACY_KEY, {'origin': 'a' * 32, 'victories': ['league:1'],
                                'partners': {key: {'counts': {'a' * 32: 12}, 'ambiguous': False}}})
    win(store, 2, mon())
    assert league.apply(payload(mon()), store)['party'][0]['elite_four_wins'] == 13
    store.close()
