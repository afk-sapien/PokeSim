"""Custom Pokémon rewards delivered through held checkpoint transactions."""
import hashlib
import json
import sqlite3

from . import boxes, pair
from .pair import verified
from .execute import _boot, _publish, _state_bytes, register_arrival
from ..policies.collection import champion
from ..strategy_data import MOVES, SPECIES
from .. import rewards

EVENT_KEY = 'pokesim-mew-v1'
MEW = 21


def gift_slot(seed, species=MEW, *, random_name=False):
    """Build a level-five Pokémon with ordinary DVs, no training, and event provenance."""
    digest = hashlib.sha256(seed.encode()).digest()
    attack, defense = digest[0] >> 4, digest[0] & 15
    speed, special = digest[1] >> 4, digest[1] & 15
    hp_dv = ((attack & 1) << 3) | ((defense & 1) << 2) | ((speed & 1) << 1) | (special & 1)
    base = SPECIES[species]
    level = 5
    struct = bytearray(boxes.BOX_STRUCT)
    struct[0] = species
    hp = ((base['stats'][0] + hp_dv) * 2 * level) // 100 + level + 10
    struct[1:3] = hp.to_bytes(2, 'big')
    struct[3] = level
    struct[5:7] = bytes(base['types'])
    struct[7] = base['catch_rate']
    moves = list(dict.fromkeys(base['initial_moves'] + [move for at, move in base['learnset'] if at <= level]))[-4:]
    struct[8:8 + len(moves)] = bytes(moves)
    struct[12:14] = digest[2:4]
    experience = {'MEDIUM_SLOW': 6 * level ** 3 // 5 - 15 * level ** 2 + 100 * level - 140,
                  'MEDIUM_FAST': level ** 3, 'SLOW': 5 * level ** 3 // 4,
                  'FAST': 4 * level ** 3 // 5}[base['growth']]
    struct[14:17] = experience.to_bytes(3, 'big')
    struct[27:29] = digest[:2]
    struct[29:29 + len(moves)] = bytes(MOVES[move]['pp'] for move in moves)
    nickname = base['name']
    if random_name:
        from ..policies.naming import POKEMON_NAMES
        # Keep naming independent of the draw and stable across delivery retries.
        name_hash = hashlib.sha256(f'nickname:{seed}'.encode()).digest()
        nickname = POKEMON_NAMES[int.from_bytes(name_hash, 'big') % len(POKEMON_NAMES)]
    return boxes.Slot(0, 0, bytes(struct), boxes.encode_text(nickname), boxes.encode_text('POKESIM'))


def received(data):
    with sqlite3.connect(data / 'pokesim.sqlite') as db:
        row = db.execute('SELECT v FROM kv WHERE k=?', (EVENT_KEY,)).fetchone()
    return bool(row and json.loads(row[0]))


def stage(root, transaction, league_rewards=False):
    work = root / 'transactions' / transaction
    sources, eligible, previous, claims = {}, {}, {}, {}
    for name in ('red', 'blue'):
        data = pair.PAIR_ROOT / name
        state = pair.CheckpointStore(data / 'states').latest_state()
        if state is None:
            raise ValueError('No checkpoint available')
        rom = pair.ROM_ROOT / f'{name}.gb'
        snapshot, metadata, slots = pair.inspect(rom, state)
        space = next(((box, count + 1) for box, count in enumerate(snapshot.box_counts, 1)
                      if count < boxes.BOX_CAPACITY), None)
        if league_rewards:
            with sqlite3.connect(data / 'pokesim.sqlite') as db:
                claims[name] = rewards.ledger(db)
            eligible[name] = space if claims[name]['earned'] > claims[name]['delivered'] else None
        else:
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
                claim = {**claims.get(name, {}), 'unlocks': sorted(
                    set(claims.get(name, {}).get('unlocks', ())) | rewards.progress_unlocks(before))}
                ordinal, species, seed = (rewards.selection(claim) if league_rewards
                                          else (None, MEW, f'{EVENT_KEY}:{name}:{transaction}'))
                gift = gift_slot(seed, species, random_name=league_rewards)
                boxes.write_slot(pb.memory, box, position, gift)
                register_arrival(pb.memory, species)
                gifts.append({'instance': name, 'name': SPECIES[species]['name'].title(), 'species': species,
                              'ordinal': ordinal, 'level': 5, 'box': box, 'position': position})
                if league_rewards:
                    memory = dict(metadata.get('run_memory', {}))
                    memory['championships'] = max(memory.get('championships', 0), rewards.championship_count(claims[name]))
                    metadata = dict(metadata, run_memory=memory)
            target = work / 'after' / name / f'auto-v1-trade-{transaction}.state'
            target.parent.mkdir(parents=True, exist_ok=True)
            _publish(target, _state_bytes(pb), dict(metadata, trade_id=transaction))
        finally:
            pb.stop(save=False)
        after, _, slots = pair.inspect(rom, target)
        verified(before.party == after.party, f'{name} party changed')
        verified(before.badges == after.badges and before.items == after.items,
                 f'{name} badges or bag changed')
        verified(before.owned <= after.owned, f'{name} lost Pokédex entries')
        verified(all(slots[key] == value for key, value in old_slots.items()),
                 f'{name} changed a box slot that the gift should not touch')
        expected_counts = list(before.box_counts)
        if eligible[name]:
            box, position = eligible[name]
            expected_counts[box - 1] += 1
            actual = slots[(box, position)]
            verified((actual.struct, actual.nickname, actual.ot_name)
                     == (gift.struct, gift.nickname, gift.ot_name),
                     f'{name} stored a different Pokémon than the gift')
            verified(after.owned == before.owned | {SPECIES[gift.species]['dex']},
                     f'{name} Pokédex did not gain exactly the gift')
        else:
            verified(before.owned == after.owned, f'{name} Pokédex changed without a gift')
        verified(tuple(expected_counts) == after.box_counts, f'{name} box counts are wrong')
        states[name] = str(target)
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    pair.write_json(work / 'result.json', {
        'status': 'staged', 'kind': 'league_reward' if league_rewards else 'mew_event',
        'event': rewards.KEY if league_rewards else EVENT_KEY,
        'id': transaction, 'reason': 'Championship Pokémon reward' if league_rewards else 'One-time Mew gift for defeating the final rival',
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
                if name in recipients and result.get('kind') == 'league_reward':
                    gift = next(g for g in result['gifts'] if g['instance'] == name)
                    value = rewards.ledger(db)
                    if not value['delivered'] + 1 == gift['ordinal'] <= value['earned']:
                        raise ValueError('Reward claim is out of order')
                    value['delivered'] = gift['ordinal']
                    rewards.save(db, value)
                    db.execute("INSERT INTO events(ts,type,title,body,notable,priority,map,playtime) VALUES (strftime('%s','now'),'obtain',?,?,1,4,'Championship reward','')",
                               (f"Received {gift['name']} for Championship #{gift['ordinal']}",
                                f"A level-5 {gift['name']} joined the PC. Each League victory earns a random PokeSim reward."))
                elif name in recipients:
                    db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (EVENT_KEY, json.dumps(transaction)))
                    db.execute("INSERT INTO events(ts,type,title,body,notable,priority,map,playtime) VALUES (strftime('%s','now'),'obtain',?,?,1,4,'Final rival reward','')",
                               ('Received Mew for defeating the final rival',
                                'A one-time level-5 Mew joined the PC after defeating the rival who held the Champion title. Rematches do not award another Mew.'))
