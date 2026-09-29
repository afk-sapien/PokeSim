from dataclasses import replace

import pytest

from pokesim import config, mew_returns, rewards, step_events as events
from pokesim.legendary_returns import STEPS
from pokesim.store import Store
from pokesim.strategy_data import MAPS, ITEMS
from test_collection import state, sid
from test_strategy import mon


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'EVENT_RETURN_STEPS', 100)
    monkeypatch.setattr(config, 'MEW_RETURN_STEPS', 100)
    monkeypatch.setattr(config, 'MEW_EVENT', True, raising=False)
    monkeypatch.setattr(config, 'FOSSIL_PREFERENCE', 'helix')
    monkeypatch.setattr(config, 'DOJO_PREFERENCE', 'hitmonchan')
    store = Store(tmp_path)
    store.set(STEPS, {'total': 5000, 'available': True})
    snapshot = state(map=MAPS['PALLET_TOWN'], hall_of_fame_count=1,
                     owned=frozenset({1, 133, 138, 106, 151}))
    try:
        yield store, snapshot, bytearray(65536)
    finally:
        store.close()


def steps(store, total):
    store.set(STEPS, {'total': total, 'available': True})


@pytest.mark.parametrize('key', ['eevee', 'dojo', 'fossil', 'trade_1', 'trade_4', 'trade_5', 'trade_6'])
def test_native_opportunity_requires_new_steps_and_consumes_once(world, key):
    store, snapshot, memory = world
    spec = next(a for a in events.activities('helix', 107) if a.key == key)
    for bit in spec.bits:
        events.write(memory, bit, True)
    original = bytes(memory)
    assert events.observe(store, snapshot, memory) == ([], False)
    assert store.get(events.KEY)['tickets'][key]['next_at'] == 5100
    steps(store, 5099)
    assert events.observe(store, snapshot, memory) == ([], False)
    assert bytes(memory) == original
    steps(store, 5100)
    rows, changed = events.observe(store, snapshot, memory)
    assert changed and key in events.available(store)
    assert all(not events.read(memory, bit) for bit in spec.bits)
    # The reopened event remains available through later milestones.
    steps(store, 5500)
    assert not events.observe(store, snapshot, memory)[0]
    assert store.get(events.KEY)['tickets'][key]['cycle'] == 1
    # A real native acquisition changes inventory and the native completion bit.
    acquired = (replace(snapshot, items=(*snapshot.items, (ITEMS[spec.item], 1))) if spec.item
                else replace(snapshot, party=(*snapshot.party, mon(species=sid(spec.dex)))))
    events.write(memory, spec.done[0], True)
    rows, _ = events.observe(store, acquired, memory)
    assert key not in events.available(store)
    assert store.get(events.KEY)['tickets'][key]['next_at'] == 5600
    assert not events.observe(store, acquired, memory)[0]
    # Old checkpoint flags cannot reopen a spent opportunity.
    for bit in spec.bits:
        events.write(memory, bit, False)
    events.observe(store, snapshot, memory)
    assert events.read(memory, spec.done[0])


@pytest.mark.parametrize('change', [{'in_battle': 1}, {'textbox': True}, {'start_menu': True},
                                    {'map': MAPS['CELADON_MANSION_ROOF_HOUSE']}])
def test_return_waits_until_original_room_is_unloaded(world, change):
    store, snapshot, memory = world
    spec = events.activities()[0]
    events.write(memory, spec.done[0], True)
    events.observe(store, snapshot, memory)
    steps(store, 5100)
    before = bytes(memory)
    assert not events.observe(store, replace(snapshot, **change), memory)[1]
    assert bytes(memory) == before
    assert events.observe(store, snapshot, memory)[1]


def test_old_pre_reset_save_does_not_consume_available_opportunity(world):
    store, snapshot, memory = world
    spec = events.activities()[0]
    events.write(memory, spec.done[0], True)
    events.observe(store, snapshot, memory)
    steps(store, 5100)
    events.observe(store, snapshot, memory)
    events.write(memory, spec.done[0], True)
    events.observe(store, snapshot, memory)
    assert 'eevee' in events.available(store)
    assert not events.read(memory, spec.done[0])


def test_disabled_steps_do_not_build_a_backlog(world, monkeypatch):
    store, snapshot, memory = world
    events.write(memory, events.activities()[0].done[0], True)
    events.observe(store, snapshot, memory)
    monkeypatch.setattr(config, 'EVENT_RETURN_STEPS', 0)
    events.observe(store, snapshot, memory)
    steps(store, 20000)
    monkeypatch.setattr(config, 'EVENT_RETURN_STEPS', 100)
    assert not events.observe(store, snapshot, memory)[1]
    assert store.get(events.KEY)['tickets']['eevee']['next_at'] == 20100


