"""Read-only Gold, Silver and Crystal decoding.

Core ships the per-version memory maps and character maps. Species, move, item and map
tables stay with the consumer and are passed in as ``data`` (a :class:`GameTables` or any
object of the same shape). The submodules ``memory_map`` and ``charmap`` hold the
per-version tables (``memory_map.symbols(version)`` and ``charmap.charmap(version)``). The table-free readers in :mod:`pokecore.gen2.state` need
only a version name. The submodules ``clock`` and ``save`` drive the cartridge clock and the
Save menu on a Core emulator and need the emulator extra when called. :mod:`pokecore.gen2.maps`
decodes live map collision and ice slides. :mod:`pokecore.gen2.hooks` finds verified ROM code
addresses for emulator hooks and :mod:`pokecore.gen2.resets` holds trusted setup writes.
:mod:`pokecore.gen2.cable` drives Cable Club and Time Capsule trades on Core emulators.
:mod:`pokecore.gen2.puzzles` reads and solves the Ruins of Alph picture boards.
:mod:`pokecore.gen2.sprites` decodes front portraits from the cartridge.
"""
from . import cable, clock, hooks, maps, puzzles, resets, save, sprites
from .battle_power import battle_power, hidden_power
from .breeding import (DITTO, TYROGUE, ancestors, branch_parents, breeding_stock, descendants_wanted, egg_lines,
                       families, free_slots, level_credit, lines, offspring, retrieval_cost, single_source)
from .clock import (clock_elapsed, clock_lock_state, export_clock, follow_game_time, host_elapsed, lock_clock,
                    rebase_to_host, stop_with_clock)
from .hooks import bcd, capture_hooks, contest_hook, encounter_hook, hatch_hook, mart_hooks, step_hook
from .maps import (CHANGES, DIRS, DOORS, ICE, OPPOSITE, OUTSIDE, WALLS, collision, flyer, has_ice, ice_solids, move,
                   passable, side_blocked, slide, travel_collision)
from .memory_map import CRYSTAL_ONLY, VERSIONS, symbols, version_of
from .ram import (BADGES, STAT_NAMES, TIMES_OF_DAY, Mon, Snapshot, calculated_stats, caught_details, clear_region_cache,
                  decode_mon, dex_flags, experience_at, experience_progress, individual, landmark_name, read_snapshot,
                  tile_rows)
from .puzzles import DESTINATIONS, PUZZLES, puzzle_button
from .resets import box_gift, reset_event, set_gs_ball, write_byte, write_flag
from .save import clock_archive, export_with_clock
from .screens import ScreenText, has_word, is_roster, mask_hud, mask_roster
from .state import (CONTEST_STATS, caught_data, contest_score, decode_struct, memory_reader, npc_trade_done,
                    npc_trade_flags, npc_trade_qualifies, npc_trades_done, pokerus, read_box_counts,
                    read_box_structs, read_clock, read_daycare, read_items, read_party_structs, read_player,
                    read_pokedex, read_roamers)
from .status import DEFAULT_VERSION, live_status
from .tables import FIELD_MOVES, NPC_TRADES, PRIZES, GameTables, NpcTrade, decode_text, npc_trades, pretty, prizes

__all__ = [
    'BADGES', 'CHANGES', 'CONTEST_STATS', 'CRYSTAL_ONLY', 'DEFAULT_VERSION', 'DESTINATIONS', 'DIRS', 'DITTO', 'DOORS',
    'FIELD_MOVES', 'GameTables', 'ICE', 'Mon', 'NPC_TRADES', 'NpcTrade', 'OPPOSITE', 'OUTSIDE', 'PRIZES', 'PUZZLES',
    'STAT_NAMES', 'ScreenText', 'Snapshot', 'TIMES_OF_DAY', 'TYROGUE', 'VERSIONS', 'WALLS', 'ancestors', 'battle_power',
    'bcd', 'box_gift', 'branch_parents', 'breeding_stock', 'cable', 'calculated_stats', 'capture_hooks', 'caught_data',
    'caught_details', 'clear_region_cache', 'clock', 'clock_archive', 'clock_elapsed', 'clock_lock_state', 'collision',
    'contest_hook', 'contest_score', 'decode_mon', 'decode_struct', 'decode_text', 'descendants_wanted', 'dex_flags',
    'egg_lines', 'encounter_hook', 'experience_at', 'experience_progress', 'export_clock', 'export_with_clock',
    'families', 'flyer', 'follow_game_time', 'free_slots', 'has_ice', 'has_word', 'hatch_hook', 'hidden_power', 'hooks',
    'host_elapsed', 'ice_solids', 'individual', 'is_roster', 'landmark_name', 'level_credit', 'lines', 'live_status',
    'lock_clock', 'maps', 'mart_hooks', 'mask_hud', 'mask_roster', 'memory_reader', 'move', 'npc_trade_done',
    'npc_trade_flags', 'npc_trade_qualifies', 'npc_trades', 'npc_trades_done', 'offspring', 'passable', 'pokerus',
    'pretty', 'prizes', 'puzzle_button', 'puzzles', 'read_box_counts', 'read_box_structs', 'read_clock', 'read_daycare',
    'read_items', 'read_party_structs', 'read_player', 'read_pokedex', 'read_roamers', 'read_snapshot',
    'rebase_to_host', 'reset_event', 'resets', 'retrieval_cost', 'save', 'set_gs_ball', 'side_blocked', 'single_source',
    'slide', 'sprites', 'step_hook', 'stop_with_clock', 'symbols', 'tile_rows', 'travel_collision', 'version_of',
    'write_byte', 'write_flag',
]
