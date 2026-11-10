# Gold, Silver and Crystal

`pokecore.gen2` decodes Gen II memory read-only. It ships the per-version
memory map (`gen2.memory_map.symbols(version)`, from the pinned pret symbol
files, with Crystal's moved WRAM and the Crystal-only symbols in `CRYSTAL_ONLY`)
and the English character maps (`gen2.charmap.charmap(version)`).
`gen2.version_of(rom_bytes)` names the version through `cartridges.identify`. It ships no
species, move, item or map tables.

Table-free readers need only a version name and any memory that supports banked
reads `memory[bank, start:stop]`:

```python
from pokecore.gen2 import state

party = state.read_party_structs(memory, "crystal")  # DVs, shiny, held item, friendship, Pokerus, caught data
boxes = state.read_box_structs(memory, "crystal", box=0)  # one PC box, eggs included
counts, active = state.read_box_counts(memory, "crystal")
items = state.read_items(memory, "crystal")  # items, balls, key, pc and the TM/HM quantities
player = state.read_player(memory, "crystal")  # name, ID, map, position, Johto and Kanto badges, money
dex = state.read_pokedex(memory, "crystal")  # seen, caught and Unown forms
clock = state.read_clock(memory, "crystal")  # day, weekday, time of day, RTC start and DST
daycare = state.read_daycare(memory, "crystal")  # parents, egg flags, steps to egg and the egg
roamers = state.read_roamers(memory, "crystal")
```

`gen2.read_snapshot(memory, data, frame=0, *, cache=True)` returns the full
`Snapshot` PokeSim observes, with `Mon` objects, pockets, objects and screen
text. `data` is the consumer's game tables: `gen2.GameTables(raw)` builds them
from a JSON mapping, and any object with the same attributes works. Symbols and
the charmap default to Core's own. With `cache=True`, decoded regions (party,
each box, Pokedex, Day Care, screen) are reused while their bytes and `data`
are unchanged. `gen2.clear_region_cache()` drops them.

Also in `pokecore.gen2`:

- `battle_power(mon, data)` and `hidden_power(data, dvs)` rate a decoded Pokemon from the game tables.
- `offspring`, `retrieval_cost`, `branch_parents`, `ancestors` and `level_credit` apply the Day Care and evolution-line rules.
  `families`, `single_source`, `lines`, `breeding_stock`, `egg_lines`, `free_slots` and `descendants_wanted`
  find the families only the Day Care can copy and whether another hatchling is wanted.
- `live_status(game, collection, *, data=None)` builds the shared adventure status payload.
- `ScreenText`, `has_word`, `mask_hud`, `mask_roster` and `is_roster` match whole words in screen text.
  `ScreenText` and `has_word` come from the generation-neutral `pokecore.textmatch`, which Gen 1
  screen readers can import too.
- `npc_trades(game)` and `NPC_TRADES` list the in-game trades (an `NpcTrade` each, with its
  `wTradeFlags` bit as `index`). `state.npc_trade_flags`, `npc_trade_done` and `npc_trades_done`
  read which happened, and `npc_trade_qualifies(mon, trade)` checks species, Egg and, for a
  female-only trade, the `gender` the caller supplies.
- `prizes(game)` and `PRIZES` list the Game Corner prize Pokemon as (species, coins, city).
  `FIELD_MOVES` holds the seven HM move IDs.
- `state.contest_score(memory, version, prefix='wContestMon')` is the Bug-Catching Contest judge's
  score for the caught Pokemon. `prefix='wEnemyMon'` scores the wild one in battle.
- `gen2.puzzles` solves the Ruins of Alph picture boards. `puzzle_button(board, cursor, held)`
  returns the next button for the 36 `wPuzzlePieces` bytes, and `puzzles.control(memory, version,
  map_constant=None)` reads the open board and returns a button, `'wait'` while the board is
  changing, or None when no board is open. Pieces are never dropped on an occupied cell.
- `decode_mon`, `individual`, `calculated_stats`, `experience_at`, `experience_progress`, `dex_flags` and `decode_text` are the building blocks.

Output is identical, field for field and in `repr`, to the PokeSim `pokesim.gen2`
modules these were moved from.

`Mon` also carries the Pokerus byte and the Crystal caught data word. `to_dict()`
reports them as `pokerus` and, on Crystal, `caught` (named through
`caught_details` and `landmark_name`), adds `power` and `accuracy` to each move
and `egg_cycles` to an egg. `Mon.to_dict(egg_view=True)` and
`Snapshot.to_dict(egg_view=True)` show an unhatched egg the way the game does,
with no Pokedex number, name or types. The default keeps the species. A
`Snapshot` has `enemy_shiny` for a wild opponent, read from the Transform backup
DVs when a wild Ditto has transformed. It is None when the symbol table has no
enemy DVs.

