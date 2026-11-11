"""Optional Gen II gifts with durable claims and verified checkpoint delivery."""
import hashlib
import io
import time
import uuid

from .. import config, rewards
from ..checkpoints import CheckpointStore
from ..runtime import trace
from ..runtime.reward_delivery import BARRIER, PENDING, recover_storage
from ..seeds import gift_seed
from ..state import claims, journal, kv
from pokecore.gen2.ram import Memory, read_snapshot
from pokecore.gen2.resets import box_gift
from .steps import RETURNS, consume, ready

MYTHICAL = 'gen2-mythical-gift-v1'


def gift_title(name):
    """The journal title of a Gen II gift. The loop guard and the live soak read it back."""
    return f'Received {name} from a custom PokeSim gift'


def gift(memory, data, species, seed, box, position):
    """Core's box gift, nicknamed from the configured nickname pool.

    With nicknames off or an empty pool, the gift keeps its species name.
    """
    from ..nicknames import configured_pool
    box_gift(memory, data, species, seed, box, position, nicknames=configured_pool() or None)


def deliver(emu):
    league = getattr(config, 'LEAGUE_REWARDS', False)
    mythical = getattr(config, 'MEW_EVENT', False)
    if not league and not mythical or emu.paused or emu.manual_mode or emu.preparation or emu.store.get('trade_hold'):
        return None
    if (guard := getattr(emu, 'loop_guard', None)) and guard.looping(emu.store):
        # A run caught in a loop gets no gifts until it makes real progress.
        return None
    before = read_snapshot(emu.pb.memory, emu.data, emu.frame)
    mem = Memory(emu.pb.memory, emu.data)
    if (not before.valid or not before.started or before.in_battle or mem.byte('wScriptRunning')
            or '┌' in before.tiles[12] or emu.policy.menu):
        return None
    with emu.store.reading() as db:
        ledger = rewards.ledger(db)
        claim = rewards.next_claim(db, 2) if league else None
    species = ordinal = None
    if claim:
        kind = 'league_reward'
        ordinal, species, seed = claim
    championships = rewards.championship_count(ledger)
    if mythical and before.hall_of_fame_count and 151 not in before.owned and not emu.store.get(MYTHICAL):
        kind, species, seed = 'mew_event', 151, gift_seed(emu.adventure_seed, 'mew_event', championships)
    if ready(emu.store.get(RETURNS), championships):
        kind, species, seed = 'mew_return', 151, gift_seed(emu.adventure_seed, 'mew_return', championships)
    if species is None:
        return None
    if kind == 'league_reward' and rewards.held(before, seed, 2):
        # A claim a reload reopened finds its gift still in the PC, so it settles with no second copy.
        rewards.found_held(emu.store, seed, species)
        return None
    space = next(((box, count) for box, count in enumerate(before.box_counts) if count < 20), None)
    if space is None:
        return None
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
        slot = next((mon.box, mon.position) for mon in after.stored if (mon.box, mon.position) not in existing)
        if kind == 'league_reward' and not shiny_gift and (why := rewards.refusal(emu.policy, after, slot, seed, 2)):
            # A copy the PC would release at once is never sent, so a League rerun cannot become a
            # gift and release loop.
            rewards.decline(emu.store, seed, why)
            return None
        output = io.BytesIO()
        clone.save_state(output)
        raw = output.getvalue()
    finally:
        clone.stop(save=False)
    source = emu._autosave()
    metadata = emu.store.checkpoint_metadata(source)
    identifier = uuid.uuid4().hex
    directory = emu.store.dir / 'custom-rewards' / identifier
    directory.mkdir(parents=True)
    CheckpointStore.atomic_write(directory / 'result.state', raw)
    metadata = {**metadata, 'sha256': hashlib.sha256(raw).hexdigest(), 'reward_id': identifier}
    record = {'id': identifier, 'phase': 'committed', 'decision': 'COMMIT', 'kind': kind,
              'species': species, 'ordinal': ordinal, 'sha256': metadata['sha256'],
              'metadata': metadata, 'trade_id': emu.store.get('trade_barrier')}
    from ..progress_events import frame
    with emu.store.durable() as db:
        if kind == 'league_reward':
            rewards.settle(db, seed, claims.DELIVERED, frame=frame(emu.store), species=species,
                           reward_id=identifier)
        elif kind == 'mew_return':
            if not ready(kv.get(db, RETURNS), rewards.championship_count(rewards.ledger(db))):
                raise ValueError('The repeat Mew claim changed')
            consume(db, emu.steps.value['total'])
        else:
            kv.put(db, MYTHICAL, identifier)
        if shiny_gift:
            from ..shiny import record as record_shiny
            record_shiny(db, 'acquired', f'gift-event:{identifier}', species, generation=2)
        from .activity import gift as count_gift
        count_gift(db, identifier, species)
        for key, value in ((PENDING, record), (BARRIER, identifier)):
            kv.put(db, key, value)
        entry = journal.add(db, time.time(), 'obtain', gift_title(emu.data.species[species]['name']),
                            'An optional custom gift joined the PC. This is separate from Cable Club trading.',
                            1, 4, before.map_name)
        from .tracking import record_gift
        record_gift(db, entry, species, frame=frame(emu.store))
    try:
        with trace.reason(emu, 'gift'):
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
