"""Optional custom gifts owned by one adventure, separate from Cable Club trading."""
from __future__ import annotations

import hashlib
import io
import json
import time
import uuid
from pathlib import Path

from ..checkpoints import CheckpointStore
from .. import rewards

PENDING = 'custom-reward-pending-v1'
BARRIER = 'custom-reward-barrier-v1'


def _put(db, key, value):
    db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (key, json.dumps(value)))


def select_reward(snapshot, ledger, mew_received, *, league_rewards=False, mew_event=False):
    """Catch up a missed Mew before draining repeatable League rewards."""
    from ..policies.collection import champion
    from ..trade.event import MEW

    # Eligibility is persistent progress, so enabling the event after victory works too.
    if mew_event and champion(snapshot) and 151 not in snapshot.owned and not mew_received:
        return 'mew_event', None, MEW, str(uuid.uuid4())
    if league_rewards and ledger['earned'] > ledger['delivered']:
        ordinal, species, seed = rewards.selection(ledger)
        return 'league_reward', ordinal, species, seed
    return None


def recover_storage(store):
    """Publish only an unfinished committed reward, never an older completed one."""
    record = store.get(PENDING)
    if not record or record.get('phase') == 'complete':
        return None
    if record.get('decision') != 'COMMIT':
        store.set(PENDING, None)
        return None
    if store.get(BARRIER) != record['id']:
        raise ValueError('The pending custom reward has a different ownership barrier')
    if store.get('trade_barrier') != record.get('trade_id'):
        raise ValueError('A newer trade prevents custom reward recovery')
    raw = (store.dir / 'custom-rewards' / record['id'] / 'result.state').read_bytes()
    if hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise ValueError('The committed custom reward checkpoint failed verification')
    path = store.states / f"auto-v1-reward-{record['id']}.state"
    CheckpointStore.atomic_write(path, raw)
    CheckpointStore.atomic_write(path.with_suffix('.json'), json.dumps(record['metadata']).encode())
    store.set(PENDING, {**record, 'phase': 'complete'})
    return path


def deliver(emu, *, league_rewards=False, mew_event=False):
    """Stage and commit at most one local gift at an unreserved safe point."""
    from ..ram import read_snapshot
    from ..trade import boxes
    from ..trade.event import EVENT_KEY, gift_slot
    from ..trade.execute import register_arrival
    from ..strategy_data import SPECIES

    if not league_rewards and not mew_event:
        return None
    preparation = emu.store.get('interaction_preparation') or {}
    if emu.paused or emu.manual_mode or emu.store.get('trade_hold') or preparation.get('phase') in {'travelling', 'storage', 'rendezvous', 'ready'}:
        return None
    before = read_snapshot(emu.pb.memory, emu.frame)
    if not before.valid or not before.started or before.in_battle or before.textbox or before.start_menu:
        return None
    space = next(((box, count + 1) for box, count in enumerate(before.box_counts, 1) if count < 20), None)
    if space is None:
        return None
    rewards.observe_progress(emu.store, before)
    with emu.store.lock:
        value = rewards.ledger(emu.store.db)
    selected = select_reward(before, value, emu.store.get(EVENT_KEY),
                             league_rewards=league_rewards, mew_event=mew_event)
    if selected is None:
        return None
    kind, ordinal, species, seed = selected
    identifier = uuid.uuid4().hex
    state = emu._state_bytes()
    emu.snapshot = before
    emu._autosave()
    source = emu.store.latest_state()
    metadata = emu.store.checkpoint_metadata(source)
    if not metadata:
        raise ValueError('Custom rewards require a verified source checkpoint')
    old_slots = {(box, position): boxes.read_slot(emu.pb.memory, box, position)
                 for box, count in enumerate(before.box_counts, 1) for position in range(1, count + 1)}
    clone = emu._boot()
    try:
        clone.load_state(io.BytesIO(state))
        gift = gift_slot(seed, species, random_name=kind == 'league_reward')
        box, position = space
        boxes.write_slot(clone.memory, box, position, gift)
        register_arrival(clone.memory, species)
        after = read_snapshot(clone.memory, emu.frame)
        expected_counts = list(before.box_counts)
        expected_counts[box - 1] += 1
        if (not after.valid or after.party != before.party or after.badges != before.badges
                or after.items != before.items or after.owned != before.owned | {SPECIES[species]['dex']}
                or tuple(expected_counts) != after.box_counts):
            raise ValueError('The custom gift changed unexpected gameplay state')
        for slot, old in old_slots.items():
            if boxes.read_slot(clone.memory, *slot) != old:
                raise ValueError('The custom gift changed an existing stored Pokémon')
        actual = boxes.read_slot(clone.memory, box, position)
        if (actual.struct, actual.nickname, actual.ot_name) != (gift.struct, gift.nickname, gift.ot_name):
            raise ValueError('The custom gift did not match the staged Pokémon')
        output = io.BytesIO()
        clone.save_state(output)
        raw = output.getvalue()
    finally:
        clone.stop(save=False)
    directory = emu.store.dir / 'custom-rewards' / identifier
    directory.mkdir(parents=True)
    CheckpointStore.atomic_write(directory / 'result.state', raw)
    metadata = {**metadata, 'sha256': hashlib.sha256(raw).hexdigest(), 'reward_id': identifier}
    memory = dict(metadata['run_memory'])
    memory['championships'] = max(memory.get('championships', 0), rewards.championship_count(value))
    metadata['run_memory'] = memory
    record = {'id': identifier, 'phase': 'staged', 'decision': None, 'kind': kind,
              'ordinal': ordinal, 'species': species, 'sha256': metadata['sha256'],
              'metadata': metadata, 'trade_id': emu.store.get('trade_barrier')}
    emu.store.set(PENDING, record)
    with emu.store.lock, emu.store.db:
        emu.store.db.execute('PRAGMA synchronous=FULL')
        if kind == 'league_reward':
            current = rewards.ledger(emu.store.db)
            if current['delivered'] + 1 != ordinal or current['earned'] < ordinal:
                raise ValueError('Custom reward ownership changed before commitment')
            current['delivered'] = ordinal
            rewards.save(emu.store.db, current)
            title = f"Received {gift.nick} ({SPECIES[species]['name']}) for League reward #{ordinal}"
        else:
            _put(emu.store.db, EVENT_KEY, identifier)
            title = 'Received Mew from the custom PokeSim event'
        _put(emu.store.db, BARRIER, identifier)
        _put(emu.store.db, PENDING, {**record, 'decision': 'COMMIT', 'phase': 'committed'})
        emu.store.db.execute('''INSERT INTO events(ts,type,title,body,notable,priority,map,playtime)
            VALUES (?,?,?,?,?,?,?,?)''', (time.time(), 'obtain', title,
            'An optional custom PokeSim gift joined the PC. This is separate from Cable Club trading.',
            1, 4, before.map_name, ''))
    try:
        path = recover_storage(emu.store)
        emu._load_state_file(path)
        emu.policy.on_restore()
        emu.input_epoch += 1
    except BaseException:
        emu.fatal_error = 'A committed custom reward needs recovery. Restart this adventure.'
        emu.stopping = True
        raise
    return {**record, 'phase': 'complete', 'decision': 'COMMIT'}
