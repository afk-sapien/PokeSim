"""Collection goals survive rewinds without inventing stars or rare individuals."""
from dataclasses import replace
import random
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from pokesim.catches import CatchTracker, SUPPORTED
from pokesim.milestones import KEY, MilestoneTracker, apply, is_perfect, level_credit, status
from pokesim.policies.director import AdventureDirector
from pokesim.store import Store
from pokesim.strategy_data import SPECIES
from pokesim.trade import preferences
from pokesim.web.app import create_app
from pokesim.web.pokedex import live_status
from test_events import snap
from test_duplicates import snapshot, stored
from test_strategy import mon


def species(dex):
    return next(sid for sid, row in SPECIES.items() if row['dex'] == dex)


def partner(dex=3, level=100, perfect=False, trainer=123):
    return mon(species=species(dex), level=level, trainer_id=trainer,
               dvs=(15,) * 5 if perfect else (8,) * 5)


@pytest.fixture
def tracking(tmp_path):
    store = Store(tmp_path)
    try:
        yield store, MilestoneTracker(store)
    finally:
        store.close()


def settle(tracker, snapshot):
    tracker.observe(snapshot)
    tracker.observe(replace(snapshot, frame=snapshot.frame + 30))


def test_terminal_evolution_stars_only_its_own_line():
    assert level_credit(species(3)) == {1, 2, 3}
    assert level_credit(species(2)) == {2}
    assert level_credit(species(134)) == {133, 134}
    assert level_credit(species(135)) == {133, 135}
    assert level_credit(species(136)) == {133, 136}
    assert level_credit(species(151)) == {151}


@pytest.mark.parametrize('dvs', [None, (), (15,) * 4, (15,) * 6, (14, 15, 15, 15, 15),
                               (True,) * 5, (15.0,) * 5, ('15',) * 5, (16,) * 5])
def test_incomplete_or_invalid_dvs_never_receive_perfect_credit(dvs):
    assert not is_perfect({'dvs': dvs})


def test_all_five_dvs_must_be_maximum():
    assert is_perfect({'dvs': [15] * 5})
    assert is_perfect({'dvs': (15,) * 5})


def test_settled_party_and_boxes_grant_stars_and_exact_perfect_species(tracking):
    store, tracker = tracking
    boxed = stored(0, species=species(134), level=100, dvs=(15,) * 5, trainer_id=123)
    s = snapshot([boxed], party=(partner(), partner(151, 99, True)))
    tracker.observe(s)
    assert status(store)['level_100'] == []
    settle(tracker, s)
    value = status(store)
    assert value['level_100'] == [1, 2, 3, 133, 134]
    assert value['perfect_species'] == [134, 151]
    assert value['perfect_found'] == 2
    payload = apply(live_status(s.to_dict()), store)
    assert payload['milestones']['perfect_held'] == 2
    assert 'perfect_groups' not in payload['milestones']
    assert [p['perfect_dvs'] for p in payload['party']] == [False, True]
    assert payload['storage']['pokemon'][0]['perfect_dvs']


def test_evolution_rename_and_box_moves_do_not_inflate_perfect_count(tracking):
    store, tracker = tracking
    settle(tracker, snap(party=(partner(1, 20, True),)))
    settle(tracker, snap(party=(replace(partner(2, 40, True), nick='NEW NAME'),)))
    boxed = stored(0, species=species(3), level=100, dvs=(15,) * 5, trainer_id=123)
    settle(tracker, snapshot([boxed], party=(partner(25, 50),)))
    assert status(store)['perfect_found'] == 1
    assert status(store)['perfect_species'] == [1, 2, 3]
    assert status(store)['level_100'] == [1, 2, 3]


def test_identical_perfect_individuals_are_counted_without_using_ambiguous_trade_keys(tracking):
    store, tracker = tracking
    settle(tracker, snap(party=(partner(3, 100, True), partner(3, 99, True), partner(25, 50, True))))
    assert status(store)['perfect_found'] == 3
    settle(tracker, snap(party=(partner(3, 99, True),)))
    assert status(store)['perfect_found'] == 3


def test_invalid_transient_and_trade_hold_snapshots_do_not_grant_credit(tracking):
    store, tracker = tracking
    bad = snap(party=(partner(3, 101, True),))
    settle(tracker, bad)
    settle(tracker, snap())
    tracker.observe(snap(party=(partner(),)))
    tracker.observe(snap())
    assert status(store)['level_100'] == []
    store.set('trade_hold', True)
    settle(tracker, snap(party=(partner(3, 100, True),)))
    assert status(store)['perfect_found'] == 0


def test_history_survives_reopen_checkpoint_rewind_and_event_pruning(tmp_path):
    store = Store(tmp_path)
    tracker = MilestoneTracker(store)
    settle(tracker, snap(party=(partner(3, 100, True),)))
    store.close()
    store = Store(tmp_path)
    try:
        tracker = MilestoneTracker(store)
        settle(tracker, snap(party=(partner(1, 5),)))
        store.prune_events(0)
        store.set('policy_state', {})
        assert status(store)['level_100'] == [1, 2, 3]
        assert status(store)['perfect_found'] == 1
        tracker.reset()
        assert status(store)['level_100'] == []
        assert status(store)['perfect_found'] == 0
    finally:
        store.close()


