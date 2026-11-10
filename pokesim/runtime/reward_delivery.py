"""Optional custom gifts owned by one adventure, separate from Cable Club trading."""
from __future__ import annotations

import hashlib
import io
import json
import time
import uuid

from ..checkpoints import CheckpointStore
from .. import rewards
from ..seeds import gift_seed
from ..state import journal, kv
from . import trace

PENDING = 'custom-reward-pending-v1'
BARRIER = 'custom-reward-barrier-v1'
# Gifts are paced in emulated frames so a fast or uncapped run sees the same gift rate per game hour.
SPACING_FRAMES = 3600
RETRY_FRAMES = 60


def gift_title(nick, species, ordinal):
    """The journal title of a Gen I League gift. The loop guard and the live soak read it back."""
    from ..strategy_data import SPECIES
    return f"Received {nick} ({SPECIES[species]['name']}) for League reward #{ordinal}"


def reward_due(emu):
    """A reload can move the frame counter back, which makes the next check due at once."""
    last = getattr(emu, '_reward_frame', None)
    return last is None or emu.frame < last or emu.frame - last >= getattr(emu, '_reward_wait', 0)


def schedule(emu, delivered):
    """A battle or menu should not postpone a pending gift for a whole spacing interval."""
    emu._reward_frame = emu.frame
    emu._reward_wait = SPACING_FRAMES if delivered else RETRY_FRAMES


def select_reward(snapshot, ledger, mew_received, *, league_rewards=False, mew_event=False, seed=None):
    """Catch up a missed Mew before draining repeatable League rewards. ``seed`` is the adventure seed."""
    from ..policies.collection import champion
    from ..trade.event import MEW

    # Eligibility is persistent progress, so enabling the event after victory works too.
    if mew_event and champion(snapshot) and 151 not in snapshot.owned and not mew_received:
        return 'mew_event', None, MEW, gift_seed(seed, 'mew_event', rewards.championship_count(ledger))
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
    if (guard := getattr(emu, 'loop_guard', None)) and guard.looping(emu.store):
        # A run caught in a loop gets no gifts until it makes real progress.
        return None
    before = read_snapshot(emu.pb.memory, emu.frame)
    if not before.valid or not before.started or before.in_battle or before.textbox or before.start_menu:
        return None
    space = next(((box, count + 1) for box, count in enumerate(before.box_counts, 1) if count < 20), None)
    if space is None:
        return None
    rewards.observe_progress(emu.store, before)
    with emu.store.reading() as db:
        value = rewards.ledger(db)
    selected = select_reward(before, value, emu.store.get(EVENT_KEY),
                             league_rewards=league_rewards, mew_event=mew_event, seed=emu.adventure_seed)
    from .. import mew_returns
    championships = rewards.championship_count(value)
    if mew_event and mew_returns.ready(emu.store, championships):
        from ..trade.event import MEW
        selected = ('mew_return', None, MEW, gift_seed(emu.adventure_seed, 'mew_return', championships))
    if selected is None:
        return None
    kind, ordinal, species, seed = selected
    identifier = uuid.uuid4().hex
    state = emu._state_bytes()
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
        held = {(mon['box'], mon['position']) for mon in before.storage_entries()}
        slot = next((slot for mon in after.storage_entries() if (slot := (mon['box'], mon['position'])) not in held), None)
        if kind == 'league_reward' and slot and not rewards.staged_shiny(seed) and rewards.wasted(emu.policy, after, slot, seed):
            # A copy the PC would release at once is never sent, so a League rerun cannot become a
            # gift and release loop.
            rewards.skip(emu.store, ordinal)
            return None
        output = io.BytesIO()
        clone.save_state(output)
        raw = output.getvalue()
    finally:
        clone.stop(save=False)
    emu.snapshot = before
    emu._autosave()
    source = emu.store.latest_state()
    metadata = emu.store.checkpoint_metadata(source)
    if not metadata:
        raise ValueError('Custom rewards require a verified source checkpoint')
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
    with emu.store.durable() as db:
        if kind == 'league_reward':
            current = rewards.ledger(db)
            if current['delivered'] + 1 != ordinal or current['earned'] < ordinal:
                raise ValueError('Custom reward ownership changed before commitment')
            current['delivered'] = ordinal
            rewards.save(db, current)
            title = gift_title(gift.nick, species, ordinal)
        else:
            if kind == 'mew_return' and not mew_returns.ready_db(db, rewards.championship_count(rewards.ledger(db))):
                raise ValueError('The Mew walking opportunity is no longer available')
            mew_returns.consume(db)
            kv.put(db, EVENT_KEY, identifier)
            title = ('Received Mew after walking and winning the League' if kind == 'mew_return'
                     else 'Received Mew from the custom PokeSim event')
        kv.put(db, BARRIER, identifier)
        kv.put(db, PENDING, {**record, 'decision': 'COMMIT', 'phase': 'committed'})
        entry = journal.add(db, time.time(), 'obtain', title,
                            'An optional custom PokeSim gift joined the PC. This is separate from Cable Club trading.',
                            1, 4, before.map_name)
        from ..catches import record_gift
        from ..progress_events import frame
        record_gift(db, entry, species, gift, frame=frame(emu.store))
    try:
        path = recover_storage(emu.store)
        with trace.reason(emu, 'gift'):
            emu._load_state_file(path)
        emu.policy.on_restore()
        emu.input_epoch += 1
    except BaseException:
        emu.fatal_error = 'A committed custom reward needs recovery. Restart this adventure.'
        emu.stopping = True
        raise
    return {**record, 'phase': 'complete', 'decision': 'COMMIT'}
