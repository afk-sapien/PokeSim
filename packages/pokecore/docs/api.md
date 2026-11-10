# API compatibility

The Python import and the distribution are `pokecore`. The repository stays
`pokesim-core`. `__version__` identifies the package release and `API_VERSION`
identifies the major data contract. It is 1 and changes only for an incompatible change to documented field shapes.

## ROM module

`inspect_rom(path)` returns frozen `RomInfo` fields `sha1`, `sha256`, `game`,
`name`, and `verified`. It describes unknown ROMs without accepting them.
`require_rom(path, allowed_games=...)` rejects unknown or excluded games.
SHA-1 values identify known cartridges for compatibility. SHA-256 identifies
artifacts in reproducibility manifests. No ROM file is modified.
`inspect_rom` and `KNOWN_ROM_SHA1` still describe only Red and Blue.
`require_rom` accepts any registered version named in `allowed_games`.

## Cartridge registry

`cartridges` lists the six clean English cartridges PokeSim plays. Its names and
error wording match PokeSim's `pokesim/cartridges.py`.

- `CARTRIDGES` holds frozen `Cartridge` records. The first five fields are
  `version`, `generation`, `sha1`, `title` and `starters`. Header facts follow:
  `header_title`, `cgb`, `sgb`, `rtc`, `cartridge_type`, `rom_size`, `ram_size`,
  `revision` and `layout`.
- `identify(raw)`, `identify_sha1(digest)` and `identify_file(path)` return a
  `Cartridge` or None. `by_version(version)` and `generation(version)` look one up.
- `unpack(raw, app='PokeSim')` accepts a cartridge or a ZIP holding exactly one.
  `unsupported_message(app)` is the refusal text.
- `read_header(raw)` decodes the header and checks both checksums.
  `header_matches`, `resembles` and `refusal_reason` explain why a file was refused.
  `REFUSED` names Crystal Rev 0 and the Australian Crystal.
- `SLOTS`, `SLOT_TITLES`, `SLOT_GENERATIONS` and `validate_starter` describe the shelf.

## ROM game data

`romdata` reads game tables from the caller's own cartridge at load time. Core
ships only the per-version addresses in `romdata.LAYOUTS`, never the tables.

- `load(rom, version=None)` returns `GameData`. Without `version` the ROM must be
  a verified clean cartridge. With `version` it reads a modified ROM of that
  version, which must keep the same layout.
- `GameData` has `version`, `generation`, `species`, `evolutions`, `learnsets`,
  `tm_moves`, `encounters`, `trainers`, `starters` and `overrides`.
  `as_dict()` copies the tables. `canonical()` returns sorted, compact JSON bytes
  for exact comparison. `starter_sites()` lists every ROM offset that holds each
  starter's species.
