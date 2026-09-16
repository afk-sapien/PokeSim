"""Championship claims survive rewinds, full storage, and repeated delivery."""
import json
import random
import sqlite3
import time

from pokesim import rewards
from pokesim.events import RunMemory, diff
from pokesim.store import Store
from pokesim.trade import event, pair, service
from pokesim.strategy_data import SPECIES, MOVES
from test_events import snap


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
    assert rewards.status(store) == {'earned': 2, 'delivered': 0, 'pending': 2}
    assert RunMemory.from_dict(memory.to_dict()).championships == 2
    store.close()


def test_pool_has_seven_species_with_playable_level_five_data_and_no_mew():
    assert {SPECIES[s]['dex'] for s in rewards.POOL} == {1, 4, 7, 133, 138, 140, 142}
    selected = set()
    for number in range(300):
        value = {'seed': 'test adventure', 'delivered': number}
        ordinal, species, seed = rewards.selection(value)
        assert rewards.selection(value) == (ordinal, species, seed)
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


def test_pending_rewards_preserve_other_species_and_replace_legacy_mew():
    replaced = 0
    for number in range(300):
        value = {'seed': 'existing adventure', 'delivered': number}
        ordinal, species, seed = rewards.selection(value)
        previous = random.Random(seed).choice((153, 176, 177, 102, 98, 90, 171, 21))
        if previous == event.MEW:
            replaced += 1
            assert species in rewards.POOL
        else:
            assert species == previous
        assert species != event.MEW
        assert ordinal == number + 1
    assert replaced > 0


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
    def select(options, rng, urgent):
        candidates.extend(project for weight, project in options)
        return next(project for weight, project in options if project["method"] == "rematch")
    monkeypatch.setattr(collection.director, 'select', select)
    nav = Mock()
    nav.distance_lookup.return_value = lambda targets: 1
    nav.visits = []
    s = state(party=(mon(species=sid(133)),), owned=frozenset({133, 134}), money=90000)
    collection.choose(s, nav, random.Random(1), Goal('champion', 'Continue', 'Collect'))
    assert {SPECIES[p['species']]['dex'] for p in candidates if p['method'] == 'evolve'} == {135, 136}
    assert any(p['method'] == 'rematch' for p in candidates)
