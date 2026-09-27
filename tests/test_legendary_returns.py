from dataclasses import replace
from types import SimpleNamespace
import random
from unittest.mock import Mock

import pytest

from pokesim import config
from pokesim.catches import CatchTracker, SUPPORTED, status as catch_status
from pokesim.legendary import LegendaryRecovery
from pokesim.legendary_returns import (
    KEY, STEPS, STEP_ADDRESS, STEP_SIGNATURE, StepTracker, claims, observe, status,
)
from pokesim.policies.battle import choose_battle
from pokesim.policies.collection import Collection
from pokesim.policies.progression import Goal
from pokesim.store import Store
from pokesim.strategy_data import ITEMS, MAPS
from test_collection import sid, state
from test_legendary_recovery import failed
from test_strategy import mon


@pytest.fixture
def tracking(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'LEGENDARY_RETURN_STEPS', 100)
    store = Store(tmp_path)
    CatchTracker(store, sorted(SUPPORTED)[0])
    steps = StepTracker(store, sorted(SUPPORTED)[0])
    try:
        yield store, steps
    finally:
        store.close()


def walk(steps, total):
    for _ in range(total):
        steps.completed(None)
    steps.flush(force=True)


def test_hook_checks_known_rom_signature_and_counts_each_completed_step(tracking):
    store, steps = tracking
    class Memory:
        def __getitem__(self, key):
            assert key == (0, slice(STEP_ADDRESS, STEP_ADDRESS + len(STEP_SIGNATURE)))
            return STEP_SIGNATURE
    registered = []
    pb = SimpleNamespace(memory=Memory(), hook_register=lambda *args: registered.append(args))
    steps.attach(pb)
    bank, address, callback, context = registered[0]
    assert (bank, address) == (0, STEP_ADDRESS)
    for _ in range(255):
        callback(context)
    steps.flush(force=True)
    assert status(store)['steps'] == 255
    restarted = StepTracker(store, sorted(SUPPORTED)[0])
    restarted.completed(None)
    restarted.flush(force=True)
    assert status(store)['steps'] == 256
    pb.memory = SimpleNamespace()
    StepTracker(store, 'unverified').attach(pb)
    assert len(registered) == 1


def test_wrong_instruction_is_rejected(tracking):
    _, steps = tracking
    class Memory:
        def __getitem__(self, key):
            return bytes(len(STEP_SIGNATURE))
    with pytest.raises(ValueError, match='signature'):
        steps.attach(SimpleNamespace(memory=Memory()))


@pytest.mark.parametrize('dex', [144, 145, 146, 150])
def test_milestone_reopens_only_encounter_bits_and_catch_consumes_once(tracking, dex):
    store, steps = tracking
    s, memory = failed(dex, owned=frozenset({dex}), map=MAPS['PALLET_TOWN'])
    original = bytes(memory)
    walk(steps, 99)
    assert observe(store, s, memory) == ([], False)
    assert bytes(memory) == original
    walk(steps, 1)
    events, changed = observe(store, s, memory)
    assert changed and len(events) == 1
    assert sum(a != b for a, b in zip(original, memory)) == 2
    assert claims(store) == ({dex}, set())
    tracker = CatchTracker(store, sorted(SUPPORTED)[0])
    tracker.record('capture', dex)
    tracker.record('capture', dex)
    assert catch_status(store)['total'] == 1
    assert claims(store) == (set(), {dex})
    # Restoring encounter flags from before the catch does not earn another claim.
    memory[:] = bytes(len(memory))
    events, changed = observe(store, s, memory)
    assert changed and not events
    assert bytes(memory) == original
    assert LegendaryRecovery().observe(s, memory, blocked=claims(store)[1]) == ([], False)
    assert StepTracker(store, sorted(SUPPORTED)[0]).value['total'] == 100
    walk(steps, 100)
    assert len(observe(store, s, memory)[0]) == 1
    assert claims(store) == ({dex}, set())


@pytest.mark.parametrize('change', [{'in_battle': 1}, {'textbox': True}, {'start_menu': True},
                                    {'map': MAPS['CERULEAN_CAVE_B1F']}])
def test_reset_waits_for_safe_unloaded_room(tracking, change):
    store, steps = tracking
    walk(steps, 100)
    s, memory = failed(owned=frozenset({150}), map=MAPS['PALLET_TOWN'], **{
        key: value for key, value in change.items() if key != 'map'})
    s = replace(s, **change)
    original = bytes(memory)
    assert not observe(store, s, memory)[1]
    assert bytes(memory) == original
    safe = replace(s, in_battle=0, textbox=False, start_menu=False, map=MAPS['PALLET_TOWN'])
    assert observe(store, safe, memory)[1]


def test_unclaimed_return_does_not_accumulate_and_failed_catch_can_retry(tracking):
    store, steps = tracking
    s, memory = failed(owned=frozenset({150}), map=MAPS['PALLET_TOWN'])
    walk(steps, 100)
    observe(store, s, memory)
    walk(steps, 400)
    assert observe(store, s, memory)[0] == []
    ready, _ = claims(store)
    recovery = LegendaryRecovery({'pending': {'150': 0}, 'attempts': {'150': 1}})
    assert recovery.observe(s, memory, repeat=ready)[1]
    CatchTracker(store, sorted(SUPPORTED)[0]).record('success', 150)
    assert claims(store) == (set(), {150})
    assert observe(store, s, memory)[0] == []


