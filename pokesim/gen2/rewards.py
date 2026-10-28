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
from pokecore.gen2.ram import Memory, read_snapshot
from pokecore.gen2.resets import box_gift
from .steps import RETURNS, consume, ready

MYTHICAL = 'gen2-mythical-gift-v1'


def gift(memory, data, species, seed, box, position):
    """Core's box gift, nicknamed from the configured nickname pool."""
    from ..nicknames import configured_pool
    box_gift(memory, data, species, seed, box, position, nicknames=configured_pool())


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
        shiny_gift = any(mon.shiny for mon in after.stored if (mon.box, mon.position) not in existing)
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
        if shiny_gift:
            from ..shiny import record as record_shiny
            record_shiny(db, 'acquired', f'gift-event:{identifier}', species, generation=2)
        from .activity import gift as count_gift
        count_gift(db, identifier, species)
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
    from pokecore.gen2.clock import boot
    clone = boot(str(emu.rom), sound=True)
    clone.load_state(io.BytesIO(emu._state_bytes()))
    return clone
