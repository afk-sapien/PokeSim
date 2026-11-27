"""Red, Blue and Yellow's part of a run (runtime/adapter.py): booting, reading, options and the run memory."""
from __future__ import annotations

import hashlib

from .runtime.adapter import GEN1

BLUE_SHA1 = 'd7037c83e1ae5b39bde3c30787637ba1d4c48ce2'


def fair_key(seed):
    """A fair wild DV key for a run with no adventure, the same for every run with this seed."""
    return hashlib.sha256(f'fair-wild-dvs {seed}'.encode()).digest()


class Gen1Adapter:
    generation = 1
    settings = GEN1

    def __init__(self, raw, sha1):
        from .game_data import VARIANT_ENV
        from .policies.progression import YELLOW
        from .yellow import YELLOW_SHA1
        self.sha1, self.yellow = sha1, sha1 == YELLOW_SHA1
        # The policy reads its game data once at import, from POKESIM_GEN1_VARIANT. Yellow under
        # Red data reads menus at Red's addresses, so every battle shortcut times out.
        if self.yellow != YELLOW:
            variant = 'yellow' if self.yellow else 'red'
            raise ValueError(f'This cartridge needs {VARIANT_ENV}={variant} before pokesim is imported')
        self.version = 'yellow' if self.yellow else 'blue' if sha1 == BLUE_SHA1 else 'red'
        # The snapshot the last read decoded, since the start or the last load.
        self.last = None

    def boot(self, run, rom, trace=None, fair_wild_dvs=None):
        from pokecore.emulator import Emulator as CoreEmulator

        from .randomized import rom_stream
        from .runtime import trace as runtime_trace
        from .investment import use_cartridge
        from .yellow import open_emulator
        self.rom = rom
        # The PC rates copies with this cartridge's TMs, which ROM_PATH may not name.
        use_cartridge(rom)
        run.game = self.version
        # A randomized run (RANDOMIZER set) plays the patched cartridge, as the managed worker does.
        run.pb = open_emulator(rom_stream(rom), default=CoreEmulator, yellow=self.yellow, window='null',
                               sound_emulated=False, snapshot=True)
        # Before fair DVs register their hook, so the trace knows it.
        run.tracer = runtime_trace.for_run(trace, 1, run.pb, run.seed)
        run.pb.set_emulation_speed(0)
        # Fair wild DVs, as an adventure with the setting on plays them. True keys the rerolls from
        # the seed, and bytes are a live adventure's own key.
        if fair_wild_dvs:
            from . import fair_dvs
            key = fair_wild_dvs if isinstance(fair_wild_dvs, bytes) else fair_key(run.seed)
            fair_dvs.attach(run.pb, self.sha1, key)
        from .events import RunMemory
        run.memory = RunMemory()
        self._open_store(run)

    def _open_store(self, run):
        """A store of the run's own, for the walked steps, the returns, the Champion counter's offers
        and the Pokédex goals the application keeps in its adventure's (store_observe.py). The policy
        is not attached to it, so losses, trades and League marks stay as a run without an adventure
        keeps them."""
        from .legendary import LegendaryRecovery
        from .legendary_returns import StepTracker
        from .milestones import MilestoneTracker
        run.open_store()
        # After the trace, which must know every hook.
        run.step_tracker = StepTracker(run.store, self.sha1, clock=lambda: run.frame / 60)
        run.step_tracker.attach(run.pb)
        run.milestones = MilestoneTracker(run.store)
        run.legendary_recovery = LegendaryRecovery()

    def new_policy(self, run, seed):
        from .planning.cost import wild_odds
        from .policies.strategic import StrategicPolicy
        from .tm_shop import cartridge_data
        policy = StrategicPolicy(seed)
        policy.collection.version = self.version
        policy.collection.wild = wild_odds(self.rom, self.version)
        # As the application's emulator attaches them. Without them the policy teaches no TM and the
        # Champion counter sells nothing.
        policy.tm_moves, policy.tm_compatible = cartridge_data(self.rom.read_bytes())
        return policy

    def start_fresh(self, run):
        pass

    def read(self, run):
        from . import store_observe
        from .ram import end_damaged_nicknames, read_snapshot, start_wild_battle
        snap = read_snapshot(run.pb.memory, run.frame)
        # As the application's observe step does (Emulator._observe_snapshot).
        if end_damaged_nicknames(run.pb.memory, snap.party, self.last and self.last.party):
            snap = read_snapshot(run.pb.memory, run.frame)
        start_wild_battle(run.pb.memory, snap, self.last)
        # Before the decision, as the application observes before its next one. The run's frames
        # stand in for the PlayClock, as for the goals' stand-downs.
        _, snap, _ = store_observe.observe(run, snap, run.frame)
        self.last = snap
        return snap

    def options(self, pb):
        from .runtime.game_loop import write_gen1_options
        write_gen1_options(pb)

    def check(self, metadata):
        from pokecore.emulator_state import validate_runtime
        validate_runtime(metadata)
        if metadata['rom_sha1'] != self.sha1:
            raise ValueError('ROM or emulator version does not match the checkpoint')

    def before_load(self, run, first):
        pass

    def after_load(self, run, metadata, first):
        from . import store_observe
        from .events import RunMemory
        from .legendary import LegendaryRecovery
        run.memory = RunMemory.from_dict(metadata['run_memory'])
        run.legendary_recovery = LegendaryRecovery.loaded(metadata, run.frame)
        # The run's store starts with the rows its first save carries. An application reload keeps
        # its adventure's rows, so a later load keeps the run's.
        if first and metadata.get('store_rows'):
            store_observe.put_rows(run.store, metadata['store_rows'])
            run.step_tracker.read()
        # The application's load forgets its last snapshot too.
        self.last = None

    def manifest_fields(self, run):
        from . import store_observe
        with run.store.reading() as db:
            carried = store_observe.rows(db)
        return {'policy_name': 'strategic', 'run_memory': run.memory, 'legendary_recovery': run.legendary_recovery,
                'store_rows': carried}

    def before_save(self, pb):
        pass

    def after_step(self, run, snapshot):
        """The Champion counter sale the application makes once a trip stands at the counter
        (runtime/tm_purchase.py). The run's own store spends a supply offer, and keeps no ledger,
        journal or recoverable save. The policy takes back the state it had, as after the sale's load."""
        import json

        from . import champion_shop
        from .runtime.tm_purchase import at_counter, credit, sale
        if not at_counter(run.policy, run.pb.memory):
            return
        run.step_tracker.flush(force=True)
        found = sale(run.policy, run.pb.memory, run.frame, champion_shop.ready(run.store))
        if found is None:
            return
        credit(run.pb.memory, *found)
        item = found[1]
        if run.policy.tm_plan.get('supply') and item in champion_shop.OFFERS:
            with run.store.transaction() as db:
                champion_shop.consume(db, item)
        # The application loads the sale from a save whose manifest it wrote as JSON a moment before.
        run.resume(json.loads(json.dumps(run.manifest())))
        run.policy.on_restore()

    def waiting(self, run, snapshot):
        return False