def test_perfect_capture_receipt_is_atomic_and_replay_safe(tracking):
    store, tracker = tracking
    settle(tracker, snap(party=(partner(25, 50, True),)))
    catches = CatchTracker(store, sorted(SUPPORTED)[0])
    memory = bytearray(65536)
    memory[0xd11c] = species(25)
    memory[0xd057] = 1
    memory[0xcff1:0xcff3] = bytes((255, 255))
    memory[0xd359:0xd35b] = (123).to_bytes(2, 'big')
    pb = SimpleNamespace(memory=memory)
    catches.completed(pb)
    catches.completed(pb)
    settle(tracker, snap(party=(partner(25, 50, True), partner(25, 20, True))))
    assert status(store)['perfect_found'] == 2
    assert status(store)['perfect_catches'] == 1
    memory[0xda44] = 1
    catches.completed(pb)
    assert status(store)['perfect_found'] == 3
    memory[0xcff1] = 254
    catches.completed(pb)
    assert status(store)['perfect_found'] == 3


def test_perfect_partner_cannot_be_manually_offered(tracking):
    store, _ = tracking
    payload = live_status(snap(party=(partner(25, 50, True),)).to_dict())
    key = preferences.identity(payload['party'][0])
    with pytest.raises(ValueError, match='Perfect DV'):
        preferences.update(store, payload, key, 'offered')


def test_training_prefers_an_unearned_star_over_high_level_completed_species():
    director = AdventureDirector()
    missing = {'method': 'train', 'key': 'new', 'mastery_needed': True, 'initial_level': 50}
    done = {'method': 'train', 'key': 'old', 'mastery_needed': False, 'initial_level': 99}
    for seed in range(20):
        assert director.select([(1, missing), (1000, done)], random.Random(seed)) == missing


def test_api_exposes_persistent_goals_even_without_running_game(tracking):
    store, tracker = tracking
    settle(tracker, snap(party=(partner(3, 100, True),)))
    emu = Mock()
    emu.status.return_value = {'game': None, 'strategy': {}}
    with TestClient(create_app(emu, store)) as client:
        data = client.get('/api/pokedex/status').json()
    assert data['milestones']['level_100'] == [1, 2, 3]
    assert data['milestones']['perfect_species'] == [3]
    assert data['milestones']['perfect_found'] == 1
    assert data['milestones']['perfect_held'] == 0


def test_perfect_receipt_and_goal_roll_back_together(tracking, monkeypatch):
    from pokesim.catches import status as catch_status
    store, _ = tracking
    catches = CatchTracker(store, sorted(SUPPORTED)[0])
    def fail(*args):
        raise RuntimeError('Interrupted before goal update')
    monkeypatch.setattr('pokesim.milestones.record_capture', fail)
    with pytest.raises(RuntimeError):
        catches.record('receipt', 25, perfect=True, species=species(25), trainer_id=123)
    assert catch_status(store)['total'] == 0
    assert status(store)['perfect_found'] == 0
    assert store.db.execute('SELECT COUNT(*) FROM capture_receipts').fetchone()[0] == 0


def test_perfect_duplicates_are_neither_released_nor_traded_even_when_offered():
    from pokesim.broker.inventory import normalise
    from pokesim.broker.routine import offers, listings
    from pokesim.policies.team import release_target
    perfect = stored(0, trainer_id=123, dvs=(15,) * 5)
    s = snapshot([perfect, replace(perfect, position=1)], party=(partner(1, 99),))
    assert release_target(s) is None
    payload = live_status(s.to_dict())
    for mon in payload['storage']['pokemon']:
        mon['trade_preference'] = 'offered'
    inv = normalise('red', '', payload)
    assert not offers(inv, allow_last_copies=True)
    assert all(not row['listed'] and 'Perfect DV' in row['reason'] for row in listings(inv) if row['box'])


def test_repeat_catches_need_another_partner_and_use_a_bounded_ball_budget():
    from pokesim.policies.collection import Collection
    from pokesim.policies.battle import choose_battle
    from pokesim.strategy_data import ITEMS, MAPS
    target = species(69)
    me = partner(3, 100)
    enemy = replace(partner(69, 5), hp=10, max_hp=10, moves=(), pp=())
    s = snap(party=(me,), owned=frozenset({3, 69}), in_battle=1,
             items=((ITEMS['POKE_BALL'], 10),))
    assert choose_battle(s, me, enemy, 0, repeat_species=target).kind == 'item'
    assert choose_battle(s, me, enemy, 0, repeat_species=target, catch_attempts=5).kind != 'item'
    assert choose_battle(replace(s, items=((ITEMS['MASTER_BALL'], 1),)), me, enemy, 0,
                         repeat_species=target).kind != 'item'
    c = Collection()
    c.project = {'species': target, 'method': 'grass', 'map': MAPS['ROUTE_1'],
                 'repeat': True, 'initial_count': 0, 'key': 'repeat'}
    c.remaining = 36000
    c.observe(replace(s, in_battle=0))
    assert c.project is not None
    c.observe(replace(s, frame=30, in_battle=0, party=(me, enemy)))
    assert c.project is None
