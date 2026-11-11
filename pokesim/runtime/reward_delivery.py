"""The one gift pipeline both generations deliver through, and its Gen I side.

These gifts are optional, owned by one adventure and separate from Cable Club trading. A delivery
takes at most one gift through the steps of docs/design/goal-system.md section 7. The open Mew
return claim goes first, then the first Mew event, then the oldest open League claim. A claim whose
gift the cartridge already holds settles with no write. The gift is written on a clone and checked,
the worth oracle may decline a League gift, and the result checkpoint commits with its claim in one
durable transaction. A generation's ``Side`` says when its game is at a safe point, how a gift is
written and checked, and what else the commit records. Gen II's side is in ``gen2/rewards.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import time
import uuid

from ..checkpoints import CheckpointStore
from .. import rewards
from ..seeds import gift_seed
from ..state import claims, journal, kv
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


@dataclass(frozen=True)
class Staged:
    """A gift written on a clone and checked: the clone's snapshot, the box slot the gift fills,
    whether it is shiny, and what the side keeps for its journal title and receipt."""
    after: object
    slot: tuple | None
    shiny: bool
    written: object = None


class Side:
    """What one generation tells the pipeline. Gen I's side is ``Gen1`` below."""
    generation = 1
    # The species the Mew gifts write, in the generation's own species numbers.
    mew = 151
    # The journal entry's detail line.
    note = 'An optional custom gift joined the PC. This is separate from Cable Club trading.'
    fatal = 'A committed custom reward needs recovery. Restart this adventure.'

    def ready(self, emu):
        """The snapshot at a safe point to gift, or None."""
        raise NotImplementedError

    def champion(self, snapshot):
        """Whether this game has beaten the League, which makes the first Mew due."""
        return bool(snapshot.hall_of_fame_count)

    def mew_received(self, emu):
        """The marker the first Mew gift left, or None."""
        raise NotImplementedError

    def space(self, before):
        """The (box, position) the next gift fills, or None when every box is full."""
        raise NotImplementedError

    def clone(self, emu):
        """A second emulator at the live state, which the pipeline stops."""
        raise NotImplementedError

    def write(self, emu, clone, before, kind, species, seed, space):
        """Write the gift into the clone, check that nothing else changed, and return ``Staged``."""
        raise NotImplementedError

    def metadata(self, emu, before, championships):
        """Save the live game and return the metadata of that source checkpoint."""
        raise NotImplementedError

    def deliver_mew(self, db, emu, number, **fields):
        """Mark Mew return claim ``number`` delivered inside the caller's transaction."""
        raise NotImplementedError

    def title(self, emu, kind, species, ordinal, staged):
        """The journal title of the gift."""
        raise NotImplementedError

    def committed(self, db, emu, kind, species, staged, identifier, entry):
        """Record what else the gift's transaction keeps, after its journal ``entry``."""
        raise NotImplementedError

    def restored(self, emu):
        """Run once the result checkpoint has loaded."""

    def failed(self, emu):
        """Mark the adventure for recovery when the committed gift did not load."""
        emu.fatal_error = self.fatal


class Gen1(Side):
    """Red, Blue and Yellow."""
    note = 'An optional custom PokeSim gift joined the PC. This is separate from Cable Club trading.'

    @property
    def mew(self):
        from ..trade.event import MEW
        return MEW

    def ready(self, emu):
        """The snapshot at a safe point, or None. It also keeps the unlocks the snapshot shows."""
        from ..ram import read_snapshot
        preparation = emu.store.get('interaction_preparation') or {}
        if preparation.get('phase') in {'travelling', 'storage', 'rendezvous', 'ready'}:
            return None
        before = read_snapshot(emu.pb.memory, emu.frame)
        if not before.valid or not before.started or before.in_battle or before.textbox or before.start_menu:
            return None
        rewards.observe_progress(emu.store, before)
        return before

    def champion(self, snapshot):
        from ..policies.collection import champion
        return champion(snapshot)

    def mew_received(self, emu):
        from ..trade.event import EVENT_KEY
        return emu.store.get(EVENT_KEY)

    def space(self, before):
        return next(((box, count + 1) for box, count in enumerate(before.box_counts, 1) if count < 20), None)

    def clone(self, emu):
        state = emu._state_bytes()
        clone = emu._boot()
        try:
            clone.load_state(io.BytesIO(state))
        except BaseException:
            clone.stop(save=False)
            raise
        return clone

    def write(self, emu, clone, before, kind, species, seed, space):
        from ..ram import read_snapshot
        from ..strategy_data import SPECIES
        from ..trade import boxes
        from ..trade.event import gift_slot
        from ..trade.execute import register_arrival
        old_slots = {(box, position): boxes.read_slot(emu.pb.memory, box, position)
                     for box, count in enumerate(before.box_counts, 1) for position in range(1, count + 1)}
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
        return Staged(after, slot, rewards.staged_shiny(seed), gift)

    def metadata(self, emu, before, championships):
        emu.snapshot = before
        emu._autosave()
        metadata = emu.store.checkpoint_metadata(emu.store.latest_state())
        if metadata:
            memory = dict(metadata['run_memory'])
            memory['championships'] = max(memory.get('championships', 0), championships)
            metadata = {**metadata, 'run_memory': memory}
        return metadata

    def deliver_mew(self, db, emu, number, **fields):
        from .. import mew_returns
        mew_returns.deliver(db, number, **fields)

    def title(self, emu, kind, species, ordinal, staged):
        if kind == 'league_reward':
            return gift_title(staged.written.nick, species, ordinal)
        return ('Received Mew after walking and winning the League' if kind == 'mew_return'
                else 'Received Mew from the custom PokeSim event')

    def committed(self, db, emu, kind, species, staged, identifier, entry):
        from ..catches import record_gift
        from ..progress_events import frame
        from ..trade.event import EVENT_KEY
        if kind != 'league_reward':
            kv.put(db, EVENT_KEY, identifier)
        record_gift(db, entry, species, staged.written, frame=frame(emu.store))

    def restored(self, emu):
        emu.policy.on_restore()
        emu.input_epoch += 1

    def failed(self, emu):
        emu.fatal_error = self.fatal
        emu.stopping = True


