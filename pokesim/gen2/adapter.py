"""Gold, Silver and Crystal's part of a run (runtime/adapter.py): the clock, the League count, the Mart
stock, the options byte and the recovery a headless run starts when the screen stops changing."""
from __future__ import annotations

from .. import config
from ..runtime.adapter import GEN2

# A screen that has not changed for half a game minute is a loop, not a pause.
SCREEN_FRAMES = 1800


def new_history():
    """The maps, Pokédex and League progress a new game's journal starts from."""
    return {'maps': [], 'owned': [], 'badges': 0, 'league': 0}


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

        from ..planning.cost import gen2_cartridge_rows
        from ..randomized import rom_stream
        from ..runtime import trace as trace_module
        from .data import GameData
        from .readiness import boss_parties
        from .store_stock import StoreStock
        run.game = self.game
        run.data = self.data = GameData.load(self.data_root, self.game)
        self.data.encounters = gen2_cartridge_rows(rom, self.game, self.data.encounters)
        self.data.boss_parties = boss_parties(rom, self.game)
        # A randomized run (RANDOMIZER set) plays the patched cartridge, as the managed worker does.
        run.pb = boot(rom_stream(rom), sound=False)
        # Before the Mart stock registers its hooks, so the trace knows them.
        run.tracer = trace_module.for_run(trace, 2, run.pb, run.seed)
        run.pb.set_emulation_speed(0)
        follow_game_time(run.pb)
        StoreStock(self.data, champion=lambda: self.champion_catalogue(run)).attach(run.pb)
        run.history = new_history()
        run.clock = None

    def champion_catalogue(self, run):
        """The planned Champion shop item for the clerk who opens the BUY list, as the runtime adds it.

        Without it a replay's clerk never listed the planned TM or supply, so every Champion shop
        visit ended "This mart does not sell that item" and stood down. Capped offers need the
        adventure store, so only the ones the policy already holds are offered.
        """
        from . import champion_shop
        plan = run.policy.collection.get(champion_shop.PLAN)
        return champion_shop.catalogue(self.data, plan, run.policy.shop_offers)

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

        from .emulator import count_league
        return count_league(run.history, self.data, read_snapshot(run.pb.memory, self.data, run.frame), observe=True)

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
        return {'generation': 2, 'pb': run.pb, 'history': run.history}

    def before_save(self, pb):
        # The clock is rebased on the host clock, as the runtime does, so a copy opened with an unlocked
        # clock never reads it running backward.
        from pokecore.gen2.clock import rebase_to_host
        rebase_to_host(pb)

    def after_step(self, run, snapshot):
        screen = hash((snapshot.tiles, snapshot.map, snapshot.x, snapshot.y, snapshot.in_battle))
        if screen != self.screen_key:
            self.screen_key, self.screen_frame = screen, run.frame
        elif run.frame - self.screen_frame >= SCREEN_FRAMES:
            # The guards back out of a screen that stopped changing, then mix in other buttons.
            run.policy.recover(1 if run.policy.recoveries % 3 == 0 else 2)
            self.screen_frame = run.frame

    def waiting(self, run, snapshot):
        """Waiting for the cartridge clock is the plan, so the stall watch does not count it."""
        return bool(run.policy.idle(snapshot) or run.policy.waiting(snapshot))