- Species IDs are what the game stores in memory: the Gen I internal index (each
  record also carries `dex`) or the Gen II dex number. `tmhm` numbers are 1-based
  positions in `tm_moves`, with HMs (and Crystal's tutor moves) after the TMs.
- Encounter keys are `grass:<map>` and `water:<map>` on Gen I, and
  `<region>_<grass|water>:<group * 256 + number>` on Gen II, where region is
  `johto`, `kanto` or `swarm`. Gen II grass tables hold `rates` and `slots` for
  `morn`, `day` and `nite`. Every slot is `[level, species]`.
- Trainer keys are `<class>:<index>`, both 1-based. Gen II trainers also hold
  `name` and `type`, and their party members hold `item` and `moves` when the
  type says so. A class with no parties has no keys.
- `with_overrides(overrides)` returns the effective `GameData` and leaves the
  original unchanged. Keys are `species_map`, `species`, `evolutions`,
  `learnsets`, `tm_moves`, `encounters`, `trainers` and `starters`.
  `species_map` rewrites starters, wild slots and trainer parties. An encounter
  override is a field dict or another table key of the same kind to swap in.
  Explicit entries win over `species_map`. Unknown keys, unknown species and
  wrong lengths raise `ValueError`. With no overrides, `canonical()` is
  byte-identical to the ROM reading.
- `effective_data(rom, overrides=None, version=None)` is `load` followed by
  `with_overrides`, for planners.
- `patch_rom(rom, overrides=None, version=None)` returns a patched copy of the ROM
  bytes. It writes starters at every starter site, wild encounter tables, trainer
  parties and the TM and HM move list, each in place. Changes that would resize a
  table (a different party size, a new Gen I fixed party level, a trainer name)
  raise `ValueError`, as do `species`, `evolutions` and `learnsets` overrides. Maps
  that share one ROM table must end up with the same table. The global checksum is
  fixed up after a change. With no overrides the ROM comes back byte-identical.
  `load(patched, version=...)` reads back the effective data.

## Randomizer

`randomizer` turns a seed into a `romdata` override map. It is pure and
deterministic: the same `GameData`, seed and options always give the same map.

- `Options(wild=True, starters=True, trainers=False)` chooses what to randomize.
  Trainer parties are opt-in. At least one must be set.
- `randomize(rom_data, seed, options=None, gates=None)` draws one shuffle of every
  species per seed and applies it to the chosen parts. Levels never change, so
  `romdata.patch_rom` can write the result. The seed is a whole number from 0 to
  2**64 - 1. Bad seeds raise `ValueError`.
- A shuffled Gen II party member that has explicit moves gets the new species'
  default moveset from the cartridge's learnset, as `default_moves(learnset,
  level)` fills it: the last four distinct moves learned at or below the level,
  padded with 0. Gen I parties carry no moves and keep the cartridge's defaults.
- When wild encounters are randomized, a draw is kept only if every HM the story
  requires has a wild learner catchable before the game asks for it. Otherwise it
  draws again, up to `MAX_DRAWS`, then raises `RuntimeError`. Only wild slots
  count. Starters, gifts, trades and fishing never do.
- `HM_GATES` and `hm_gates(version)` list each gate as `(hm, encounter keys)`,
  with HM numbers counted after the 50 TMs (HM01 is 51). Gen I gates Cut, Surf
  and Strength. Gen II gates Cut, Surf, Strength and Waterfall. Fly, Flash and
  Whirlpool are not required to finish the story and are not checked. A key the
  cartridge has no table for is skipped. `gates=` replaces them for one call.
- `missing_hm_learners(data, gates=None)` returns the HMs with no catchable
  learner in `data`.
- `encode_share_code(version, seed, options)` returns `PSR1-<GAME>-<OPTS>-<seed>`,
  for example `PSR1-CRYSTAL-WST-42`. OPTS are `W`, `S` and `T` in that order.
  `decode_share_code(code)` returns `(version, seed, options)` and raises
  `ValueError` for anything but a canonical code, ignoring case and surrounding
  space.

## Yellow

Yellow runs the Red engine with WRAM from 0xCF1B to 0xDEE1 one byte lower and a
few HRAM bytes moved. `yellow.red_layout(memory, version)` returns a Red-layout
view of raw Yellow memory, so every `gen1` and `gen1_ui` address works.

- `gen1.read_party`, `read_bag`, `read_progress`, `read_starters`, `read_trainers`,
  `gen1_ui.read_battler` and `read_storage` take `version=`. Leaving it out keeps
  the Red and Blue behaviour. A view that is already Red-layout needs no version.
- `read_starters` returns the player and rival starter bytes. In Yellow the rival
  byte is 1, 2 or 3 and `rival_evolution` names Jolteon, Flareon or Vaporeon.
- `yellow.read_pikachu(memory)` returns happiness, mood, the follow, surf and
  starter flags, and `starter_slot`. `starter_pikachu_slot` follows the
  cartridge rule: species, trainer ID and the first five name bytes must match.
- `yellow.YellowEmulator` is a Core `Emulator` whose `memory` uses Red addresses.
  `raw_memory` keeps Yellow addresses. `open_emulator(rom)` picks it for Yellow.
- `gen1_link_metadata.BUILDS` gains the Yellow build. Its RAM symbols are the Red
  ones, so read them through a Red-layout view.

## Battle power and DVs

`gen1_battle_power` reproduces PokeSim's estimates exactly, given the caller's
game tables, because Core ships none. `BattlePower(species, moves, matchups)`
provides `damage`, `moveset_score`, `battler`, `battle_power`, `stored_strength`
and `best_replacement`. The module also has `calculated_stat`, `calculated_stats`,
`stored_strength(mon, species)`, `stat_exp_bonus` and `dv_rating`.
`dvs` adds `is_perfect`, `is_shiny` and `shiny_bytes`.

## Trades and the Time Capsule

All trade helpers are pure and read-only.

- `gen1_link_metadata` covers Red, Blue and Yellow. `gen2_link_metadata` covers
  Gold, Silver and Crystal. Both have `BUILDS`, `build(sha1)` and
  `verify_signatures(rom, sha1)`.
- `timecapsule` has `compatible`, `compatible_struct`, `MAIL_ITEMS`,
  `CATCH_RATE_ITEMS`, `held_item_from_catch_rate`, `to_gen1`, `to_gen2`, `convert`,
  `communication_ok`, `ADAPTER_ID` and `COMMUNICATION`.
- `trade` has `gen1_party`, `boxed_inventory`, `walking_party_preserved`,
  `gen1_individual_key`, `gen2_individual_key`, `verify_gen1_received`,
  `gen2_evolved_species`, `gen2_untraded_party` and `verify_gen2_received`.
  Failed checks raise `gen1_cable.CableError` with PokeSim's messages.
- `gen1_cable.CableDriver` and `centers` drive a Red, Blue or Yellow trade (see
  [emulator.md](emulator.md#gen-1-virtual-cable)). `gen2.cable` has `CableSide`,
  `TimeCapsuleSide`, `CableDriver`, `MixedDriver` and `ABNORMAL` for Gold, Silver and
  Crystal (see [gen2.md](gen2.md#cable-club)).
- `identity.family_key(trainer, dvs, dex, families=None)` is a trade key: the
  `pokemon_identity` signature, a hyphen and the evolution family root, the lowest Pokedex
  number in the family (`FAMILY_ROOTS`, built from `FAMILIES`). It survives evolution in
  both generations and the Time Capsule and tells apart two species that share a trainer
  and DVs. `dex_of(mon)` reads `dex`, or a Red, Blue or Yellow species index through
  `GEN1_DEX` (`GEN1_INDEX` is the inverse). `same(current, wanted)` and
  `find(rows, wanted, field='trade_key')` also accept a bare signature with no family, and
  `find` returns a row only when exactly one answers.

## Sprites and formulas

- `sprites.portraits(rom)` decodes all 151 Red, Blue and Yellow front portraits, as Pokedex
  number to rows of colour indices 0 (lightest) to 3 (darkest). `front_sprite(rom, dex)`
  decodes one and returns the rows, width and height in tiles. Yellow is detected from the
  ROM. Gold, Silver and Crystal portraits are in [gen2.md](gen2.md).
- `sprites.png(rows, palette=SHADES)` writes an RGBA PNG with the standard library.
  `SHADES` makes index 0 transparent.
- `formulas.experience_at(level, growth)` and `experience_progress(total, level, growth)`
  are the experience curves of both generations, by the growth name without `GROWTH_`.

## Generation I module

`gen1` supports the verified USA/Europe English Red and Blue layouts, and Yellow through `version='yellow'`. It accepts
any memory object supporting integer and slice reads. It does not depend on
PyBoy, a live process, application globals, a filesystem data directory, or labels.

- `decode_text(data)` handles the original cartridge alphabet, termination,
  gender symbols, and unknown glyphs using PokeSim's established behavior.
- `bcd(data)` decodes packed BCD bytes using the original permissive behavior.
- `flag_bits(data)` returns one-based set-bit indices for Pokédex arrays.
- `event_set(flags, index)` uses zero-based event indices and validates bounds.
- `individual_data(struct)` returns moves, trainer ID, experience, DVs, and stat experience.
- `read_party(memory, move_data=None)` returns dicts matching the numerical fields
  of PokeSim's PartyMon. Optional integer-keyed move data provides base PP values.
- `read_bag(memory)` returns a tuple of item ID and quantity pairs.
- `read_progress(memory)` returns the following raw facts.

| Field | Meaning |
| --- | --- |
| `valid` | Lightweight party species/level sanity check |
| `badges` | Badge bitmask |
| `gym_flags` | Gym victory flags in badge order |
| `elite` | Named Elite Four trainer victory flags |
| `champion` | Champion rival victory flag |
| `hall_of_fame` | Cartridge Hall of Fame registration counter |
| `map_id` | Current map identifier |
| `story` | Starter, Pokédex, Silph Co., and Surf event flags |

The `valid` field is not comprehensive validation. RAM can be partly written
during transitions, and Elite Four flags can reset after a League journey.
Applications own confirmation across frames, historical tracking, unique awards,
and completion criteria. The core makes no claim that a trainer battle ending
proves victory. Core progress facts do not include hidden opponent statistics.

Party dict keys are `species`, `hp`, `max_hp`, `level`, `nick`, `status`, `types`,
`moves`, `pp`, `attack`, `defense`, `speed`, `special`, `experience`, `max_pp`,
`dvs`, `stat_exp`, and `trainer_id`. Pending counted slots remain present.
Box data uses `individual_data` but box enumeration remains application-owned.

`gen1` also names the overworld, menu and battle bytes consumers read, all Red
addresses from pret/pokered: `W_FACING` (a key of `FACINGS`), `W_WALK_COUNTER`,
`W_WHICH_POKEMON`, `W_MOVE_NUM`, `W_PLAYER_DISABLED_MOVE`, `W_WALK_BIKE_SURF_STATE`
(0 walking, 1 biking, 2 surfing), `W_STATUS_FLAGS1` with `BIT_STRENGTH_ACTIVE` and
`BIT_GAVE_SAFFRON_GUARDS_DRINK`, and `W_MOVEMENT_FLAGS` with `BIT_SPINNING` (arrow
tiles). `W_SPRITE_STATE_DATA2`, `SPRITE_STRUCT`, `SPRITE_MAP_Y` and `SPRITE_MAP_X`
locate sprite positions, and `sprite_tile(memory, sprite, *, version=None)` returns
the (x, y) tile of sprite slot `sprite`: 0 is the player and 1 to 15 the map's objects.
Read Yellow through `yellow.red_layout` as with the other addresses.

## Save summary

`save_summary.summarize_save(save, *, rom=None)` reads a 32 KiB cartridge save, given
as bytes or a path, without an emulator. It raises `SaveError`, a `ValueError`, for
the wrong size, a bad checksum, or a ROM from the other generation. The command
`pokecore summary SAVE [--rom ROM] [--json]` prints the same thing and exits 1 on a
refusal.

The result is a frozen `SaveSummary` with `to_dict()`: `generation`, `version`,
`player_name`, `rival_name`, `trainer_id`, `badges`, `johto_badges`, `kanto_badges`,
`badge_count`, `dex_owned`, `dex_seen`, `hall_of_fame`, `money`, `play_time` (hours,
minutes, seconds), `party` (`PartyMon` with `species`, `level`, `name`, `egg`),
`box_counts`, `box_total`, `map_id`, `kanto_entered`, `red_beaten` and `stage`.

Crystal and Yellow are told from the save alone. Red or Blue and Gold or Silver read
as `version=None` without the ROM, and species names always need it. `species` is the
stored byte, the internal index in Gen I and the dex number in Gen II.

`stage` is one of `new game`, `N badges` (`1 badge`), `league entered`, `champion`,
`post-game` (Gen I), `kanto entered` and `red beaten` (Gen II). In Gen I, `champion`
means the save is still inside the League after the first win. Gen II has no flag for
beating Red. The credits set the Hall of Fame counter to 200 instead, so `red_beaten`
is that counter at 200 or more, and `hall_of_fame` then no longer counts real wins.
`kanto_entered` is any Kanto badge, the Fast Ship's arrival, or Kanto's power restored.

## Emulator module

Importing the module is safe without the emulator extra. Constructing `GameBoy`
requires it. The adapter pins PyBoy 2.7.0 for save-state stability. `tick` advances
only a positive integer number of frames. `press` and `release` accept the eight
Game Boy buttons. Screenshots are native 160 by 144 PNG bytes. `save` and `load`
use opaque PyBoy state bytes. `close` is idempotent and never writes SRAM to disk.

The wrapper has no threads, wall clock, notebook, budget, or automatic actions.
Methods are not internally synchronized. The application must serialize access.
PyBoy construction reads the supplied ROM path and uses independent in-memory SRAM.

Real-time clock control on `Emulator` is additive: the `rtc_file` argument,
`stop(..., rtc_file=)`, `has_rtc`, `export_rtc`, `import_rtc`, `rtc_registers`,
`set_rtc_registers`, `rtc_state`, `set_rtc_timezero`, `lock_clock`, `unlock_clock`,
`advance_clock`, `clock_locked`, `clock_now` and the optional `rtc_clock` checkpoint
key. A locked clock exports its host-following value and a checkpoint without
clock data releases a lock. Semantics are in [rtc.md](rtc.md).

## Versioning and upgrades

Consumers pin a release artifact checksum or source commit. Do not replace a
published artifact in place. Patch releases preserve documented shapes and
behavior except clearly documented corrections. A changed observation or scoring
interpretation must be reflected in the consuming benchmark's own version.

Keep recorded core versions, artifact provenance, emulator versions, and scenario
hashes with experiments. Shared code fixes are available to both applications,
but neither automatically takes an unreviewed upstream update.

## DV probability reference

`pokecore.dvs.dv_probabilities(dvs)` accepts HP, Attack, Defense, Speed,
Special as a list or tuple. It returns `None` for missing, malformed, or
inconsistent HP data. Valid results contain `total`, `outcomes`, `at_least`,
`better`, `at_least_probability`, and `better_probability`.

The denominator is 65,536 equally weighted combinations of the four stored DVs.
HP is derived from their low bits, never sampled independently. `at_least`
includes ties, while `better` means a strictly higher five-DV total. Perfect
DVs have inclusive probability 1/65,536 and strictly better probability zero.
These are reference probabilities, not measured cartridge encounter odds or
species encounter rates. Game RNG timing can affect observed distributions.
Consumer applications own scoring, training priorities, and replacement rules.


## Controller helpers

`controls.ControllerPort` adapts a consumer's serialized controller. The consumer
supplies `memory`, `send(button, hold, gap)`, `choose(visible_label)`,
`observe()` and `frame()`. Optional callbacks are `stopped()` and
`continue_ready()`. `item_labels` maps string item IDs to cartridge menu labels.
`send` and `choose` return false when they cannot continue. They must enforce
frame budgets and record every input. No helper bypasses these callbacks.

`observe` returns `kind`, `text`, `cursor_tile`, `selected_text` and
`visible_choices` from the consumer's visible UI classifier. `kind` uses
`overworld`, `battle_menu`, `move_menu`, `menu`, `naming`, `dialogue`,
`transition` or an unsupported state. Continue readiness must only approve
continue-only dialogue, never a choice. The default waits without confirming.
`choose` selects only the supplied visible label and must also be bounded.

- `use_item(port, item, target=None, move=None)` uses any bag item through
  `shortcuts.UseItem`. `item_id=` and `party_slot=` are accepted as aliases.
- `switch_pokemon(port, party_slot)` switches a battler or makes the field party
  lead. Fainted or already active battle targets are rejected.
- Both return `outcome` and, once validated, `shortcut` metadata. `completed`
  records the observed effect, even if the controller budget expires during
  cleanup. `settled` records that the screen reached rest after it.
  `item_consumed` reports a verified bag decrement. No unconfirmed effect is
  repeated automatically.
- `ControllerPort.version` names the game (`red`, `blue`, `yellow`, `gold`,
  `silver`, `crystal`, or None for Red and Blue). `read_party`, `read_bag` and
  `panel` may be replaced. A port with its own `panel` should also supply
  `continue_ready`, or text is pressed only after it has stayed the same for two
  steps.
- `naming.name_step(rows, cursor, name, limit=10)` returns a `ButtonAction` or
  None outside the keyboard. It reads back partial text and corrects mismatches.
- `naming.enter_name(port, name, limit=10, max_actions=256, version=None)` drives
  a supplied name from an already open naming keyboard. `version` defaults to
  `port.version`. On Red, Blue and Yellow the name is uppercase ASCII. Use limit
  7 there for player and rival names. On Gold, Silver and Crystal it is capital
  letters, space and `-?!/.,`, and the keyboard's own limit applies (7 for the
  player and rival, 10 otherwise). A name over it raises ValueError. It does not
  accept nickname prompts or pick names.
- `naming.gen2_naming(memory, version)` reads the open Gen 2 keyboard: `entered`
  (read back from the name's destination), `length`, `limit`, `cursor` as
  (column, row), `lowercase` and `subject` (`pokemon`, `player`, `rival` or
  `other`). None when the keyboard is not on screen.
  `naming.gen2_name_step(memory, version, name)` returns its next `ButtonAction`.
  A letter that does not match is deleted with B, START moves to END and A on END
  submits.
- `naming.menu_button(current, target)` returns one linear menu direction or A.
- `menus.menu_options(memory, screen, kind=None)` reads visible menu rows.
  Consumer observation filtering remains required.

Menu macros have a 200-iteration ceiling in addition to the consumer's frame
budget. They do not own threads, emulator lifecycle, logging, replay or locks.
Call them only with exclusive access to the emulator. All helpers support the
verified English Red, Blue and Yellow layouts, not ROM hacks. The shortcuts below
also cover English Gold, Silver and Crystal.

## Menu shortcuts

`pokecore.shortcuts` holds one class per action (`UseItem`, `ChooseMove`,
`SwitchPokemon`, `RunAway`, `ReorderParty`, `FieldMove`, `TossItem`, `BuyItem`,
`SellItem`, `DepositPokemon`, `WithdrawPokemon`, `ReleasePokemon`, `DepositItem`,
`WithdrawItem`, `ChangeBox`, `LearnMove`, `AdvanceDialogue`, `Walk`, and for Gen 2
`GiveItem`, `TakeItem` and `DeleteMove`) and a function of the same name in snake case
that runs it on a port.

- `machine.step(memory, ui=None)` returns a button name, None to wait, or `Done`.
  `ui` may carry `screen` (overrides `current_screen`), `continue_ready` (bool) and
  `sp` (the CPU stack pointer, used to find the text wait routine). After a `Done`
  every further call returns the same `Done`.
- `Done` has `outcome`, `completed`, `settled`, `details` and `reason` (a `StopReason`).
  `done.stop_reason` fills in a reason when none was set and `done.can_continue` is
  `settled`. The port functions return it as `{'outcome': ..., 'shortcut': {'kind',
  'completed', 'settled', 'stop_reason', 'can_continue', ...}}`.
- Stop reasons (`shortcuts.STOP_REASONS`): `completed` (the effect happened and the
  screen settled), `prompt` (stopped at a game prompt for the caller), `unsettled` (the
  effect happened but the screen did not settle), `refused` (refused before any input),
  `game_refused` (the game refused the action), `no_effect` (no effect showed),
  `no_response` (a menu did not respond), `budget` (`max_steps` or the controller
  budget ran out), `stopped` (the screen stopped changing, or a script kept the
  controls), `choice` and `text_end` (`advance_dialogue`), and `blocked`, `battle`,
  `map_change` and `dialogue` (`walk`). `can_continue` is false only when the screen
  did not settle.
- `AdvanceDialogue(quiet=4, patience=120)` presses A only when the text-wait check
  says the game waits to continue. It stops at any screen that waits for a menu
  answer, or after `quiet` observations of the overworld with no script holding the
  controls (Gen 1 `wJoyIgnore` or `wStatusFlags5` bit 7, Gen 2 `wScriptRunning`).
  Details: `lines`, `text`, `truncated`, and at a choice `screen` and `choices`.
- `Walk(direction, tiles=1, patience=4)` taps `direction` once per tile and reads the
  map and coordinates (Gen 1 `wCurMap`, `wXCoord`, `wYCoord`, Gen 2 `wMapGroup`,
  `wMapNumber`, `wXCoord`, `wYCoord`). A tap that only turns the player is followed by
  another, and a dropped tap is retried once before the way counts as blocked. After a
  map change it waits for the fade and the entry script. Details: `direction`,
  `requested`, `tiles_moved`, `start`, `end` (each `{'map', 'x', 'y'}`, a Gen 2 map is
  `[group, number]`) and `facing`.
- `describe(name=None, version=None)` returns plain JSON data per command: `name`,
  `machine`, `summary`, `generations`, `arguments` (a JSON Schema object), `options`
  (`max_steps`, `nickname`), `start` (`screens`, `battle` as `any`, `required` or
  `forbidden`, and an optional `note`, plus `battle_screens` for commands that also
  run in battle) and `returns` (extra result keys and their types).
  `result_schema()` describes the common result dict.
- Constructor options: `version`, `read_party`, `read_bag`, `labels` and
  `max_steps` (default 600 steps).
- `run(port, machine)` presses a button with `send(button, 8, 24)` then waits
  `send(None, 12, 0)`, waits with `send(None, 30, 0)`, and turns a pending menu
  choice into cursor presses. `drive(machine, emulator)` does the same on a Core
  emulator.
- Shortcuts never write memory and never press A on a YES/NO prompt they were not
  asked to answer. Nickname prompts get NO. Move learning follows `forget_move`
  (a move index, or `'keep'`).
- Queries: `list_items(memory, version=None, labels=None)`, `list_party(memory,
  version=None)`, `list_moves(memory, slot, version=None)`, `list_box(memory,
  box=None, version=None)` and `current_screen(memory, version=None)`. Screen names
  are in `shortcuts.SCREENS`.
- Before a game starts, the intro and title screens are `title` and the CONTINUE or
  NEW GAME menu is `main_menu`, in all six games. The play time flag tells them
  apart from a loaded game, because a soft reset can keep the last game in WRAM.

Gen 2 (Gold, Silver, Crystal):

- The screen is classified from the tilemap and WRAM menu bytes. Extra screen names
  are `bag`, `quantity`, `pc_items`, `pc_party`, `pc_box`, `mart_list`,
  `item_target`, `move_list`, `fly_map` and `switch_prompt`.
- `run(port, machine)` calls `machine.step`, which turns menu choices into single
  cursor presses. It only calls `port.send`. `port.choose` is never called.
- Each press is held until two observations show the same screen, so the default
  budget is 600 steps, and 900 for marts.
- `use_item` turns to the item's pocket. Hold items go through `give_item(port,
  item, slot, swap=False)` and come back with `take_item(port, slot)`.
- `use_field_move` adds WHIRLPOOL, WATERFALL, ROCKSMASH and HEADBUTT.
- Gaps: mail, changing the Bill's PC box, and PC boxes other than the current one.

## Cached readers

`gen1_ui.read_screen(memory, raw_text=False)` preserves the 0.1.3 default glyph
semantics. `raw_text=True` preserves the original decoder's unknown glyphs for
PokeSim. Both use immutable glyph lookup tables. `screen_rows(raw, raw_text=False)`
accepts exactly 360 tile bytes.

`storage.memory_bytes(memory, bank, start, size)` uses bulk reads with a scalar
fallback. `storage.decode_box(structs, names)` returns frozen `BoxMon` records
with zero based positions and tuple fields. Its 128-entry cache is keyed only
by complete immutable bytes. It cannot go stale after a restore, trade or box
switch. No species validity policy is applied. `read_storage` retains its
existing dictionaries and list fields, returning fresh mutable values each call.

## Trusted resets

`resets` is deliberately separate from read-only facts and controller actions.
Never register these functions as benchmark agent commands. A fixture builder
may use them before a run, then record its setup and resulting initial-state
hash. Existing benchmark runs never import or call this module.

- `Flag(base, bit)` describes one WRAM flag and validates its address.
- `update_flags(memory, [(flag, bool), ...])` is the low-level trusted primitive.
  It preserves other bits, merges updates to one byte and preflights all reads.
  Conflicting assignments fail before writes. It returns immutable `Change`
  records containing address, before and after bytes. An unchanged update
  returns an empty tuple. Failed writes trigger verified rollback attempts.
- `reset_events(memory, flags, rooms=...)` clears a caller-defined group. It
  rejects loaded target rooms, battle, visible menus, dialogue and display
  transitions. Consumers must additionally ensure scripts are idle.
- `reset_encounter(memory, event=..., visibility=..., room=...)` clears the
  encounter event and object-hide bits together through `reset_events`.

Consumers supply verified event definitions for their cartridge. Core does not
ship generated game tables or guess reset flags. Callers must verify the ROM,
stop emulation or hold its exclusive lock, and retain reward eligibility and
claim history. These helpers do not refund items, heal, rewind a save or reset
unrelated story progress. A rollback failure is attached to the original
exception and requires the caller to stop using that state.
