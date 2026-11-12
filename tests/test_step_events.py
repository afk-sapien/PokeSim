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


@pytest.mark.parametrize('key', ['eevee', 'dojo', 'snorlax', 'fossil', 'trade_1', 'trade_4', 'trade_5', 'trade_6'])
def test_native_opportunity_requires_new_steps_and_consumes_once(world, key):
    store, snapshot, memory = world
    spec = next(a for a in events.activities('helix', 107) if a.key == key)
    for bit in spec.bits:
        events.write(memory, bit, True)
    original = bytes(memory)
    assert events.observe(store, snapshot, memory) == ([], False)
    assert store.get(events.KEY)['clocks'][key]['next_at'] == 5100
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
    assert store.get(events.KEY)['clocks'][key]['cycle'] == 1
    # A real native acquisition changes inventory and the native completion bit.
    acquired = (replace(snapshot, items=(*snapshot.items, (ITEMS[spec.item], 1))) if spec.item
                else replace(snapshot, party=(*snapshot.party, mon(species=sid(spec.dex)))))
    events.write(memory, spec.done[0], True)
    rows, _ = events.observe(store, acquired, memory)
    assert key not in events.available(store)
    assert store.get(events.KEY)['clocks'][key]['next_at'] == 5600
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


def test_a_reload_from_before_a_return_opens_it_again_without_a_second_notice(world):
    store, snapshot, memory = world
    snapshot = replace(snapshot, owned=frozenset({133}))
    play = [500]
    store.clock = lambda: play[0]
    spec = events.activities()[0]
    events.write(memory, spec.done[0], True)
    events.observe(store, snapshot, memory)
    steps(store, 5100)
    original = bytes(memory)
    rows, changed = events.observe(store, snapshot, memory)
    assert changed and len(rows) == 1
    returned = bytes(memory)
    # A save from after the return already holds its cleared flags.
    assert rewards.rewound(store, {'play_clock': {'frames': 600}}) == []
    # A save from before it does not, so the claim opens and the flags are cleared again.
    memory[:] = original
    assert rewards.rewound(store, {'play_clock': {'frames': 400}}) == [('event', 'eevee')]
    assert events.available(store) == {}
    play[0] = 450
    assert events.observe(store, snapshot, memory) == ([], True)
    assert bytes(memory) == returned and 'eevee' in events.available(store)


def test_a_restart_lets_the_new_games_events_wait_for_their_story(world):
    store, snapshot, memory = world
    events.write(memory, events.activities()[0].done[0], True)
    events.observe(store, snapshot, memory)
    steps(store, 5100)
    events.observe(store, snapshot, memory)
    assert 'eevee' in events.available(store)
    store.restart(1, {})
    steps(store, 5200)
    # The last game's open Eevee visit does not send the new game to Celadon before its own story.
    assert events.available(store) == {}
    fresh = bytearray(len(memory))
    assert events.observe(store, replace(snapshot, owned=frozenset()), fresh) == ([], False)
    assert fresh == bytes(len(memory)) and events.available(store) == {}


