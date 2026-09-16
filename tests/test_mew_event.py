"""Custom event gifts preserve inventories and have durable delivery records."""
import json
import sqlite3
import time

import pytest

from pokesim.trade import boxes, event, pair, service
from pokesim.store import Store
from test_trade_save import Memory, populate


def test_event_mew_has_level_five_data_and_clear_provenance():
    slot = event.gift_slot('test adventure')
    assert slot.species == 21 and slot.level == 5
    assert slot.nick == 'MEW' and slot.trainer == 'POKESIM'
    assert slot.struct[8:12] == bytes([1, 0, 0, 0])
    assert slot.struct[29:33] == bytes([35, 0, 0, 0])
    assert int.from_bytes(slot.struct[14:17], 'big') == 135
    assert slot.struct[17:27] == bytes(10)
    assert slot == event.gift_slot('test adventure')
    assert slot.struct[27:29] != event.gift_slot('another adventure').struct[27:29]
    mem = populate(Memory())
    previous = boxes.read_slot(mem, 1, 1)
    boxes.write_slot(mem, 1, 2, slot)
    assert boxes.read_slot(mem, 1, 1) == previous
    assert boxes.read_slot(mem, 1, 2).struct == slot.struct


def test_event_journal_is_atomic_idempotent_and_marks_both_checkpoint_barriers(tmp_path, monkeypatch):
    monkeypatch.setattr(pair, 'PAIR_ROOT', tmp_path / 'pair')
    for name in ('red', 'blue'):
        Store(pair.PAIR_ROOT / name).close()
    service.write(tmp_path / 'transactions/123/result.json', {
        'states': {'red': 'red.state', 'blue': 'blue.state'},
        'gifts': [{'instance': 'red'}],
    })
    event.journal(tmp_path, '123')
    event.journal(tmp_path, '123')
    for name in ('red', 'blue'):
        data = pair.PAIR_ROOT / name
        assert event.received(data) == (name == 'red')
        with sqlite3.connect(data / 'pokesim.sqlite') as db:
            assert json.loads(db.execute("SELECT v FROM kv WHERE k='trade_barrier'").fetchone()[0]) == '123'
            assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == int(name == 'red')
            if name == 'red':
                title, body = db.execute('SELECT title, body FROM events').fetchone()
                assert title == 'Received Mew for defeating the final rival'
                assert 'Rematches do not award another Mew.' in body


def test_recovered_event_is_not_counted_as_a_trade(tmp_path, monkeypatch):
    service.write(tmp_path / 'policy.json', {'peers': {'red': {}, 'blue': {}}})
    c = service.Coordinator(tmp_path)
    monkeypatch.setattr(c, 'worker', lambda *args: None)
    monkeypatch.setattr(c, 'control', lambda *args: None)
    active = {'id': '123', 'ts': 10, 'phase': 'committed', 'kind': 'mew_event'}
    service.write(tmp_path / 'transactions/123/result.json', {
        'kind': 'mew_event', 'event': event.EVENT_KEY, 'gifts': [{'instance': 'red'}],
    })
    c.finish(active)
    c.finish(active)
    status = json.loads((tmp_path / 'public/status.json').read_text())
    assert status['completed'] == 0 and status['history'] == []
    assert len(status['events']) == 1 and status['mew_recipients'] == ['red']


def test_event_waits_for_champion_and_space_and_never_reissues(tmp_path, monkeypatch):
    from dataclasses import replace
    from test_events import snap
    from test_league_reentry import WINS
    from test_strategy import flags
    monkeypatch.setattr(pair, 'PAIR_ROOT', tmp_path / 'pair')
    monkeypatch.setattr(pair, 'ROM_ROOT', tmp_path / 'roms')
    for name in ('red', 'blue'):
        store = Store(pair.PAIR_ROOT / name)
        path = store.states / 'auto-v1-1.state'
        path.write_bytes(b'unchanged checkpoint')
        path.with_suffix('.json').write_text('{}')
        store.close()
    monkeypatch.setattr(pair.CheckpointStore, 'latest_state', lambda self: self.states / 'auto-v1-1.state')
    # The metadata reader is replaced, but no emulator or writer may run for ineligible gifts.
    base = snap(hall_of_fame_count=1, box_counts=(0,) * 12, owned=frozenset({1}))
    for index, state in enumerate((replace(base, hall_of_fame_count=0, event_flags=flags(*WINS)),
                                   replace(base, box_counts=(20,) * 12),
                                   replace(base, owned=frozenset({1, 151})))):
        monkeypatch.setattr(pair, 'inspect', lambda *args: (state, {}, {}))
        event.stage(tmp_path, str(index))
        result = json.loads((tmp_path / 'transactions' / str(index) / 'result.json').read_text())
        assert result['status'] == 'no_opportunity'
    for name in ('red', 'blue'):
        with sqlite3.connect(pair.PAIR_ROOT / name / 'pokesim.sqlite') as db:
            db.execute('INSERT INTO kv(k,v) VALUES (?,?)', (event.EVENT_KEY, json.dumps('previous-event')))
    monkeypatch.setattr(pair, 'inspect', lambda *args: (base, {}, {}))
    event.stage(tmp_path, '9')
    assert json.loads((tmp_path / 'transactions/9/result.json').read_text())['status'] == 'no_opportunity'


