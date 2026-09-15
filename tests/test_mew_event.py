"""Custom event gifts preserve inventories and have durable delivery records."""
import json
import sqlite3

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
    for index, state in enumerate((replace(base, hall_of_fame_count=0),
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
