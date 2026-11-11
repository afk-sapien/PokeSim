"""Championship claims survive rewinds, full storage, and repeated delivery."""
import json
import sqlite3
import time
import pytest

from pokesim import rewards
from pokesim.events import RunMemory, diff
from pokesim.state import claims
from pokesim.store import Store
from pokesim.trade import event, pair, service
from pokesim.strategy_data import SPECIES, MOVES
from test_events import snap
from test_strategy import flags


def test_gifts_are_off_for_headless_runs_and_on_for_a_new_managed_adventure(tmp_path):
    """config names both gift switches, so a headless run is off on purpose, and a managed worker
    installs the adventure's own choice, which the create route turns on."""
    import inspect
    from pokesim import config
    from pokesim.app import manager
    from pokesim.runtime.settings import SimulationSettings
    assert hasattr(config, 'LEAGUE_REWARDS') and hasattr(config, 'MEW_EVENT')
    defaults = {field.name: field.default for field in SimulationSettings.__dataclass_fields__.values()}
    assert defaults['league_rewards'] is False and defaults['mew_event'] is False
    source = inspect.getsource(manager)
    assert "'league_rewards': data.get('league_rewards', True)" in source
    assert "'mew_event': data.get('mew_event', True)" in source


@pytest.mark.parametrize('owned,events,groups', [
    ({1}, (), set()),
    ({133}, (), {'eevee'}),
    ({135}, (), {'eevee'}),
    ({139}, (), {'fossils'}),
    ({142}, (), {'fossils'}),
    ({106}, (), set()),
    (set(), ('EVENT_BEAT_KARATE_MASTER',), {'dojo'}),
    (set(), ('EVENT_GOT_HITMONCHAN',), {'dojo'}),
    ({122}, (), {'mr_mime'}),
    ({124}, (), {'jynx'}),
])
def test_pool_requires_each_adventures_own_progress(owned, events, groups):
    snapshot = snap(owned=frozenset(owned), event_flags=flags(*events))
    assert rewards.progress_unlocks(snapshot) == groups
    value = {'unlocks': sorted(groups)}
    expected = set(rewards.BASE_POOL)
    assert set(rewards.eligible_pool(value)) == expected


def test_unlocks_survive_restore_without_awarding_old_victories(tmp_path):
    store = Store(tmp_path)
    try:
        rewards.initialize(store, 80)
        rewards.observe_progress(store, snap(owned=frozenset({133, 138, 122}),
                                             event_flags=flags('EVENT_GOT_HITMONLEE')))
        rewards.observe_progress(store, snap())
        rewards.initialize(store, 70)
        status = rewards.status(store)
        assert status['wins'] == 80
        assert status['earned'] == status['pending'] == 0
        assert set(status['unlocks']) == {'eevee', 'fossils', 'dojo', 'mr_mime'}
        rewards.earn(store, 81, enabled=False)
        assert rewards.status(store)['wins'] == 81
        assert rewards.status(store)['earned'] == 0
    finally:
        store.close()


def test_locked_species_never_appear_in_base_reward_draws():
    draws = {rewards.draw(f'base:{i}') for i in range(200)}
    assert draws == set(rewards.BASE_POOL)


def status(earned=0, delivered=0, declined=0, pending=0, wins=0):
    return {'earned': earned, 'delivered': delivered, 'declined': declined, 'pending': pending,
            'wins': wins, 'unlocks': []}


def test_enabling_after_past_victories_only_rewards_the_next_win(tmp_path):
    with_store = Store(tmp_path)
    try:
        rewards.initialize(with_store, 100)
        rewards.earn(with_store, 101, enabled=False)
        rewards.initialize(with_store, 101)
        assert rewards.status(with_store) == status(wins=101)
        rewards.earn(with_store, 102, enabled=True)
        assert rewards.status(with_store) == status(earned=1, pending=1, wins=102)
        rewards.earn(with_store, 102, enabled=True)
        rewards.earn(with_store, 99, enabled=True)
        assert rewards.status(with_store)['pending'] == 1
        assert rewards.championship_count(rewards.ledger(with_store.db)) == 102
    finally:
        with_store.close()