def test_no_unencountered_legendary_or_disabled_reset(tracking, monkeypatch):
    store, steps = tracking
    walk(steps, 100)
    s, memory = failed(owned=frozenset())
    assert observe(store, s, memory) == ([], False)
    assert not claims(store)[0]
    monkeypatch.setattr(config, 'LEGENDARY_RETURN_STEPS', 0)
    walk(steps, 100)
    assert observe(store, replace(s, owned=frozenset({150})), memory) == ([], False)
    assert not status(store)['enabled']


def test_owned_legendary_return_is_planned_and_finished_by_receipt(monkeypatch):
    c = Collection()
    c.completed_champion = True
    c.returned_legendaries = {150}
    c.elapsed = 2000
    monkeypatch.setattr(c, 'sources', lambda: {sid(150): [{'map': MAPS['CERULEAN_CAVE_B1F'],
                    'method': 'static', 'fragment': 'MEWTWO', 'flag': 'EVENT_BEAT_MEWTWO'}]})
    monkeypatch.setattr(c.director, 'select', lambda rows, *args, **kw: next(p for _, p in rows if p.get('legendary_return')))
    nav = Mock()
    nav.distance_lookup.return_value = lambda _: 20
    nav.visits = []
    s = state(owned=frozenset({150}))
    c.choose(s, nav, random.Random(1), Goal('collect_plan', 'Plan', 'Plan'))
    assert c.project['legendary_return'] and c.project['repeat']
    assert c.repeat_target(sid(150)) == sid(150)
    c.observe(s)
    assert c.project is not None
    c.returned_legendaries = set()
    c.closed_legendaries = {150}
    c.observe(replace(s, frame=120))
    assert c.project is None


@pytest.mark.parametrize('dex', [144, 145, 146, 150])
def test_returned_owned_legendary_uses_protected_capture_routine(dex):
    me = mon(level=100, hp=300, max_hp=300, moves=(33,), pp=(35,))
    enemy = mon(species=sid(dex), level=70, hp=200, max_hp=200)
    s = state(owned=frozenset({dex}), party=(me,), in_battle=1,
              items=((ITEMS['ULTRA_BALL'], 20),))
    assert choose_battle(s, me, enemy, 0, repeat_species=sid(dex)).kind == 'item'
    assert choose_battle(replace(s, items=()), me, enemy, 0, repeat_species=sid(dex)).kind == 'run'
    assert choose_battle(s, me, enemy, 0, repeat_species=sid(dex), catch_attempts=50).kind == 'run'


def test_interval_change_starts_a_new_milestone_without_revoking_ready_claims(tracking, monkeypatch):
    store, steps = tracking
    s, memory = failed(owned=frozenset({150}), map=MAPS['PALLET_TOWN'])
    walk(steps, 100)
    observe(store, s, memory)
    monkeypatch.setattr(config, 'LEGENDARY_RETURN_STEPS', 500)
    assert observe(store, s, memory)[0] == []
    assert status(store)['remaining'] == 500
    assert claims(store)[0] == {150}
    CatchTracker(store, sorted(SUPPORTED)[0]).record('caught', 150)
    walk(steps, 499)
    observe(store, s, memory)
    assert status(store)['remaining'] == 1
    assert not claims(store)[0]
    walk(steps, 1)
    observe(store, s, memory)
    assert claims(store)[0] == {150}


def test_receipt_failure_does_not_consume_return(tracking):
    import sqlite3
    store, steps = tracking
    s, memory = failed(owned=frozenset({150}), map=MAPS['PALLET_TOWN'])
    walk(steps, 100)
    observe(store, s, memory)
    tracker = CatchTracker(store, sorted(SUPPORTED)[0])
    store.db.execute("CREATE TRIGGER reject_count BEFORE UPDATE ON kv WHEN NEW.k='capture-statistics-v1' "
                     "BEGIN SELECT RAISE(ABORT, 'failed')" + chr(59) + " END")
    with pytest.raises(sqlite3.IntegrityError, match='failed'):
        tracker.record('catch', 150)
    assert claims(store)[0] == {150}
    assert catch_status(store)['total'] == 0


def test_failed_return_expedition_leaves_room_for_retry():
    from test_strategy import flags
    c = Collection()
    c.returned_legendaries = {150}
    c.project = {'method': 'static', 'species': sid(150), 'legendary_return': True,
                 'repeat': True, 'initial_count': 0, 'flag': 'EVENT_BEAT_MEWTWO', 'key': 'return'}
    c.remaining = 180000
    c.observe(state(owned=frozenset({150}), event_flags=flags('EVENT_BEAT_MEWTWO')))
    assert c.project is None
    assert c.returned_legendaries == {150}


def test_disabled_walking_does_not_create_a_backlog_when_reenabled(tracking, monkeypatch):
    store, steps = tracking
    s, memory = failed(owned=frozenset({150}), map=MAPS['PALLET_TOWN'])
    monkeypatch.setattr(config, 'LEGENDARY_RETURN_STEPS', 0)
    observe(store, s, memory)
    walk(steps, 1000)
    monkeypatch.setattr(config, 'LEGENDARY_RETURN_STEPS', 100)
    assert observe(store, s, memory)[0] == []
    assert status(store)['remaining'] == 100
    walk(steps, 100)
    assert len(observe(store, s, memory)[0]) == 1