## Portraits

`gen2.sprites` decodes the front portraits from the cartridge with no game tables. The ROM
tables come from `sprites.LABELS` and every read checks the base data's Pokedex number.

- `picture(rom, version, dex, *, unown=0)` returns rows of colour indices 0 (lightest) to 3
  (darkest), then the width and height in tiles. `unown` picks Unown's letter, 0 to 25.
- `portrait(rom, version, dex, *, shiny=False, unown=0)` frames the picture on a 56 by 56
  canvas, centred and on the bottom edge as the game shows it, and returns the rows with
  the species' palette. The margin is index 0.
- `palette(rom, version, dex, *, shiny=False)` is four RGBA colours. Index 0 is transparent.
- `front_pointer`, `pic_bank`, `dimensions`, `decompress` and `offset` are the steps.
- `pokecore.sprites.png(rows, palette)` writes a PNG with the standard library.

## Save-menu exports

`gen2.save` and `gen1_save` produce a battery save the way a console would: a private clone
of the run opens the Start menu, chooses SAVE and confirms, then a fresh emulator boots the
file, chooses Continue and checks that the party, boxes, Pokédex, badges, money, bag, names
and position match. A mismatch raises `ValueError` and nothing is returned. The live run is
never changed and nothing is written beside the ROM.

- `gen2.save.capture(emulator, data)` and `gen1_save.capture(emulator)` return a raw state,
  refused unless the trainer is walking with a party outside battle and dialogue.
- `gen2.save.export_with_clock(rom, state, data)` returns the 32 KiB save and its ten-byte
  `.rtc` file. `export` returns the save alone. `clock_archive(save, rtc, name)` zips both.
- `gen2.save.verify(rom, save, data, expected, *, rtc=None)` and `continue_save(rom, save,
  data, *, rtc=None)` boot a save. `continue_save` returns the running emulator once the
  trainer walks and leaves location checks to the caller.
- `gen2.save.checkpoint_clock(rom, state)` is the clock file a raw state reads as.
- `gen1_save.export(rom, state)` and `verify(rom, save, symbols, expected)` accept the
  verified English Red, Blue and Yellow builds (`symbols_for(rom)`). Yellow runs on
  `YellowEmulator`, so `progress(memory, symbols)` reads Red addresses on all three.

## Map collision and ice

`gen2.maps` says where the game lets the player walk. Route planning stays with the
consumer. Grids are one collision byte per tile, row by row, and each `data.maps` entry
needs `constant`, `width`, `height`, `collision`, `block_collision` and `objects`.

- `collision(memory, data, snapshot)` decodes the loaded map from `wOverworldMapBlocks`, so it
  shows the blocks the game has swapped in (the bedroom's bed and PC, opened doors, pushed
  boulders), then applies `travel_collision`. Each call decodes again and returns a new list.
  `decode_blocks(blocks, width, height, table)` is the same decode on bytes already read.
- `passable(data, tile, surf=False)` reads the low nibble of `data.permissions`: 0 walks, 1 surfs.
- `side_blocked(tile, direction)` (also `blocked_side`) is a one-sided wall from `WALLS`.
- `move(grid, width, height, point, button, enter, solid=(), stop=())` is where one step ends,
  sliding across `ICE` tiles, or None when the first tile cannot be entered. `slide` continues
  a slide from the tile just entered. `enter(tile)` says whether a tile can be walked on,
  `solid` holds tiles taken by objects and a tile in `stop` (a warp, a goal) ends the slide.
- `travel_collision(data, snapshot, map_id, grid)` adds the walls story flags and items clear:
  the Route 36 Sudowoodo, the Vermilion Snorlax, the Route 19 rocks, the Victory Road gate
  guards and the bike-only Route 16 and 17 gates.
- `event_changes(data, snapshot, live=None)` returns `{map id: grid}` for the maps that event
  flags change while they are not loaded (`CHANGES`, `LEAGUE`, the switch room `DOORS`) and the
  `TRAVEL_MAPS`. `live` gives the last grid seen on a map, used as the base for the edits.
- `ice_solids(data, snapshot, map_id)` is the tiles objects hold, with boulders where the game
  reports them while their map is loaded and hidden objects left out.
