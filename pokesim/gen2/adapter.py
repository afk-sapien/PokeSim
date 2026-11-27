"""Gold, Silver and Crystal's part of a run (runtime/adapter.py): the clock, the League count, the Mart
stock, the options byte, the recovery a headless run starts when the screen stops changing and the run's
own store."""
from __future__ import annotations

from .. import config
from ..runtime.adapter import GEN2

# A screen that has not changed for half a game minute is a loop, not a pause.
SCREEN_FRAMES = 1800


def new_history():
    """The maps, Pokédex and League progress a new game's journal starts from."""
    return {'maps': [], 'owned': [], 'badges': 0, 'league': 0}


def cartridge_game_data(rom, game, data_root):
    """The game data a run of ``game`` plays with, its encounter rows and boss parties read from the cartridge."""
    from ..planning.cost import gen2_cartridge_rows
    from .data import GameData
    from .readiness import boss_parties
    data = GameData.load(data_root, game)
    data.encounters = gen2_cartridge_rows(rom, game, data.encounters)
    data.boss_parties = boss_parties(rom, game)
    return data


def write_options(pb, data):
    """The text speed and battle animations the runtime sets after every load."""
    bank, address = data.symbols['wOptions']
    value = pb.memory[bank, address]
    if config.FAST_TEXT:
        value = value & ~7 | 1
    pb.memory[bank, address] = value & ~128 if config.BATTLE_ANIMATIONS else value | 128


class Gen2Adapter:
    generation = 2
    settings = GEN2

    def __init__(self, raw, sha1, data_root=None):
        from ..experimental.gen2 import identify
        profile = identify(raw)
        self.sha1, self.game, self.data_root = profile.sha1, profile.game, data_root
        self.screen_key, self.screen_frame = None, 0

    def boot(self, run, rom, trace=None, fair_wild_dvs=None):
        if fair_wild_dvs:
            raise ValueError('Fair wild DVs is only for Red, Blue and Yellow')
        from pokecore.gen2.clock import boot, follow_game_time

        from ..randomized import rom_stream
        from ..runtime import trace as trace_module
        from . import store_observe
        from .store_stock import StoreStock
        run.game = self.game
        run.data = self.data = cartridge_game_data(rom, self.game, self.data_root)
        # A randomized run (RANDOMIZER set) plays the patched cartridge, as the managed worker does.
        run.pb = boot(rom_stream(rom), sound=False)
        # Before the step count and the Mart stock register their hooks, so the trace knows them.
        run.tracer = trace_module.for_run(trace, 2, run.pb, run.seed)
        run.pb.set_emulation_speed(0)
        follow_game_time(run.pb)
        self._open_store(run)
        # The clerk lists the planned Champion counter item, as the runtime adds it. Without it every
        # visit ended "This mart does not sell that item" and stood down.
        run.store_stock = StoreStock(self.data, champion=lambda: store_observe.catalogue(run))
        run.store_stock.attach(run.pb)
        run.history = new_history()
        run.clock = None

    def _open_store(self, run):
        """A store of the run's own, for the walked steps, the returns and the Champion counter's offers
        the application keeps in its adventure's (store_observe.py). The policy is not attached to it, so
        losses, trades and League marks stay as a run without an adventure keeps them."""
        from .legendary import Recovery
        from .steps import StepTracker
        run.open_store()
        run.steps = StepTracker(run.store, self.data, clock=lambda: run.frame / 60)
        run.steps.attach(run.pb)
        run.legendary_recovery = Recovery()

    def new_policy(self, run, seed):
        from .policy import Policy
        return Policy(self.data, seed=seed)

    def start_fresh(self, run):
        # A new game, as the runtime starts one with no autosave: the clock follows game time from the
        # host clock's reading now.
        from pokecore.gen2.clock import follow_game_time, host_elapsed
        run.clock = follow_game_time(run.pb, host_elapsed(run.pb))

    def read(self, run):
        from pokecore.gen2.ram import read_snapshot

        from . import store_observe
        from .emulator import count_league
        snapshot = count_league(run.history, self.data, read_snapshot(run.pb.memory, self.data, run.frame), observe=True)
        if snapshot.valid and snapshot.started:
            # Before the decision, as the application observes before its next one. The run's frames
            # stand in for the PlayClock, as for the goals' stand-downs.
            store_observe.shop(run, snapshot)
            if store_observe.observe(run, snapshot, run.frame)[1]:
                snapshot = count_league(run.history, self.data, read_snapshot(run.pb.memory, self.data, run.frame))
        return snapshot

    def options(self, pb):
        write_options(pb, self.data)

    def check(self, metadata):
        from pokecore.emulator_state import validate_runtime
        if metadata.get('rom_sha1') != self.sha1 or metadata.get('generation') != 2:
            raise ValueError('This checkpoint belongs to a different cartridge')
        validate_runtime(metadata)

    def before_load(self, run, first):
        # A reload resumes at the furthest clock reading, so the one before it is kept.
        if not first:
            from pokecore.gen2.clock import clock_elapsed
            run.clock = clock_elapsed(run.pb)

    def after_load(self, run, metadata, first):
        from pokecore.gen2.clock import follow_game_time

        from ..store_observe import put_rows
        from .legendary import Recovery
        run.legendary_recovery = Recovery.loaded(metadata, run.frame)
        # The run's store starts with the rows its first save carries, as a Red, Blue or Yellow run's
        # does. An application reload keeps its adventure's rows, so a later load keeps the run's.
        if first and metadata.get('store_rows'):
            put_rows(run.store, metadata['store_rows'], 2)
            run.steps.read()
        # Gen II reads a clock earlier than its saved time as a reset, so a load resumes at the
        # furthest reading, as the runtime does.
        readings = [value for value in (metadata.get('rtc_elapsed'), run.clock) if isinstance(value, (int, float))]
        run.clock = follow_game_time(run.pb, max(readings) if readings else None)
        self.screen_frame, self.screen_key = run.frame, None
        run.history = metadata.get('gen2_history') or run.history
        self.options(run.pb)
        if not first:
            # A reload drops the menu task the save was in, as the guards do.
            run.policy.menu = None

    def manifest_fields(self, run):
        from ..store_observe import rows
        with run.store.reading() as db:
            carried = rows(db, 2)
        return {'generation': 2, 'pb': run.pb, 'history': run.history, 'legendary_recovery': run.legendary_recovery,
                'store_rows': carried}

    def before_save(self, pb):
        # The clock is rebased on the host clock, as the runtime does, so a copy opened with an unlocked
        # clock never reads it running backward.
        from pokecore.gen2.clock import rebase_to_host
        rebase_to_host(pb)

    def after_step(self, run, snapshot):
        screen = hash((snapshot.tiles, snapshot.map, snapshot.x, snapshot.y, snapshot.in_battle))
        if run.policy.idle(snapshot):
            # Standing on a wait tile is the plan, as the emulator's guards hold (policy.idle).
            self.screen_key, self.screen_frame = screen, run.frame
        elif screen != self.screen_key:
            self.screen_key, self.screen_frame = screen, run.frame
        elif run.frame - self.screen_frame >= SCREEN_FRAMES:
            # The guards back out of a screen that stopped changing, then mix in other buttons.
            run.policy.recover(1 if run.policy.recoveries % 3 == 0 else 2)
            self.screen_frame = run.frame

    def waiting(self, run, snapshot):
        """Waiting for the cartridge clock is the plan, so the stall watch does not count it."""
        return bool(run.policy.idle(snapshot) or run.policy.waiting(snapshot))