def test_the_schema_moves_event_tickets_into_claims_rows_once(tmp_path):
    import json
    import sqlite3
    from pokesim import return_claims
    from pokesim.gen2.returns import EVENTS
    from pokesim.state import claims as ledger
    Store(tmp_path).close()
    clock = {'next_at': 300, 'interval': 100, 'choice': 'helix', 'dojo': 106}
    gen1 = {'eevee': {**clock, 'cycle': 2, 'state': 'available'},
            'dojo': {**clock, 'cycle': 1, 'state': 'walking'},
            'fossil': {**clock, 'cycle': 0, 'state': 'walking'}}
    gen2 = {'sudowoodo': {'next_at': 300, 'interval': 100, 'cycle': 1, 'state': 'caught'},
            'gift_eevee': {'next_at': 300, 'interval': 100, 'cycle': 1, 'state': 'walking', 'skipped': True,
                           'name': 'Eevee gift', 'dex': 133}}
    with sqlite3.connect(tmp_path / 'pokesim.sqlite') as db:
        db.execute('PRAGMA user_version = 3')
        for key, tickets in ((events.KEY, gen1), (EVENTS, gen2)):
            db.execute('INSERT OR REPLACE INTO kv(k, v) VALUES (?, ?)',
                       (key, json.dumps({'tickets': tickets, 'guards': {}})))
    store = Store(tmp_path)
    try:
        moved = {key: (row['state'], row['species'], row['frame'])
                 for key, row in return_claims.events(store.db).items()}
        assert moved == {'eevee': (ledger.DELIVERED, None, None), 'dojo': (ledger.CONSUMED, None, None),
                         'sudowoodo': (ledger.CONSUMED, None, None), 'gift_eevee': (ledger.DECLINED, 133, None)}
        assert store.get(events.KEY) == {'guards': {}, 'clocks': {
            'eevee': {**clock, 'cycle': 2}, 'dojo': {**clock, 'cycle': 1}, 'fossil': {**clock, 'cycle': 0}}}
        # Gen II reports the capture it had not journaled yet, and not the skip it already had.
        noted = {key: clock['noted'] for key, clock in store.get(EVENTS)['clocks'].items()}
        assert noted == {'sudowoodo': 0, 'gift_eevee': 1} and 'tickets' not in store.get(EVENTS)
        assert set(events.available(store)) == {'eevee'}
        # A moved row has no frame, so no reload reopens it.
        assert rewards.rewound(store, {'play_clock': {'frames': 0}}) == []
    finally:
        store.close()


def test_disabled_steps_do_not_build_a_backlog(world, monkeypatch):
    store, snapshot, memory = world
    events.write(memory, events.activities()[0].done[0], True)
    events.observe(store, snapshot, memory)
    monkeypatch.setattr(config, 'EVENT_RETURN_STEPS', 0)
    events.observe(store, snapshot, memory)
    steps(store, 20000)
    monkeypatch.setattr(config, 'EVENT_RETURN_STEPS', 100)
    assert not events.observe(store, snapshot, memory)[1]
    assert store.get(events.KEY)['clocks']['eevee']['next_at'] == 20100


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
    assert not mew_returns.ready(store)
    steps(store, 5100)
    mew_returns.observe(store, snapshot)
    assert not mew_returns.ready(store)
    rewards.earn(store, 302)
    mew_returns.observe(store, snapshot)
    assert mew_returns.ready(store)['key'] == '1'
    # The clock waits while the claim is open, and walks again from the gift.
    steps(store, 20000)
    mew_returns.observe(store, snapshot)
    assert store.get(mew_returns.KEY)['next_at'] is None
    with store.transaction() as db:
        mew_returns.deliver(db, '1', frame=50, seed='mew-seed', reward_id='gift')
    assert not mew_returns.ready(store)
    assert store.get(mew_returns.KEY)['next_at'] == 20100
    assert mew_returns.status(store)['delivered'] == 1
    # Replaying an old Hall of Fame snapshot does not earn another gift.
    rewards.earn(store, 301)
    mew_returns.observe(store, snapshot)
    assert not mew_returns.ready(store)


