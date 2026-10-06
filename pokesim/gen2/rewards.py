"""Optional Gen II gifts with durable claims and verified checkpoint delivery."""
import hashlib
import io
import json
import random
import time
import uuid

from .. import config, rewards
from ..checkpoints import CheckpointStore
from ..runtime.reward_delivery import BARRIER, PENDING, recover_storage
from .ram import Memory, experience_at, read_snapshot
from .steps import RETURNS, consume, ready

MYTHICAL = 'gen2-mythical-gift-v1'


def write(memory, data, symbol, raw, offset=0):
    bank, address = data.symbols[symbol]
    for index, byte in enumerate(raw):
        memory[bank, address + offset + index] = byte


def gift(memory, data, species, seed, box, position):
    rng = random.Random(seed)
    entry = data.species[species]
    raw = bytearray(32)
    raw[0] = species
    moves = []
    for level, move in entry['learnset']:
        if level <= 5 and move not in moves:
            moves.append(move)
    moves = moves[-4:]
    raw[2:2 + len(moves)] = bytes(moves)
    raw[6:8] = rng.randrange(65536).to_bytes(2, 'big')
    raw[8:11] = experience_at(5, entry['growth']).to_bytes(3, 'big')
    raw[21:23] = bytes((rng.randrange(256), rng.randrange(256)))
    raw[23:23 + len(moves)] = bytes(data.moves[move]['pp'] for move in moves)
    raw[27] = 70
    raw[31] = 5
    alphabet = {value: key for key, value in data.charmap.items() if len(value) == 1}
    def encode(text):
        return bytes([alphabet.get(char, 0x7F) for char in text.upper()[:10]] + [0x50]).ljust(11, b'\x50')
    from ..nicknames import configured_pool
    nickname = encode(rng.choice(configured_pool()))
    mem = Memory(memory, data)
    name = 'sBox' if box == mem.byte('wCurBox') & 0x7F else f'sBox{box + 1}'
    if mem.byte(name) != position or not 0 <= position < 20:
        raise ValueError('The gift destination changed')
    write(memory, data, name, raw, 22 + position * 32)
    write(memory, data, name, encode('POKESIM'), 662 + position * 11)
    write(memory, data, name, nickname, 862 + position * 11)
    write(memory, data, name, bytes((species, 0xFF)), 1 + position)
    write(memory, data, name, bytes((position + 1,)))
    offset, bit = divmod(species - 1, 8)
    for symbol in ('wPokedexCaught', 'wPokedexSeen'):
        write(memory, data, symbol, bytes((mem.byte(symbol, offset) | 1 << bit,)), offset)


def deliver(emu):
    league = getattr(config, 'LEAGUE_REWARDS', False)
    mythical = getattr(config, 'MEW_EVENT', False)
    if not league and not mythical or emu.paused or emu.manual_mode or emu.preparation or emu.store.get('trade_hold'):
        return None
    before = read_snapshot(emu.pb.memory, emu.data, emu.frame)
    mem = Memory(emu.pb.memory, emu.data)
    if (not before.valid or not before.started or before.in_battle or mem.byte('wScriptRunning')
            or '┌' in before.tiles[12] or emu.policy.menu):
        return None
    with emu.store.lock:
        ledger = rewards.ledger(emu.store.db)
    species = None
    ordinal = ledger['delivered'] + 1
    if league and ordinal <= ledger['earned']:
        seed = f'{ledger["seed"]}:{ordinal}'
        species = random.Random(seed).choice((152, 155, 158))
        kind = 'league_reward'
    if mythical and before.hall_of_fame_count and 151 not in before.owned and not emu.store.get(MYTHICAL):
        kind, species, seed = 'mew_event', 151, uuid.uuid4().hex
    if ready(emu.store.get(RETURNS), rewards.championship_count(ledger)):
        kind, species, seed = 'mew_return', 151, uuid.uuid4().hex
    space = next(((box, count) for box, count in enumerate(before.box_counts) if count < 20), None)
    if species is None or space is None:
        return None
    source = emu._autosave()
    metadata = emu.store.checkpoint_metadata(source)
    clone = clone_emulator(emu)
    try:
        gift(clone.memory, emu.data, species, seed, *space)
        after = read_snapshot(clone.memory, emu.data, emu.frame)
        existing = {(mon.box, mon.position): mon for mon in before.stored}
        if (after.party != before.party or after.badges != before.badges or after.items != before.items
                or after.event_flags != before.event_flags or after.owned != before.owned | {species}
                or len(after.stored) != len(before.stored) + 1
                or any(existing.get((mon.box, mon.position), mon) != mon for mon in after.stored)):
            raise ValueError('The Gen II gift changed unrelated adventure state')
        output = io.BytesIO()
        clone.save_state(output)
        raw = output.getvalue()
    finally:
        clone.stop(save=False)
    identifier = uuid.uuid4().hex
    directory = emu.store.dir / 'custom-rewards' / identifier
    directory.mkdir(parents=True)
    CheckpointStore.atomic_write(directory / 'result.state', raw)
    metadata = {**metadata, 'sha256': hashlib.sha256(raw).hexdigest(), 'reward_id': identifier}
    record = {'id': identifier, 'phase': 'committed', 'decision': 'COMMIT', 'kind': kind,
              'species': species, 'ordinal': ordinal, 'sha256': metadata['sha256'],
              'metadata': metadata, 'trade_id': emu.store.get('trade_barrier')}
    with emu.store.lock, emu.store.db:
        db = emu.store.db
        db.execute('PRAGMA synchronous=FULL')
        if kind == 'league_reward':
            current = rewards.ledger(db)
            if current['delivered'] + 1 != ordinal or current['earned'] < ordinal:
                raise ValueError('The League gift claim changed')
            current['delivered'] = ordinal
            rewards.save(db, current)
        elif kind == 'mew_return':
            row = db.execute('SELECT v FROM kv WHERE k=?', (RETURNS,)).fetchone()
            if not ready(json.loads(row[0]) if row else None, rewards.championship_count(rewards.ledger(db))):
                raise ValueError('The repeat Mew claim changed')
            consume(db, emu.steps.value['total'])
        else:
            db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (MYTHICAL, json.dumps(identifier)))
        for key, value in ((PENDING, record), (BARRIER, identifier)):
            db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (key, json.dumps(value)))
        db.execute('INSERT INTO events(ts,type,title,body,notable,priority,map,playtime) VALUES (?,?,?,?,?,?,?,?)',
                   (time.time(), 'obtain', f'Received {emu.data.species[species]["name"]} from a custom PokeSim gift',
                    'An optional custom gift joined the PC. This is separate from Cable Club trading.',
                    1, 4, before.map_name, ''))
    try:
        emu._load_state_file(recover_storage(emu.store))
    except BaseException:
        emu.fatal_error = 'A committed Gen II gift needs recovery. Restart this adventure.'
        raise
    return record


def clone_emulator(emu):
    from pyboy import PyBoy
    clone = PyBoy(str(emu.rom), window='null', cgb=True, sound_emulated=True, ram_file=io.BytesIO(bytes(32768)))
    clone.load_state(io.BytesIO(emu._state_bytes()))
    return clone