def test_fossil_does_not_interrupt_pending_revival(world):
    store, snapshot, memory = world
    events.observe(store, snapshot, memory)
    steps(store, 5100)
    busy = replace(snapshot, items=((ITEMS['OLD_AMBER'], 1),))
    events.observe(store, busy, memory)
    assert 'fossil' not in events.available(store)


def test_auto_choices_prefer_missing_family(world, monkeypatch):
    _, snapshot, _ = world
    monkeypatch.setattr(config, 'FOSSIL_PREFERENCE', 'auto')
    monkeypatch.setattr(config, 'DOJO_PREFERENCE', 'auto')
    assert events.choices(snapshot) == ('dome', 107)


def test_mew_requires_steps_then_a_new_league_win_and_no_backlog(world):
    store, snapshot, _ = world
    rewards.initialize(store, 300)
    mew_returns.observe(store, snapshot)
    rewards.earn(store, 301)
    steps(store, 5099)
    mew_returns.observe(store, snapshot)
    assert not mew_returns.ready(store, 301)
    steps(store, 5100)
    mew_returns.observe(store, snapshot)
    assert not mew_returns.ready(store, 301)
    rewards.earn(store, 302)
    assert mew_returns.ready(store, 302)
    steps(store, 20000)
    mew_returns.observe(store, snapshot)
    with store.db:
        mew_returns.consume(store.db)
    assert not mew_returns.ready(store, 302)
    assert store.get(mew_returns.KEY)['next_at'] == 20100
    # Replaying an old Hall of Fame snapshot does not earn another gift.
    rewards.earn(store, 301)
    mew_returns.observe(store, snapshot)
    assert not mew_returns.ready(store, 302)


def test_mew_disable_and_reenable_starts_fresh_requirement(world, monkeypatch):
    store, snapshot, _ = world
    mew_returns.observe(store, snapshot)
    monkeypatch.setattr(config, 'MEW_EVENT', False)
    mew_returns.observe(store, snapshot)
    steps(store, 10000)
    monkeypatch.setattr(config, 'MEW_EVENT', True, raising=False)
    mew_returns.observe(store, snapshot)
    assert store.get(mew_returns.KEY)['next_at'] == 10100
    assert not mew_returns.ready(store, 1000)


def test_fossil_restore_protects_previous_amber_after_switching_to_helix(world, monkeypatch):
    store, snapshot, memory = world
    monkeypatch.setattr(config, 'FOSSIL_PREFERENCE', 'amber')
    events.observe(store, snapshot, memory)
    steps(store, 5100)
    events.observe(store, snapshot, memory)
    amber = next(a for a in events.activities('amber') if a.key == 'fossil')
    for bit in amber.bits:
        events.write(memory, bit, True)
    events.observe(store, replace(snapshot, items=((ITEMS['OLD_AMBER'], 1),)), memory)
    monkeypatch.setattr(config, 'FOSSIL_PREFERENCE', 'helix')
    steps(store, 5200)
    events.observe(store, snapshot, memory)
    assert events.available(store)['fossil']['item'] == 'HELIX_FOSSIL'
    for bit in amber.bits:
        events.write(memory, bit, False)
    events.observe(store, snapshot, memory)
    assert all(events.read(memory, bit) for bit in amber.bits)
    assert 'fossil' in events.available(store)


def test_trade_claim_survives_duplicate_cleanup_during_preparation(world):
    store, snapshot, memory = world
    spec = next(a for a in events.activities() if a.key == 'trade_6')
    twins = ((1, sid(124), 5, 'FIRST'), (1, sid(124), 5, 'SECOND'))
    snapshot = replace(snapshot, stored_pokemon=twins)
    events.write(memory, spec.done[0], True)
    events.observe(store, snapshot, memory)
    steps(store, 5100)
    events.observe(store, snapshot, memory)
    at_house = replace(snapshot, map=spec.room, stored_pokemon=twins[:1])
    events.observe(store, at_house, memory)
    assert store.get(events.KEY)['tickets']['trade_6']['baseline'] == 1
    # The cartridge sets the trade bit before playing the exchange animation.
    events.write(memory, spec.done[0], True)
    events.observe(store, at_house, memory)
    assert 'trade_6' in events.available(store)
    acquired = replace(at_house, party=(*at_house.party, mon(species=sid(124))))
    events.observe(store, acquired, memory)
    assert 'trade_6' not in events.available(store)