@pytest.mark.parametrize('old', [
    # Version 1 counted every victory as earned, so the ones past the delivered gifts are dropped.
    {'earned': 107, 'delivered': 5, 'seed': 'existing-seed', 'unlocks': ['eevee']},
    # Version 2 kept the victories apart and earned only the gifts it would give.
    {'version': 2, 'observed': 107, 'earned': 7, 'delivered': 5, 'skipped': 1, 'seed': 'existing-seed',
     'unlocks': ['eevee']},
])
def test_an_old_ledger_becomes_claims_rows_and_keeps_its_open_gifts(tmp_path, old):
    store = Store(tmp_path)
    try:
        with store.transaction() as db:
            rewards.save(db, old)
        rewards.initialize(store, 107)
        pending = old['earned'] - old['delivered'] if old.get('version') == 2 else 0
        assert rewards.status(store) == {**status(earned=5 + pending, delivered=5, pending=pending, wins=107),
                                         'unlocks': ['eevee']}
        assert rewards.ledger(store.db) == {'seed': 'existing-seed', 'observed': 107, 'unlocks': ['eevee'],
                                            'version': rewards.VERSION}
        rows = claims.rows(store.db, rewards.SOURCE)
        assert [row['key'] for row in rows] == [f'existing-seed:{n}' for n in range(1, 6 + pending)]
        # A moved delivery has no frame, so no reload reopens it.
        assert all(row['frame'] is None for row in rows)
        with store.transaction() as db:
            assert claims.reopen_after(db, 0) == []
        rewards.earn(store, 108, enabled=True)
        assert rewards.status(store)['pending'] == pending + 1
        assert claims.rows(store.db, rewards.SOURCE)[-1]['key'] == f'existing-seed:{6 + pending}'
        rewards.initialize(store, 108)
        assert rewards.status(store)['pending'] == pending + 1
    finally:
        store.close()


def test_the_schema_moves_an_old_ledger_once_when_the_database_opens(tmp_path):
    store = Store(tmp_path)
    store.close()
    with sqlite3.connect(tmp_path / 'pokesim.sqlite') as db:
        db.execute('DROP TABLE claims')
        db.execute('PRAGMA user_version = 1')
        db.execute('INSERT OR REPLACE INTO kv(k, v) VALUES (?, ?)',
                   (rewards.KEY, json.dumps({'earned': 3, 'delivered': 1, 'seed': 'old'})))
    store = Store(tmp_path)
    try:
        assert rewards.status(store) == status(earned=1, delivered=1, wins=3)
        assert rewards.ledger(store.db)['version'] == rewards.VERSION
    finally:
        store.close()


def test_disabled_victories_never_become_claims_after_reenabling(tmp_path):
    store = Store(tmp_path)
    try:
        rewards.initialize(store, 0)
        rewards.earn(store, 1, enabled=True)
        rewards.earn(store, 2, enabled=False)
        rewards.earn(store, 3, enabled=False)
        rewards.initialize(store, 3)
        rewards.earn(store, 4, enabled=True)
        assert rewards.status(store) == status(earned=2, pending=2, wins=4)
    finally:
        store.close()


def test_a_reload_reopens_only_the_gifts_delivered_after_its_save(tmp_path):
    store = Store(tmp_path)
    try:
        with store.transaction() as db:
            rewards.save(db, {'seed': 's', 'observed': 3, 'version': rewards.VERSION})
            rewards.open_claims(db, 's', 3, frame=10)
            rewards.settle(db, 's:1', claims.DELIVERED, frame=100, reward_id='first')
            rewards.settle(db, 's:2', claims.DELIVERED, frame=200, reward_id='second')
            rewards.settle(db, 's:3', claims.DECLINED, frame=300, reasons='Not worth a slot')
        # The gift's own result checkpoint never reopens its claim.
        assert rewards.rewound(store, {'play_clock': {'frames': 150}, 'reward_id': 'second'}) == []
        assert rewards.rewound(store, {}) == ()
        assert rewards.rewound(store, {'play_clock': {'frames': 150}}) == [('league', 's:2')]
        rows = {row['key']: row for row in claims.rows(store.db, rewards.SOURCE)}
        assert rows['s:2']['state'] == claims.OPEN and rows['s:2']['reward_id'] is None
        assert rows['s:1']['state'] == claims.DELIVERED
        # A declined gift stays declined, since the save before it would decline it again.
        assert rows['s:3']['state'] == claims.DECLINED
        # The reopened claim keeps its place, so it is the next gift drawn, with the same seed.
        assert rewards.next_claim(store.db) == (2, rewards.draw('s:2'), 's:2')
    finally:
        store.close()


def test_a_reopened_gift_the_pc_still_holds_settles_without_a_second_copy(tmp_path):
    from dataclasses import replace as changed
    store = Store(tmp_path)
    try:
        with store.transaction() as db:
            rewards.open_claims(db, 's', 1)
        seed = rewards.next_claim(store.db)[2]
        trainer, first, second = rewards._draw(seed, 1)
        dvs = (0, first >> 4, first & 15, second >> 4, second & 15)
        empty = snap()
        assert not rewards.held(empty, seed)
        holding = changed(empty, party=(changed(empty.party[0], trainer_id=trainer, dvs=dvs),))
        assert rewards.held(holding, seed)
        rewards.found_held(store, seed, 153)
        found = claims.get(store.db, rewards.SOURCE, seed)
        assert (found['state'], found['reasons'], found['species']) == (claims.DELIVERED, 'Already held', 153)
        assert rewards.next_claim(store.db) is None
        with pytest.raises(ValueError, match='claim changed'):
            rewards.found_held(store, seed, 153)
    finally:
        store.close()


