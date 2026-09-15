"""An optional one-time PokeSim Mew distribution using held checkpoints."""
import hashlib
import json
import sqlite3
from pathlib import Path

from . import boxes, pair
from .execute import _boot, _publish, _state_bytes, register_arrival
from ..policies.collection import champion
from ..strategy_data import MOVES, SPECIES

EVENT_KEY = 'pokesim-mew-v1'
MEW = 21


def gift_slot(seed):
    """Build a level-five Mew with ordinary DVs, no training, and event provenance."""
    digest = hashlib.sha256(seed.encode()).digest()
    attack, defense = digest[0] >> 4, digest[0] & 15
    speed, special = digest[1] >> 4, digest[1] & 15
    hp_dv = ((attack & 1) << 3) | ((defense & 1) << 2) | ((speed & 1) << 1) | (special & 1)
    base = SPECIES[MEW]
    level = 5
    struct = bytearray(boxes.BOX_STRUCT)
    struct[0] = MEW
    hp = ((base['stats'][0] + hp_dv) * 2 * level) // 100 + level + 10
    struct[1:3] = hp.to_bytes(2, 'big')
    struct[3] = level
    struct[5:7] = bytes(base['types'])
    struct[7] = base['catch_rate']
    struct[8] = 1
    struct[12:14] = digest[2:4]
    experience = 6 * level ** 3 // 5 - 15 * level ** 2 + 100 * level - 140
    struct[14:17] = experience.to_bytes(3, 'big')
    struct[27:29] = digest[:2]
    struct[29] = MOVES[1]['pp']
    return boxes.Slot(0, 0, bytes(struct), boxes.encode_text('MEW'), boxes.encode_text('POKESIM'))


def received(data):
    with sqlite3.connect(data / 'pokesim.sqlite') as db:
        row = db.execute('SELECT v FROM kv WHERE k=?', (EVENT_KEY,)).fetchone()
    return bool(row and json.loads(row[0]))


def stage(root, transaction):
    work = root / 'transactions' / transaction
    sources, eligible, previous = {}, {}, {}
    for name in ('red', 'blue'):
        data = pair.PAIR_ROOT / name
        state = pair.CheckpointStore(data / 'states').latest_state()
        if state is None:
            raise ValueError('No checkpoint available')
        rom = pair.ROM_ROOT / f'{name}.gb'
        snapshot, metadata, slots = pair.inspect(rom, state)
        space = next(((box, count + 1) for box, count in enumerate(snapshot.box_counts, 1)
                      if count < boxes.BOX_CAPACITY), None)
        eligible[name] = space if champion(snapshot) and 151 not in snapshot.owned and not received(data) else None
        previous[name] = snapshot, metadata, slots
        backup = work / 'before' / name
        backup.mkdir(parents=True, exist_ok=True)
        for path in (state, state.with_suffix('.json')):
            pair.CheckpointStore.atomic_write(backup / path.name, path.read_bytes())
        with sqlite3.connect(data / 'pokesim.sqlite') as db, sqlite3.connect(backup / 'pokesim.sqlite') as dest:
            db.backup(dest)
        sources[name] = rom, backup / state.name
    if not any(eligible.values()):
        pair.write_json(work / 'result.json', {'status': 'no_opportunity'})
        return
    states, hashes, gifts = {}, {}, []
    for name, (rom, state) in sources.items():
        before, metadata, old_slots = previous[name]
        pb = _boot(rom, state, metadata['rom_sha1'])
        try:
            if eligible[name]:
                box, position = eligible[name]
                gift = gift_slot(f'{EVENT_KEY}:{name}:{transaction}')
                boxes.write_slot(pb.memory, box, position, gift)
                register_arrival(pb.memory, MEW)
                gifts.append({'instance': name, 'name': 'Mew', 'level': 5, 'box': box, 'position': position})
            target = work / 'after' / name / f'auto-v1-trade-{transaction}.state'
            target.parent.mkdir(parents=True, exist_ok=True)
            _publish(target, _state_bytes(pb), dict(metadata, trade_id=transaction))
        finally:
            pb.stop(save=False)
        after, _, slots = pair.inspect(rom, target)
        assert before.party == after.party
        assert before.badges == after.badges and before.items == after.items
        assert before.owned <= after.owned
        assert all(slots[key] == value for key, value in old_slots.items())
        expected_counts = list(before.box_counts)
        if eligible[name]:
            box, position = eligible[name]
            expected_counts[box - 1] += 1
            actual = slots[(box, position)]
            assert (actual.struct, actual.nickname, actual.ot_name) == (gift.struct, gift.nickname, gift.ot_name)
            assert after.owned == before.owned | {151}
        else:
            assert before.owned == after.owned
        assert tuple(expected_counts) == after.box_counts
        states[name] = str(target)
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    pair.write_json(work / 'result.json', {
        'status': 'staged', 'kind': 'mew_event', 'event': EVENT_KEY,
        'id': transaction, 'reason': 'One-time postgame PokeSim Mew event',
        'gifts': gifts, 'states': states, 'hashes': hashes,
    })


def journal(root, transaction):
    result = json.loads((root / 'transactions' / transaction / 'result.json').read_text())
    recipients = {gift['instance'] for gift in result['gifts']}
    for name in result['states']:
        with sqlite3.connect(pair.PAIR_ROOT / name / 'pokesim.sqlite') as db:
            db.execute('CREATE TABLE IF NOT EXISTS completed_events (id TEXT PRIMARY KEY)')
            cursor = db.execute('INSERT OR IGNORE INTO completed_events(id) VALUES (?)', (transaction,))
            if cursor.rowcount:
                db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', ('trade_barrier', json.dumps(transaction)))
                if name in recipients:
                    db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (EVENT_KEY, json.dumps(transaction)))
                    db.execute("INSERT INTO events(ts,type,title,body,notable,priority,map,playtime) VALUES (strftime('%s','now'),'obtain',?,?,1,4,'PokeSim event','')",
                               ('Received Mew from the PokeSim event',
                                'A one-time level-5 Mew gift after becoming Champion. This is a custom PokeSim distribution, not an official Nintendo event.'))