def test_a_reload_from_before_the_mew_gift_opens_it_again_with_the_same_seed(world):
    store, snapshot, _ = world
    rewards.initialize(store, 1)
    mew_returns.observe(store, snapshot)
    steps(store, 5100)
    mew_returns.observe(store, snapshot)
    rewards.earn(store, 2)
    mew_returns.observe(store, snapshot)
    with store.transaction() as db:
        mew_returns.deliver(db, '1', frame=500, seed='mew-seed', reward_id='gift')
    # The gift's own result save keeps it delivered.
    assert rewards.rewound(store, {'play_clock': {'frames': 100}, 'reward_id': 'gift'}) == []
    assert rewards.rewound(store, {'play_clock': {'frames': 100}}) == [('mew', '1')]
    claim = mew_returns.ready(store)
    assert (claim['key'], claim['seed']) == ('1', 'mew-seed')
    # Its second delivery leaves the clock that already walks from the first.
    steps(store, 5150)
    with store.transaction() as db:
        mew_returns.deliver(db, '1', frame=600, seed='mew-seed', reasons='Already held')
    assert store.get(mew_returns.KEY)['next_at'] == 5200
    assert mew_returns.status(store)['delivered'] == 1


def test_the_schema_moves_mew_counts_into_claims_rows_once(tmp_path):
    import json
    import sqlite3
    from pokesim import return_claims
    from pokesim.gen2.steps import RETURNS
    from pokesim.state import claims as ledger
    Store(tmp_path).close()
    clock = {'interval': 100, 'next_at': 300, 'armed_after_win': None}
    with sqlite3.connect(tmp_path / 'pokesim.sqlite') as db:
        db.execute('PRAGMA user_version = 4')
        for key, delivered in ((mew_returns.KEY, 2), (RETURNS, 0)):
            db.execute('INSERT OR REPLACE INTO kv(k, v) VALUES (?, ?)',
                       (key, json.dumps({**clock, 'delivered': delivered})))
    store = Store(tmp_path)
    try:
        with store.reading() as db:
            moved = [(row['key'], row['state'], row['frame']) for row in ledger.rows(db, return_claims.MEW)]
        assert moved == [('1', ledger.DELIVERED, None), ('2', ledger.DELIVERED, None)]
        assert store.get(mew_returns.KEY) == store.get(RETURNS) == clock
        assert mew_returns.status(store)['delivered'] == 2
        # A moved row has no frame, so no reload reopens it.
        assert rewards.rewound(store, {'play_clock': {'frames': 0}}) == []
    finally:
        store.close()


def test_mew_disable_and_reenable_starts_fresh_requirement(world, monkeypatch):
    store, snapshot, _ = world
    mew_returns.observe(store, snapshot)
    monkeypatch.setattr(config, 'MEW_EVENT', False)
    mew_returns.observe(store, snapshot)
    steps(store, 10000)
    monkeypatch.setattr(config, 'MEW_EVENT', True, raising=False)
    mew_returns.observe(store, snapshot)
    assert store.get(mew_returns.KEY)['next_at'] == 10100
    assert not mew_returns.ready(store)


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
    assert store.get(events.KEY)['clocks']['trade_6']['baseline'] == 1
    # The cartridge sets the trade bit before playing the exchange animation.
    events.write(memory, spec.done[0], True)
    events.observe(store, at_house, memory)
    assert 'trade_6' in events.available(store)
    acquired = replace(at_house, party=(*at_house.party, mon(species=sid(124))))
    events.observe(store, acquired, memory)
    assert 'trade_6' not in events.available(store)


def snorlax_open(world):
    store, snapshot, memory = world
    beaten, hidden = events.snorlax()
    events.write(memory, beaten, True)
    events.write(memory, hidden, True)
    events.observe(store, snapshot, memory)
    steps(store, 5100)
    events.observe(store, snapshot, memory)
    assert 'snorlax' in events.available(store)
    return beaten, hidden


def spare(dex):
    """The PC would release one more copy of any dex number."""
    return False


def kept(dex):
    """The PC would keep one more copy of any dex number."""
    return True