def test_repeated_championships_count_beyond_cartridge_cap_and_restore_safely(tmp_path):
    store = Store(tmp_path)
    memory = RunMemory()
    outside = snap(map=120, hall_of_fame_count=255)
    hall = snap(map=118, hall_of_fame_count=255)
    checkpoint = memory.to_dict()
    for number in (1, 2):
        assert any(e.type == 'champion' for e in diff(outside, hall, memory))
        rewards.earn(store, memory.championships)
        assert memory.championships == number
        assert not any(e.type == 'champion' for e in diff(hall, hall, memory))
        assert diff(None, hall, memory) == []
    restored = RunMemory.from_dict(checkpoint)
    diff(outside, hall, restored)
    rewards.earn(store, restored.championships)
    assert rewards.status(store) == status(earned=2, pending=2, wins=2)
    assert RunMemory.from_dict(memory.to_dict()).championships == 2
    store.close()


def test_league_pool_has_only_three_starters_with_playable_level_five_data():
    assert {SPECIES[s]['dex'] for s in rewards.POOL} == {1, 4, 7}
    selected = set()
    for number in range(1, 301):
        seed = f'test adventure:{number}'
        species = rewards.draw(seed, 1, {'unlocks': list(rewards.UNLOCK_POOLS)})
        assert rewards.draw(seed) == species and rewards.ordinal(seed) == number
        selected.add(species)
        gift = event.gift_slot(seed, species)
        assert gift.species == species and gift.level == 5
        assert gift.struct[17:27] == bytes(10)
        assert gift.trainer == 'POKESIM'
        assert int.from_bytes(gift.struct[1:3], 'big') > 0
        for move, pp in zip(gift.struct[8:12], gift.struct[29:33]):
            assert pp == (MOVES[move]['pp'] if move else 0)
        expected_xp = {'MEDIUM_SLOW': 135, 'MEDIUM_FAST': 125, 'SLOW': 156, 'FAST': 100}
        assert int.from_bytes(gift.struct[14:17], 'big') == expected_xp[SPECIES[species]['growth']]
    assert selected == set(rewards.POOL)


def test_reward_journal_consumes_one_claim_once_and_preserves_next_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(pair, 'PAIR_ROOT', tmp_path / 'pair')
    for name in ('red', 'blue'):
        store = Store(pair.PAIR_ROOT / name)
        rewards.earn(store, 2)
        store.close()
    for ordinal in (1, 2):
        transaction = str(ordinal)
        service.write(tmp_path / f'transactions/{transaction}/result.json', {
            'states': {'red': 'red.state', 'blue': 'blue.state'}, 'kind': 'league_reward',
            'gifts': [{'instance': 'red', 'name': 'Eevee', 'ordinal': ordinal}],
        })
        event.journal(tmp_path, transaction)
        event.journal(tmp_path, transaction)
        store = Store(pair.PAIR_ROOT / 'red')
        assert rewards.status(store)['delivered'] == ordinal
        from pokesim.catches import status as catches
        assert catches(store)['counts'] == {'133': ordinal}
        assert len(store.events()) == ordinal
        store.close()
    store = Store(pair.PAIR_ROOT / 'blue')
    assert rewards.status(store)['pending'] == 2
    store.close()


def test_full_boxes_preserve_pending_reward_without_booting(tmp_path, monkeypatch):
    monkeypatch.setattr(pair, 'PAIR_ROOT', tmp_path / 'pair')
    for name in ('red', 'blue'):
        store = Store(pair.PAIR_ROOT / name)
        rewards.earn(store, 1)
        state = store.states / 'auto-v1-1.state'
        state.write_bytes(b'checkpoint')
        state.with_suffix('.json').write_text('{}')
        store.close()
    monkeypatch.setattr(pair.CheckpointStore, 'latest_state', lambda self: self.states / 'auto-v1-1.state')
    monkeypatch.setattr(pair, 'inspect', lambda *args: (snap(box_counts=(20,) * 12), {}, {}))
    event.stage(tmp_path, '1', league_rewards=True)
    assert json.loads((tmp_path / 'transactions/1/result.json').read_text())['status'] == 'no_opportunity'
    for name in ('red', 'blue'):
        store = Store(pair.PAIR_ROOT / name)
        assert rewards.status(store)['pending'] == 1
        store.close()


