"""The Gen II side of the gift pipeline in ``runtime/reward_delivery.py``."""
import io

from .. import config
from ..runtime.reward_delivery import Side, Staged, deliver_with
from ..state import kv
from pokecore.gen2.ram import Memory, read_snapshot
from pokecore.gen2.resets import box_gift

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


class Gen2(Side):
    """Gold, Silver and Crystal."""
    generation = 2
    fatal = 'A committed Gen II gift needs recovery. Restart this adventure.'

    def ready(self, emu):
        if emu.preparation:
            return None
        before = read_snapshot(emu.pb.memory, emu.data, emu.frame)
        mem = Memory(emu.pb.memory, emu.data)
        if (not before.valid or not before.started or before.in_battle or mem.byte('wScriptRunning')
                or '┌' in before.tiles[12] or emu.policy.menu):
            return None
        return before

    def mew_received(self, emu):
        return emu.store.get(MYTHICAL)

    def space(self, before):
        return next(((box, count) for box, count in enumerate(before.box_counts) if count < 20), None)

    def clone(self, emu):
        return clone_emulator(emu)

    def write(self, emu, clone, before, kind, species, seed, space):
        gift(clone.memory, emu.data, species, seed, *space)
        after = read_snapshot(clone.memory, emu.data, emu.frame)
        existing = {(mon.box, mon.position): mon for mon in before.stored}
        if (after.party != before.party or after.badges != before.badges or after.items != before.items
                or after.event_flags != before.event_flags or after.owned != before.owned | {species}
                or len(after.stored) != len(before.stored) + 1
                or any(existing.get((mon.box, mon.position), mon) != mon for mon in after.stored)):
            raise ValueError('The Gen II gift changed unrelated adventure state')
        new = next(mon for mon in after.stored if (mon.box, mon.position) not in existing)
        return Staged(after, (new.box, new.position), bool(new.shiny))

    def metadata(self, emu, before, championships):
        return emu.store.checkpoint_metadata(emu._autosave())

    def deliver_mew(self, db, emu, number, **fields):
        from .steps import deliver
        deliver(db, number, emu.steps.value['total'], **fields)

    def title(self, emu, kind, species, ordinal, staged):
        return gift_title(emu.data.species[species]['name'])

    def committed(self, db, emu, kind, species, staged, identifier, entry):
        from ..progress_events import frame
        from .activity import gift as count_gift
        from .tracking import record_gift
        if kind == 'mew_event':
            kv.put(db, MYTHICAL, identifier)
        if staged.shiny:
            from ..shiny import record as record_shiny
            record_shiny(db, 'acquired', f'gift-event:{identifier}', species, generation=2)
        count_gift(db, identifier, species)
        record_gift(db, entry, species, frame=frame(emu.store))


GEN2 = Gen2()


def deliver(emu):
    """Stage and commit at most one Gen II gift at a safe point."""
    return deliver_with(emu, GEN2, league_rewards=getattr(config, 'LEAGUE_REWARDS', False),
                        mew_event=getattr(config, 'MEW_EVENT', False))


def clone_emulator(emu):
    from pokecore.gen2.clock import boot
    clone = boot(str(emu.rom), sound=True)
    clone.load_state(io.BytesIO(emu._state_bytes()))
    return clone