@pytest.mark.parametrize('keeps', [None, kept], ids=['unrated', 'pc keeps one'])
def test_snorlax_battle_is_judged_after_leaving_route_12(world, keeps):
    store, snapshot, memory = world
    beaten, hidden = snorlax_open(world)
    route = replace(snapshot, map=MAPS['ROUTE_12'])
    events.observe(store, route, memory, keeps)
    # The battle hides Snorlax and sets the beaten flag, and the player has not caught it.
    events.write(memory, beaten, True)
    events.write(memory, hidden, True)
    assert events.observe(store, route, memory, keeps) == ([], False)
    # The road stays clear while the player is still on Route 12.
    assert events.read(memory, hidden) and 'snorlax' in events.available(store)
    rows, changed = events.observe(store, snapshot, memory, keeps)
    assert changed and not rows and 'snorlax' in events.available(store)
    assert not events.read(memory, beaten) and not events.read(memory, hidden)


def titles(rows):
    return [row.title for row in rows]


def test_a_snorlax_the_pc_would_release_waits_for_the_next_milestone(world):
    # Blue and Yellow walked to Route 12, met a copy the PC would release and knocked it out. Snorlax
    # was back the moment they left, so the next plan sent them on the same walk.
    store, snapshot, memory = world
    beaten, hidden = snorlax_open(world)
    route = replace(snapshot, map=MAPS['ROUTE_12'])
    events.observe(store, route, memory, spare)
    events.write(memory, beaten, True)
    events.write(memory, hidden, True)
    assert events.observe(store, route, memory, spare) == ([], False)
    rows, changed = events.observe(store, snapshot, memory, spare)
    assert titles(rows) == ['Skipped the returning Snorlax'] and not changed
    assert 'snorlax' not in events.available(store)
    assert events.read(memory, beaten) and events.read(memory, hidden)
    assert store.get(events.KEY)['clocks']['snorlax']['next_at'] == 5200
    assert events.observe(store, snapshot, memory, spare) == ([], False)
    # An older checkpoint cannot bring the spent Snorlax back.
    events.write(memory, beaten, False)
    events.write(memory, hidden, False)
    assert events.observe(store, snapshot, memory, spare)[1]
    assert events.read(memory, beaten) and events.read(memory, hidden)
    # The next milestone asks the PC again. Still a spare, so no visit and no second journal entry.
    steps(store, 5200)
    assert events.observe(store, snapshot, memory, spare) == ([], False)
    assert 'snorlax' not in events.available(store)
    assert store.get(events.KEY)['clocks']['snorlax']['next_at'] == 5300
    # Once the PC would keep one, the milestone after opens the visit.
    steps(store, 5300)
    rows, changed = events.observe(store, snapshot, memory, kept)
    assert titles(rows) == ['Snorlax has returned!'] and changed
    assert 'snorlax' in events.available(store)
    assert not events.read(memory, beaten) and not events.read(memory, hidden)


def test_a_due_snorlax_the_pc_would_release_is_never_offered(world):
    store, snapshot, memory = world
    beaten, hidden = events.snorlax()
    events.write(memory, beaten, True)
    events.write(memory, hidden, True)
    events.observe(store, snapshot, memory, spare)
    steps(store, 5100)
    rows, _ = events.observe(store, snapshot, memory, spare)
    assert 'Skipped the returning Snorlax' in titles(rows) and 'Snorlax has returned!' not in titles(rows)
    assert 'snorlax' not in events.available(store)
    assert events.read(memory, beaten) and events.read(memory, hidden)
    steps(store, 5200)
    assert 'Skipped the returning Snorlax' not in titles(events.observe(store, snapshot, memory, spare)[0])
    assert 'snorlax' not in events.available(store)


def test_the_pc_rating_leaves_returns_that_are_not_encounters_alone(world):
    store, snapshot, memory = world
    spec = next(a for a in events.activities() if a.key == 'eevee')
    events.write(memory, spec.done[0], True)
    events.observe(store, snapshot, memory, spare)
    steps(store, 5100)
    rows, changed = events.observe(store, snapshot, memory, spare)
    assert changed and 'eevee' in events.available(store)
    assert not any(row.title.startswith('Skipped') for row in rows)