def test_rewards_bypass_trade_cooldown_and_do_not_need_board(tmp_path, monkeypatch):
    service.write(tmp_path / 'policy.json', {'enabled': True, 'league_rewards': True,
                  'peers': {'red': {}, 'blue': {}}})
    service.write(tmp_path / 'public/status.json', {'last_trade': time.time(), 'history': [], 'completed': 0})
    c = service.Coordinator(tmp_path)
    state = {'health': {'ok': True}, 'game': {'party': [{}], 'storage': {'box_counts': [0] * 12}},
             'league_rewards': {'pending': 1}}
    monkeypatch.setattr(service, 'request', lambda *args: state)
    monkeypatch.setattr(c, 'control', lambda *args: {'phase': 'prepared'})
    kinds = []
    def stage(action, transaction):
        kinds.append(json.loads(c.active_path.read_text())['kind'])
        service.write(tmp_path / f'transactions/{transaction}/result.json', {'status': 'no_opportunity'})
    monkeypatch.setattr(c, 'worker', stage)
    c.cycle()
    assert kinds == ['league_reward']


def test_later_eevees_can_fill_remaining_evolutions_and_rematches_stay_available(monkeypatch):
    import random
    from unittest.mock import Mock
    from pokesim.policies.collection import Collection
    from pokesim.policies.progression import Goal
    from test_collection import state, sid
    from test_strategy import mon
    collection = Collection()
    collection.completed_champion = True
    collection.elapsed = 2000
    collection.eevee_choice = 134
    monkeypatch.setattr(collection, 'sources', lambda: {})
    candidates = []
    def select(options, projects):
        candidates.extend(projects.values())
        return next(project for project in projects.values() if project["method"] == "rematch")
    monkeypatch.setattr(collection.director, 'select', select)
    nav = Mock()
    nav.distance_lookup.return_value = lambda targets: 1
    nav.visits = []
    s = state(party=(mon(species=sid(133)),), owned=frozenset({133, 134}), money=90000)
    collection.choose(s, nav, random.Random(1), Goal('champion', 'Continue', 'Collect'))
    assert {SPECIES[p['species']]['dex'] for p in candidates if p['method'] == 'evolve'} == {135, 136}
    assert any(p['method'] == 'rematch' for p in candidates)


def test_mew_is_never_in_any_repeatable_reward_pool():
    from itertools import combinations
    from pokesim.trade.event import MEW
    groups = tuple(rewards.UNLOCK_POOLS)
    for size in range(len(groups) + 1):
        for unlocked in combinations(groups, size):
            value = {'unlocks': unlocked}
            assert MEW not in rewards.eligible_pool(value)
            for ordinal in range(1, 101):
                assert rewards.draw(f'mew-exclusion:{ordinal}', 1, value) != MEW


def test_existing_mew_closes_event_claim_even_after_restore(tmp_path):
    from pokesim.runtime.reward_delivery import select_reward
    from pokesim.trade.event import EVENT_KEY, MEW
    store = Store(tmp_path)
    rewards.observe_progress(store, snap(owned=frozenset({151})))
    assert store.get(EVENT_KEY)
    store.close()
    store = Store(tmp_path)
    restored = snap(hall_of_fame_count=1, owned=frozenset({1}))
    rewards.observe_progress(store, restored)
    assert select_reward(restored, None, 0, store.get(EVENT_KEY), mew_event=True) is None
    with store.transaction() as db:
        rewards.open_claims(db, 'old-save', 2)
    selected = select_reward(restored, rewards.next_claim(store.db), 2, store.get(EVENT_KEY), mew_event=True)
    assert selected[0] == 'league_reward' and selected[2] != MEW
    store.close()


def test_existing_mew_event_receipt_is_preserved(tmp_path):
    from pokesim.trade.event import EVENT_KEY
    store = Store(tmp_path)
    store.set(EVENT_KEY, 'original-transaction')
    rewards.observe_progress(store, snap(owned=frozenset({151})))
    assert store.get(EVENT_KEY) == 'original-transaction'
    store.close()


def test_league_gifts_use_random_cartridge_safe_names_without_changing_stats():
    from pokesim.policies.naming import POKEMON_NAMES
    names = set()
    for species in rewards.POOL:
        for number in range(20):
            seed = f'reward-name:{species}:{number}'
            original = event.gift_slot(seed, species)
            named = event.gift_slot(seed, species, random_name=True)
            assert named.nick in POKEMON_NAMES
            assert named.nick != original.nick
            assert 1 <= len(named.nick) <= 10
            assert len(named.nickname) == 11
            assert named.struct == original.struct
            assert named.ot_name == original.ot_name
            assert named == event.gift_slot(seed, species, random_name=True)
            names.add(named.nick)
    assert len(names) > 20