- `flyer(snapshot)` is the party slot that can use Fly, or None. `OUTSIDE` is the map
  environments Fly works from.

## ROM hooks

`gen2.hooks` returns the (bank, address) to pass to `hook_register` for game code a consumer
wants to watch. Each finder takes `memory` (banked reads) and `data`, checks the instructions
at that address and raises ValueError when they differ, so a hook is never placed inside
other code. What the hook does stays with the consumer.

- `capture_hooks(memory, data)`: the two places a caught Pokemon joins the party or a box
  (fixed addresses and signatures in `HOOKS`).
- `encounter_hook`: where every wild battle checks for a shiny.
- `contest_hook`: where a Bug-Catching Contest catch is kept. Contest catches skip the capture hooks.
- `hatch_hook`: HatchEggs, which every Egg reaches.
- `step_hook`: CountStep, once per completed step (link sessions too, so check `wLinkMode`).
- `mart_hooks`: a dict with `opened` (BuyMenu), `priced` (unit price in `de`), `subtotal` and
  `bought`. It is `{}` without BuyMenu and SelectQuantityToBuy, and has only the first two
  without BuySell_DisplaySubtotal, BuyMenuLoop, hProduct and hMoneyTemp.

ROM labels come from `data.symbols` first, then `hooks.LABELS`, which holds the ones these
finders need from the pinned pret symbol files. A minimal `GameTables({"game": "crystal"})`
is enough. `bcd(value)` packs 0 to 999999 as the game stores money and prices.

## Cable Club

`gen2.cable` runs a trade between two emulators with the Gen 1 transport (see
[emulator.md](emulator.md#gen-1-virtual-cable)) over the Gen 2 link routines.

- `CableSide(emulator, symbols, data, max_queue=4)` is one cartridge. `symbols` are
  `gen2_link_metadata.build(sha1)["symbols"]`, so check `verify_signatures` first.
  `get` reads a link symbol, then any `data.symbols` label.
- `TimeCapsuleSide(emulator, symbols, data, rom, max_queue=4)` also counts
  Gen2ToGen1LinkComms. It raises `CableError` unless `timecapsule.communication_ok(rom,
  data.game)`.
- `CableDriver(sides, plan, progress=None, cancelled=None, *, walk=None)` presses the
  buttons of a Gold, Silver or Crystal trade until both sides leave. `MixedDriver(gen1,
  gen2, plan, ...)` trades a Red-layout Gen 1 `CableEndpoint` with a `TimeCapsuleSide`.
  `plan` needs `max_steps`, `timeout_seconds` and `speed` (0 runs unpaced). Each side
  offers `party_slot` and reports progress under `label`.
- `data.map_ids` must name `POKECENTER_2F` and `data.maps` must give each map's
  `constant`. A side outside the trade rooms heads for the attendant on Pokémon Center 2F
  through `walk(side, snapshot, target)`, which returns the next button toward `target`
  (map, x, y), or None to wait. Without `walk` the driver raises `CableError` as soon as a
  trainer has to move. Route finding stays with the caller.
- The driver raises `CableError` with `ABNORMAL` when the game rejects the incoming
  Pokémon as abnormal, because the game then cancels the trade by itself.

## Setup writes

`gen2.resets` mirrors the Gen 1 `resets` module for banked memory. These are trusted setup
writes for a paused emulator, not agent commands. Which flags to change, and when, stays with
the consumer.

```python
from pokecore.gen2 import resets

resets.write_flag(memory, data, "EVENT_FOUGHT_LUGIA", False)  # True when the bit changed
resets.write_byte(memory, data, "wTinTower1FSceneID", 0)
changed = resets.reset_event(memory, data, [("EVENT_FOUGHT_LUGIA", False), ("EVENT_WHIRL_ISLAND_LUGIA_CHAMBER_LUGIA", False)])
resets.box_gift(memory, data, 152, seed, box, position, nicknames=("LEAFY",), ot="POKESIM")
resets.set_gs_ball(memory, data)  # Crystal only
```

`reset_event` checks every name and refuses conflicting values before it writes, reads each
byte back and restores the bytes it wrote if one does not persist. It returns the names whose
value changed. `box_gift` writes a level 5 Pokemon at `position`, which must be the box's
current count, with the moves it knows by level 5, full PP and 70 happiness. `seed` fixes its
trainer ID and DVs. The nickname is drawn from `nicknames` after the DVs, or is the species
name when `nicknames` is None. It also sets the caught and seen Pokedex bits. It reads
`learnset`, `growth` and `name` from `data.species` and `pp` from `data.moves`.