def test_the_emulator_rates_a_returning_copy_as_the_pc_would_keep_it():
    from types import SimpleNamespace
    from pokesim.emulator import Emulator
    from test_duplicates import snapshot as boxed, stored
    held = boxed([stored(0, dvs=(0, 8, 8, 8, 8))])
    assert Emulator._keeps_another(SimpleNamespace(policy=SimpleNamespace()), held) is None
    policy = SimpleNamespace(catch_rating=lambda s: None)
    # Bulbasaur is held with common DVs, so a copy rated with none is a spare until the dex misses it.
    assert Emulator._keeps_another(SimpleNamespace(policy=policy), held)(1) is False
    missing = replace(held, owned=frozenset())
    assert Emulator._keeps_another(SimpleNamespace(policy=policy), missing)(1) is True


def test_caught_snorlax_closes_the_return_after_leaving_route_12(world):
    store, snapshot, memory = world
    beaten, hidden = snorlax_open(world)
    route = replace(snapshot, map=MAPS['ROUTE_12'])
    events.observe(store, route, memory)
    events.write(memory, beaten, True)
    events.write(memory, hidden, True)
    caught = replace(route, party=(*route.party, mon(species=sid(143))))
    assert not events.observe(store, caught, memory)[0]
    rows, _ = events.observe(store, replace(caught, map=MAPS['PALLET_TOWN']), memory)
    assert [row.title for row in rows] == ['Caught the returning Snorlax']
    assert 'snorlax' not in events.available(store)
    assert events.read(memory, beaten) and events.read(memory, hidden)


def test_snorlax_lost_to_a_blackout_still_returns(world):
    store, snapshot, memory = world
    beaten, hidden = events.snorlax()
    # A blackout ends the script before the beaten flag, leaving Snorlax hidden.
    events.write(memory, hidden, True)
    events.observe(store, snapshot, memory)
    assert 'snorlax' in store.get(events.KEY)['clocks']
    steps(store, 5100)
    assert events.observe(store, snapshot, memory)[1]
    assert not events.read(memory, hidden) and not events.read(memory, beaten)


FOSSIL_OBJECTS = '''
from pokesim import step_events as events
from pokesim.strategy_data import DATA, MAPS, WORLD
objects = WORLD[MAPS['MT_MOON_B2F']]['objects']
for activity in (a for a in events.activities('helix') if a.key == 'fossil'):
    for base, index in activity.bits[2:]:
        room, obj = DATA['toggle_objects'][index]
        assert room == MAPS['MT_MOON_B2F']
        print(objects[obj][4])
for key in ('eevee', 'dojo', 'snorlax'):
    activity = next(a for a in events.activities() if a.key == key)
    for base, index in activity.bits:
        if base == events.W_TOGGLE_OBJECT_FLAGS:
            room, obj = DATA['toggle_objects'][index]
            print(key, WORLD[room]['objects'][obj][4])
'''


def fossil_objects(output):
    labels = output.split('\n')
    return labels[:2], {line.split()[0]: line.split()[1] for line in labels[2:] if line}


def test_fossil_reset_rearms_both_mt_moon_fossils():
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(FOSSIL_OBJECTS, {})
    fossils, others = fossil_objects(out.getvalue())
    assert ['DOME_FOSSIL' in fossils[0], 'HELIX_FOSSIL' in fossils[1]] == [True, True]
    assert 'EEVEE' in others['eevee'] and 'SNORLAX' in others['snorlax']


def test_yellow_fossil_reset_rearms_its_fossils_not_james():
    from test_yellow_start import run_yellow
    fossils, others = fossil_objects(run_yellow(FOSSIL_OBJECTS))
    assert ['DOME_FOSSIL' in fossils[0], 'HELIX_FOSSIL' in fossils[1]] == [True, True]
    assert 'EEVEE' in others['eevee'] and 'SNORLAX' in others['snorlax']
    assert all('JAMES' not in label for label in fossils)