GEN1 = Gen1()


def select_reward(snapshot, claim, championships, mew_received, *, mew_event=False, seed=None, side=GEN1):
    """Catch up a missed Mew before draining repeatable League rewards. ``claim`` is the oldest open
    League claim (rewards.next_claim) and ``seed`` the adventure seed."""
    # Eligibility is persistent progress, so enabling the event after victory works too.
    if mew_event and side.champion(snapshot) and 151 not in snapshot.owned and not mew_received:
        return 'mew_event', None, side.mew, gift_seed(seed, 'mew_event', championships)
    if claim:
        return ('league_reward', *claim)
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
    """Stage and commit at most one Gen I gift at an unreserved safe point."""
    return deliver_with(emu, GEN1, league_rewards=league_rewards, mew_event=mew_event)


def deliver_with(emu, side, *, league_rewards=False, mew_event=False):
    """Stage and commit at most one gift for ``side``'s game. Returns the committed record, or None."""
    from .. import mew_returns
    from ..progress_events import frame

    if not league_rewards and not mew_event:
        return None
    if emu.paused or emu.manual_mode or emu.store.get('trade_hold'):
        return None
    if (guard := getattr(emu, 'loop_guard', None)) and guard.looping(emu.store):
        # A run caught in a loop gets no gifts until it makes real progress.
        return None
    before = side.ready(emu)
    if before is None:
        return None
    with emu.store.reading() as db:
        value = rewards.ledger(db)
        claim = rewards.next_claim(db, side.generation) if league_rewards else None
        mew = mew_returns.ready_db(db) if mew_event else None
    # A claim a reload reopened finds its gift still in the PC, so it settles with no second copy.
    if claim and rewards.held(before, claim[2], side.generation):
        rewards.found_held(emu.store, claim[2], claim[1])
        return None
    if mew and mew['seed'] and rewards.held(before, mew['seed'], side.generation):
        with emu.store.transaction() as db:
            side.deliver_mew(db, emu, mew['key'], frame=frame(emu.store), seed=mew['seed'], reasons='Already held')
        return None
    space = side.space(before)
    if space is None:
        return None
    championships = rewards.championship_count(value)
    if mew:
        # A claim a reload reopened writes the same Mew again.
        selected = ('mew_return', mew['key'], side.mew,
                    mew['seed'] or gift_seed(emu.adventure_seed, 'mew_return', championships))
    else:
        selected = select_reward(before, claim, championships, side.mew_received(emu), mew_event=mew_event,
                                 seed=emu.adventure_seed if mew_event else None, side=side)
    if selected is None:
        return None
    kind, ordinal, species, seed = selected
    clone = side.clone(emu)
    try:
        staged = side.write(emu, clone, before, kind, species, seed, space)
        if (kind == 'league_reward' and staged.slot and not staged.shiny
                and (why := rewards.refusal(emu.policy, staged.after, staged.slot, seed, side.generation))):
            # A copy the PC would release at once is never sent, so a League rerun cannot become a
            # gift and release loop. A shiny gift is always sent.
            rewards.decline(emu.store, seed, why)
            return None
        output = io.BytesIO()
        clone.save_state(output)
        raw = output.getvalue()
    finally:
        clone.stop(save=False)
    metadata = side.metadata(emu, before, championships)
    if not metadata:
        raise ValueError('Custom rewards require a verified source checkpoint')
    identifier = uuid.uuid4().hex
    directory = emu.store.dir / 'custom-rewards' / identifier
    directory.mkdir(parents=True)
    CheckpointStore.atomic_write(directory / 'result.state', raw)
    metadata = {**metadata, 'sha256': hashlib.sha256(raw).hexdigest(), 'reward_id': identifier}
    record = {'id': identifier, 'phase': 'staged', 'decision': None, 'kind': kind,
              'ordinal': ordinal, 'species': species, 'sha256': metadata['sha256'],
              'metadata': metadata, 'trade_id': emu.store.get('trade_barrier')}
    emu.store.set(PENDING, record)
    with emu.store.durable() as db:
        if kind == 'league_reward':
            rewards.settle(db, seed, claims.DELIVERED, frame=frame(emu.store), species=species,
                           reward_id=identifier)
        elif kind == 'mew_return':
            side.deliver_mew(db, emu, ordinal, frame=frame(emu.store), seed=seed, reward_id=identifier)
        kv.put(db, BARRIER, identifier)
        kv.put(db, PENDING, {**record, 'decision': 'COMMIT', 'phase': 'committed'})
        entry = journal.add(db, time.time(), 'obtain', side.title(emu, kind, species, ordinal, staged),
                            side.note, 1, 4, before.map_name)
        side.committed(db, emu, kind, species, staged, identifier, entry)
    try:
        path = recover_storage(emu.store)
        with trace.reason(emu, 'gift'):
            emu._load_state_file(path)
        side.restored(emu)
    except BaseException:
        side.failed(emu)
        raise
    return {**record, 'phase': 'complete', 'decision': 'COMMIT'}