def test_final_rival_win_delivers_one_mew_before_hall_of_fame_and_survives_retries(tmp_path, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from pokesim import rewards
    from pokesim.ram import read_box_counts
    from test_events import snap
    from test_strategy import flags

    monkeypatch.setattr(pair, 'PAIR_ROOT', tmp_path / 'pair')
    memories = {}
    before = snap(hall_of_fame_count=0, event_flags=flags('EVENT_BEAT_CHAMPION_RIVAL'),
                  box_counts=(0,) * 12)
    for name in ('red', 'blue'):
        store = Store(pair.PAIR_ROOT / name)
        rewards.earn(store, 3)
        state = store.states / 'auto-v1-1.state'
        state.write_bytes(b'checkpoint')
        state.with_suffix('.json').write_text('{}')
        store.close()
        memories[name] = populate(Memory(), contents=())

    def inspect(rom, path):
        if 'after' not in path.parts:
            return before, {'rom_sha1': 'test'}, {}
        mem = memories[rom.stem]
        return (replace(before, box_counts=read_box_counts(mem), owned=before.owned | {151}),
                {}, {(1, 1): boxes.read_slot(mem, 1, 1)})

    monkeypatch.setattr(pair.CheckpointStore, 'latest_state', lambda self: self.states / 'auto-v1-1.state')
    monkeypatch.setattr(pair, 'inspect', inspect)
    monkeypatch.setattr(event, '_boot', lambda rom, *args: SimpleNamespace(
        memory=memories[rom.stem], stop=lambda **kwargs: None))
    monkeypatch.setattr(event, '_state_bytes', lambda pb: b'gift checkpoint')
    event.stage(tmp_path, '1')
    result = json.loads((tmp_path / 'transactions/1/result.json').read_text())
    assert result['kind'] == 'mew_event'
    assert result['reason'] == 'One-time Mew gift for defeating the final rival'
    assert len(result['gifts']) == 2
    assert all(gift['species'] == event.MEW and gift['ordinal'] is None for gift in result['gifts'])
    event.journal(tmp_path, '1')
    event.journal(tmp_path, '1')
    for name in ('red', 'blue'):
        store = Store(pair.PAIR_ROOT / name)
        assert rewards.status(store) == {'earned': 3, 'delivered': 0, 'pending': 3}
        assert len(store.events()) == 1
        store.close()
    # Even a checkpoint from before receiving or trading Mew cannot earn it again.
    event.stage(tmp_path, '2')
    assert json.loads((tmp_path / 'transactions/2/result.json').read_text())['status'] == 'no_opportunity'


@pytest.mark.parametrize('policy', [
    {'league_rewards': True, 'mew_event': False},
    {'league_rewards': False, 'mew_event': True},
])
@pytest.mark.parametrize('cooling', [False, True])
def test_final_rival_gift_takes_priority_without_trade_board_or_cooldown(tmp_path, monkeypatch, policy, cooling):
    service.write(tmp_path / 'policy.json', {'enabled': True, **policy, 'peers': {'red': {}, 'blue': {}}})
    service.write(tmp_path / 'public/status.json', {
        'last_trade': time.time() if cooling else 0, 'history': [], 'completed': 0,
        'last_operation': 'league_reward'})
    state = {'health': {'ok': True}, 'game': {'party': [{}], 'storage': {'box_counts': [0] * 12}},
             'strategy': {'milestones': {'champion': True}}, 'league_rewards': {'pending': 5}}
    monkeypatch.setattr(service, 'request', lambda *args: state)
    c = service.Coordinator(tmp_path)
    monkeypatch.setattr(c, 'control', lambda *args: {'phase': 'prepared'})
    kinds = []

    def stage(action, transaction):
        kinds.append(json.loads(c.active_path.read_text())['kind'])
        service.write(tmp_path / f'transactions/{transaction}/result.json', {'status': 'no_opportunity'})

    monkeypatch.setattr(c, 'worker', stage)
    c.cycle()
    assert kinds == ['mew_event']


@pytest.mark.parametrize('already_received', ['dex', 'receipt'])
def test_existing_mew_does_not_block_other_rewards_or_create_another_gift(tmp_path, monkeypatch, already_received):
    service.write(tmp_path / 'policy.json', {'enabled': True, 'league_rewards': True,
                  'peers': {'red': {}, 'blue': {}}})
    service.write(tmp_path / 'public/status.json', {
        'last_trade': time.time(), 'history': [], 'completed': 0,
        'mew_recipients': ['red', 'blue'] if already_received == 'receipt' else []})
    state = {'health': {'ok': True},
             'game': {'party': [{}], 'storage': {'box_counts': [0] * 12},
                      'dex_owned': [151] if already_received == 'dex' else []},
             'strategy': {'milestones': {'champion': True}}, 'league_rewards': {'pending': 1}}
    monkeypatch.setattr(service, 'request', lambda *args: state)
    c = service.Coordinator(tmp_path)
    monkeypatch.setattr(c, 'control', lambda *args: {'phase': 'prepared'})
    kinds = []

    def stage(action, transaction):
        kinds.append(json.loads(c.active_path.read_text())['kind'])
        service.write(tmp_path / f'transactions/{transaction}/result.json', {'status': 'no_opportunity'})

    monkeypatch.setattr(c, 'worker', stage)
    c.cycle()
    assert kinds == ['league_reward']


def test_public_policy_reports_separate_mew_gift_for_existing_reward_configuration(tmp_path, monkeypatch):
    from pokesim.broker.app import trading_status

    service.write(tmp_path / 'policy.json', {'enabled': True, 'league_rewards': True, 'mew_event': False})
    monkeypatch.setenv('BROKER_TRADING_DIR', str(tmp_path))
    status = trading_status()
    assert status['league_rewards'] is True
    assert status['mew_event'] is True
