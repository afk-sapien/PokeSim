# Changelog

## 0.11.0

### Added

- `save_summary.summarize_save` reads a Gen I or Gen II cartridge save from its SRAM
  with no emulator: names, badges, Pokedex counts, Hall of Fame count, money, play
  time, party, box totals, map and a story stage. Bad checksums are refused with
  `SaveError`. The ROM is optional and only adds the version and species names.
- The `pokecore summary <save>` command prints a summary, with `--rom` and `--json`.

## 0.10.2

### Fixed

- Gen I `text_lines` decodes the text box tile by tile. PK and MN tiles print two
  letters each, so a bottom row such as Yellow's "WITHDRAW PKMN" ran past the
  tilemap and raised IndexError, and earlier rows could read the wrong tile as a
  contraction. A short memory read now returns the rows it holds. The Gen II text box
  already reads tile by tile and is unchanged.

## 0.10.1

### Fixed

- `romdata.load` refuses a cartridge that is not a Pokémon game before reading it. It
  raised IndexError on a short demo ROM passed with `version=`. It now raises the new
  `UnsupportedCartridge` (a ValueError, also in `pokecore.cartridges`), whose message
  and `title` name the header title. With `version=` the header title must name a
  Pokémon game of that generation. Read errors on a Pokémon cartridge are unchanged.

## 0.10.0

### Added

- Fishing tables read from the ROM. `GameData.fishing` holds every rod table, with
  each slot's species, level and `probability` once something bites, and each table's
  `bite` chance per cast. Gen I has `old_rod`, `good_rod` and `super_rod:<map>` tables.
  Gen II has `<rod>:<fish group>` tables with slots for each time of day, and
  `GameData.fish_groups` maps each map ID to its fish group.
- `GameData.fishing_slots(rod, map_id, time=, swarm=)` answers what a rod hooks on a
  map, including Gen II's time of day and Qwilfish or Remoraid swarms.
- `romdata.load_cached(rom, version=None)` reads each ROM once, keyed by the SHA-256 of
  its bytes.

### Changed

- `GameData.canonical()` now includes the fishing tables, so its digests change.
  Overrides do not change fishing yet. A ROM randomized by another tool is read as it is.

## 0.9.5

### Fixed

- Yellow's Bill's PC opens without `sp`. It waits after both lines of "Accessed
  BILL's PC." and "Accessed POKéMON Storage System.", and the shortcut used to stop
  with "The PC did not open." after the first.
- Yellow stack readiness. `continue_ready` now finds Yellow's text wait routine, whose
  link cable branch differs from Red and Blue, and reads the raw stack, since the
  Red-layout view shifts WRAM by one byte.
- Gen 2 Bill's PC lists press A through nicknames holding `<PARA>` (0x51) or
  `<PROMPT>` (0x58). Any text engine call to PromptButton now counts as a wait.
- Gen 1 PC lists trust known stack readiness off the dialogue screen. Yellow draws
  the list off screen during a `<CONT>` wait.

### Changed

- `continue_ready` returns None instead of False when the text wait routine is not
  found, so shortcuts fall back to text that stopped changing.

## 0.9.4

### Fixed

- Bill's PC lists now press A through a nickname holding `<CONT>` (0x55). A traded
  nickname with that byte stops the list redraw at a ▼ until A or B, so withdraw,
  release and deposit used to stall with `no_response` on every slot past it. Gen 1
  sees the wait as text. Gen 2 reads it from the stack when `ui` carries `sp`, and
  otherwise falls back to the blinking ▼.

### Added

- Gen 2 `Mon.nick_bytes` holds the stored nickname bytes, so callers can spot a
  `<CONT>` byte or other control codes. It is not part of `to_dict`.

## 0.9.3

### Fixed

- Gold and Silver no longer read in-game screens as `title`. 0.9.2 took the play
  time flag from the wrong address, so Bill's PC, battles and dialogue could read
  as the title and stall `change_box`. The flag is now `wGameTimerPaused` at
  0xD8B8, found from the cartridge's own game timer code, and the title also needs
  the map to be still (`hMapAnims` clear). Crystal is unchanged.

## 0.9.2

### Fixed

- `current_screen` no longer reports `overworld` on the intro and title screens
  after a soft reset. WRAM still holds the last game there, so the screen is now
  read from the play time flag, which only a started game sets. Title art that
  shows a cursor tile is no longer a `menu`.

### Added

- The `title` and `main_menu` screen names for Red, Blue, Yellow, Gold, Silver and
  Crystal. Oak's speech before a new game stays `dialogue` and the OPTION screen
  stays `menu`.

## 0.9.1

### Fixed

- Shuffling Gen II trainer parties now gives each party member with explicit
  moves the default moveset of its new species, read from the cartridge's
  learnset. Before, the new species kept the old species' moves. Gen I parties
  and draws without trainers are unchanged, so their share codes still give the
  same overrides.

### Added

- `randomizer.default_moves(learnset, level)` returns the four moves the
  cartridge fills for a Pokemon at a level.

## 0.9.0

### Changed

- The distribution is now `pokecore`, so the release files are
  `pokecore-0.9.0-py3-none-any.whl` and `pokecore-0.9.0.tar.gz`. Install it as
  `pokecore[emulator] @ <wheel URL>`. Uninstall `pokesim-core` first, because both
  distributions ship the `pokecore` package. The repository, the native
  `pokesim-core-native` crate and the `POKESIM_CORE_*` environment variables are
  unchanged.

### Removed

- The deprecated `pokesim_core` import alias. Import `pokecore` instead.

## 0.8.0

### Changed

- The package is now imported as `pokecore`. `import pokesim_core` still works. It
  raises a DeprecationWarning and returns the same module objects, so
  `pokesim_core.gen1 is pokecore.gen1`. The distribution name `pokesim-core`, the
  wheel file names, the native `pokesim_core_native` crate and the `POKESIM_CORE_*`
  environment variables are unchanged. Run the compatibility harness as
  `python -m pokecore.compatibility`. The old `-m` name no longer runs it.

### Added

- `romdata.load(rom, version=None)` reads species, evolutions, learnsets, TM and
  HM learners, wild encounters (with Gen II morning, day and night slots), trainer
  parties and starters from the caller's Red, Blue, Yellow, Gold, Silver or Crystal
  cartridge. Core ships only the addresses. `GameData.with_overrides` applies a
  randomizer's override map and returns the effective data. With no overrides it is
  byte-identical to the ROM reading.
- `romdata.effective_data(rom, overrides)` loads and applies overrides in one call.
  `romdata.patch_rom(rom, overrides)` writes starters, wild encounters, trainer
  parties and the TM and HM list into a copy of the ROM and fixes up the global
  checksum. With no overrides it returns the ROM byte-identical.
- `rom.rom_offset(bank, address)` is the one banked ROM offset helper.
- `randomizer.randomize(data, seed, Options(...))` returns a deterministic override
  map that shuffles wild encounters and starters, and trainer parties on request,
  keeping levels. Draws that leave a required HM without a catchable wild learner
  are redrawn. `encode_share_code` and `decode_share_code` handle
  `PSR1-<GAME>-<OPTS>-<seed>` codes.

## 0.7.1

### Changed

- The `emulator` extra accepts Pillow 13, which fixes several security advisories in
  Pillow 12. Nothing else changes.

## 0.7.0

### Added

- `gen1_cable.CableDriver` drives a Red, Blue or Yellow Cable Club trade with
  controller input, and the new `centers` module has `CENTERS`, `location`, `screen`
  and `safe_center` for the Centers a session starts from. The caller passes route
  finding in as `walk`. `CableEndpoint` gains `party_slot` and `label`.
- `gen2.cable` has `CableSide`, `TimeCapsuleSide`, `CableDriver` and `MixedDriver` for
  Gold, Silver and Crystal trades and Time Capsule trades with Red, Blue or Yellow.
- `advance_dialogue` (`AdvanceDialogue`) advances printed text on all six games and
  returns the whole conversation in `lines` and `text`. It presses A only when Core's
  text-wait check says the game waits to continue, and it stops at the first choice or
  menu (YES/NO, multiple choice, the battle menu) with `screen` and `choices`, or once the
  text box closes and the player has control again. It never answers a choice.
- `walk` (`Walk`) walks up to `tiles` tiles in one direction on all six games. A tap that
  only turns the player is followed by another. It stops early when the player cannot
  move, when a battle starts, when the map changes, or when text or a menu opens. The
  result gives `tiles_moved`, `start`, `end` and `facing`. There is no route finding.
- Every result's `shortcut` dict now has `stop_reason` and `can_continue`.
  `stop_reason` is one of `shortcuts.STOP_REASONS` (the `StopReason` enum): `completed`,
  `prompt`, `unsettled`, `refused`, `game_refused`, `no_effect`, `no_response`, `budget`,
  `stopped`, `choice`, `text_end`, `blocked`, `battle`, `map_change` or `dialogue`.
  `can_continue` says whether another command can start without inspecting the screen
  first. `Done` gained the matching `reason` field and properties.
- `shortcuts.describe(name=None, version=None)` describes every command as plain JSON
  data: its arguments as a JSON Schema object, the common options, the start
  preconditions (screens, and whether a battle is required or ruled out), the games it
  runs on and the result keys it adds. `shortcuts.result_schema()` describes the result
  dict every command returns. Which commands to offer stays the consumer's choice.
- Top-level `textmatch` module with `has_word` and `ScreenText`, the whole-word keyword
  search for decoded screen text. A nickname such as PROTOTYPE or MOSQUITO no longer
  reads as TYPE or QUIT. It is generation neutral, and `gen2.screens` re-exports the
  same objects, so existing `gen2.has_word` and `gen2.ScreenText` imports keep working.
- Gen 2 `Mon` gains `pokerus` and `caught` (the raw Pokerus byte and Crystal caught data
  word). `Mon.to_dict()` adds `pokerus` ('infected', 'cured' or None), `caught` on Crystal,
  `power` and `accuracy` on each move, and `egg_cycles` on an egg.
- `gen2.caught_details`, `gen2.landmark_name` and `gen2.TIMES_OF_DAY` name Crystal caught
  data: level, time of day and the landmark, Event or Gift.
- `Snapshot.enemy_shiny` reports a shiny wild opponent. A wild Ditto that transformed is
  judged by its own DVs from `wEnemyBackupDVs`, which joins the Gen 2 memory maps.
  A custom symbol table without the Transform symbols falls back to `wEnemyMonDVs`,
  and one without `wEnemyMonDVs` gives None.
- `Mon.to_dict(egg_view=True)` and `Snapshot.to_dict(egg_view=True)` hide the species of
  an unhatched egg (`dex=None`, `name='Egg'`, no types), as PokeSim shows it. The default
  is unchanged, so existing values stay the same.
- Gen II breeding helpers: `families`, `single_source`, `lines`, `breeding_stock`,
  `egg_lines`, `free_slots` and `descendants_wanted`, plus the `DITTO` and `TYROGUE`
  constants at package level. They find the gift and static families that only the
  Day Care can copy and keep their last parent home.
- `gen2.clock` holds the Gold, Silver and Crystal clock helpers from PokeSim: `boot`,
  `lock_clock`, `follow_game_time`, `rebase_to_host`, `clock_elapsed`, `host_elapsed`,
  `clock_lock_state`, `export_clock` and `stop_with_clock`. A backend without clock
  control raises `CoreCapabilityError`. The common names are also on `gen2`.
- `gen2.save` exports a verified battery save and its `.rtc` file through the game's own
  Save menu (`capture`, `export`, `export_with_clock`, `verify`, `clock_archive`,
  `checkpoint_clock`, `continue_save`). `continue_save` returns once the trainer walks and
  no longer checks for the Pokémon Center upstairs, which stays with the caller.
- `gen1_save` does the same for Red, Blue and Yellow (`capture`, `export`, `verify`,
  `progress`, `symbols_for`). Progress is compared as raw party, box, Pokédex, money and
  name bytes, so it needs no species tables.
- `gen2.maps` holds the Gen II map physics from PokeSim: the live collision decoder
  (`collision(memory, data, snapshot)`, `decode_blocks`), `passable`, one-sided walls
  (`WALLS`, `side_blocked`), ice slides (`ICE`, `slide`, `move`, `has_ice`), the story walls
  of `travel_collision`, the event flag map changes (`CHANGES`, `DOORS`, `LEAGUE`,
  `event_changes`), `ice_solids`, `flyer` and `OUTSIDE`. The names are also on `gen2`.
- `gen2.hooks` finds ROM code addresses for emulator hooks and verifies the instructions
  there: `capture_hooks`, `encounter_hook`, `contest_hook`, `hatch_hook`, `step_hook` and
  `mart_hooks`, each raising ValueError on a signature mismatch, plus `bcd`. ROM labels the
  memory map does not carry fall back to `hooks.LABELS`.
- `gen2.resets` holds trusted setup writes: `write`, `write_byte`, `write_flag`,
  `reset_event` (a group of flags, checked before any write and rolled back on failure),
  `box_gift` (a level 5 PC gift) and `set_gs_ball` (Crystal).
- `gen1` names more Red addresses from pret/pokered: `W_FACING` and `FACINGS`,
  `W_WALK_COUNTER`, `W_WHICH_POKEMON`, `W_MOVE_NUM`, `W_PLAYER_DISABLED_MOVE`,
  `W_WALK_BIKE_SURF_STATE`, `W_MOVEMENT_FLAGS`, the sprite position layout
  (`W_SPRITE_STATE_DATA2`, `SPRITE_STRUCT`, `SPRITE_MAP_Y`, `SPRITE_MAP_X`) and the bits
  `BIT_STRENGTH_ACTIVE`, `BIT_GAVE_SAFFRON_GUARDS_DRINK` and `BIT_SPINNING`.
  `gen1.sprite_tile` reads a sprite's map tile.
- Gen 2 shortcuts `tune_radio` (`Radio`), `day_care` (`DayCare`) and `show_partner`
  (`ShowPartner`). `tune_radio` tunes the Pokegear radio, by default to the Poke Flute
  channel. `day_care` leaves a party Pokemon with either Day Care person or takes it back,
  confirmed by species, trainer ID, DVs and nickname. `show_partner` shows a party Pokemon
  until a given event flag turns on. All three are in `describe()`.
- `shortcuts.gen2ui.menu_label`, `choose` and `close_pc` read and drive Gen 2 menus.
- The Gold, Silver and Crystal naming keyboard: `naming.gen2_naming`, `gen2_name_step` and
  `enter_name` on a Gen 2 port. Names may use capital letters, space and `-?!/.,`.
- `gen2.npc_trades`, `NPC_TRADES` and `NpcTrade` (the in-game trades), `gen2.prizes` and
  `PRIZES` (Game Corner prize Pokemon), `FIELD_MOVES`, and `state.npc_trade_flags`,
  `npc_trade_done`, `npc_trades_done`, `npc_trade_qualifies` and `contest_score`.
  `wTradeFlags`, the `wContestMon` fields, `wEnemyMonAttack`, `wEnemyMonSpclAtk` and the
  naming keyboard's destination and length symbols join the Gen 2 memory maps.
- `gen2.puzzles`: `puzzle_button` and `control` solve the Ruins of Alph picture boards.
- `sprites` decodes the 151 Red, Blue and Yellow front portraits from the cartridge
  (`front_sprite`, `portraits`, `decode`, `sprite_bank`, `base_stats`), and `gen2.sprites`
  the 251 Gold, Silver and Crystal portraits (`picture`, `portrait`, `palette`,
  `front_pointer`, `dimensions`, `decompress`, `offset`). Pictures are rows of colour
  indices. `sprites.png(pixels, palette=SHADES)` writes one as an RGBA PNG with the
  standard library, so no imaging library is needed.
- `formulas` holds the experience curves both generations share: `experience_at` and
  `experience_progress`. `gen2.experience_at` and `gen2.experience_progress` are the same
  functions.
- `identity` gains trade keys that survive evolution and the Time Capsule:
  `family_key(trainer, dvs, dex, families=None)`, `family`, `dex_of`, `same`, `find`,
  `legacy` and `is_legacy`, with the `FAMILIES`, `FAMILY_ROOTS`, `GEN1_DEX` and
  `GEN1_INDEX` tables.

### Fixed

- Shortcuts on Yellow read the party and bag at Yellow addresses. `use_item`,
  `switch_pokemon` and the other shortcuts used the Red and Blue readers on raw Yellow
  memory, which is shifted by one byte.
- `delete_move` and Gen 2 `deposit_pokemon` no longer raise `KeyError` when a custom
  `read_party` leaves out the `egg` field.
- `use_item` with a fishing rod waits on the overworld while the line is cast. Gen 2 closes
  the pack before "Not even a nibble!" or "Oh! A bite!" prints, so every rod used to stop with
  "returned without a confirmed effect". A cast that never prints a message still stops
  without a second cast.
- Waiting for an item's effect on the overworld no longer presses A there, where it could
  talk to someone or offer SURF.
- `enter_name` on a Gold, Silver or Crystal port drives the Gen 2 keyboard. It used to read
  the Red and Blue screen layout there.

### Changed

- `gen2.offspring` builds each species table's pre-evolution map once instead of
  scanning the table for every pair. The result is unchanged, including the first
  pre-evolution in species order when two species evolve into the same one.
- The emulator extra requires PyBoy RS 0.1.2 or newer (`pyboy-rs>=0.1.2,<0.2`). Its clock
  `set` is exact, a halted clock stays frozen, and loading a state restores the latched
  registers. CI installs the v0.1.2 release wheel.
- The shortcuts read Gen 1 addresses from `gen1` instead of their own copies.
  `shortcuts.actions.W_WALK_BIKE_SURF` is now `W_WALK_BIKE_SURF_STATE`, and
  `shortcuts.walk.W_PLAYER_FACING` is the same value as `gen1.W_FACING`.

## 0.6.0

### Added

- `change_box` (`ChangeBox`) switches the current box through Bill's PC on all six games
  and answers the save prompt.
- `learn_move` (`LearnMove`) answers a learn-a-new-move prompt on all six games: replace
  a move slot, or keep the old moves with `'keep'`. HMs and empty slots refuse.
- `delete_move` (`DeleteMove`) for the Gen 2 Move Deleter.
- A `nickname` option on every shortcut. `'no'` (the default) answers NO to a caught
  Pokemon's nickname prompt. `'caller'` stops there with `pending='nickname'`.
- `choose_move` handles a forced turn. With no PP left or a locked move, FIGHT starts
  the turn at once, and the result says `forced='struggle'` or `forced='locked'`.
- A thrown ball that catches reports `caught` in the result.

### Fixed

- Gen 2 FLY checks the Storm Badge, not the Mineral Badge.
- The Gen 2 party submenu is recognized when it scrolls, so party reorders, switches and
  field moves on a Pokemon with four field moves no longer stop with no effect.
- Gen 2 refusals for a move that can't be deleted or forgotten end the shortcut.
- A Gen 2 switch after a faint waits for the party screen under "Which PKMN?". It no
  longer presses B there and stops with "Menu did not respond".
- On Gen 2, an A press meant for text is dropped when a menu replaces the text before
  the press goes out, so it no longer opens FIGHT after a switch.
- The Gen 2 move menu is recognized while the cursor is on a disabled move, and
  `choose_move` refuses a disabled move before sending input.

## 0.5.0

### Added

- Menu shortcuts for Gold, Silver and Crystal. Every 0.4.0 action now runs on Gen 2:
  `use_item` (all kinds, with pocket switching and Berries), `choose_move`,
  `switch_pokemon` (also from the battle switch prompt), `run_away`, `reorder_party`,
  `use_field_move`, `toss_item`, `buy_item`, `sell_item`, `deposit_pokemon`,
  `withdraw_pokemon`, `release_pokemon` (still needs `allow_release=True`),
  `deposit_item` and `withdraw_item`.
- `give_item` and `take_item` (`GiveItem`, `TakeItem`) for Gen 2 held items. Replacing
  a held item needs `swap=True`.
- Gen 2 field moves WHIRLPOOL, WATERFALL, ROCKSMASH and HEADBUTT, with badge checks.
- Gen 2 item kinds and usage for every item ID, from pret pokecrystal and pokegold.
  Item names are decoded from the cartridge.
- `current_screen` names Gen 2 screens: the four pack pockets, party, item target,
  move list, quantity box, mart menu and list, the PC, Bill's PC menu and lists, the
  item PC, the battle menus, the switch prompt, YES/NO and text.

### Changed

- Gen 2 actions no longer refuse with "Not supported in Gen 2 yet".
- On Gen 2, `run` resolves menu choices itself and only calls `port.send`.
- The optional real cartridge shortcut tests release every button after loading a
  state and accept the battle switch prompt as rest.

## 0.4.0

### Added

- `pokesim_core.shortcuts`: resumable menu shortcuts for Red, Blue and Yellow. Each is a
  machine with `step(memory, ui)` that returns one button, a wait or a final `Done`, and
  never writes memory. `run(port, machine)` and `drive(machine, emulator)` are the
  blocking wrappers.
- Actions: `use_item` for every item kind, `choose_move`, `switch_pokemon`, `run_away`,
  `reorder_party`, `use_field_move` (CUT, SURF, STRENGTH, FLASH, FLY to a named town),
  `toss_item`, `buy_item`, `sell_item`, `deposit_pokemon`, `withdraw_pokemon`,
  `release_pokemon` (needs `allow_release=True`), `deposit_item` and `withdraw_item`.
- Queries: `list_items`, `list_party`, `list_moves`, `list_box` and `current_screen`.
- `ControllerPort.version` selects the game. Gen 2 actions refuse before any input.
- Optional real cartridge shortcut tests read save states and a manifest from
  `POKESIM_CORE_SHORTCUT_STATES`. None ship with Core.

### Changed

- `controls.use_item(port, item, target=None, move=None)` covers every item kind. The
  0.3 keywords `item_id` and `party_slot` still work. `controls.switch_pokemon` runs the
  new machine.

### Fixed

- Shortcuts no longer stop on a text screen after the effect. In battle, "recovered by"
  and the foe's turn are pressed through until the battle menu, the move menu, a forced
  switch or the end of the battle. If the screen never settles within the budget the
  result says `completed` and not `settled`.

## 0.3.0

Distributed as GitHub release files: the wheel `pokesim_core-0.3.0-py3-none-any.whl`,
the sdist `pokesim_core-0.3.0.tar.gz` and `SHA256SUMS.txt`. Not on PyPI.

0.2.0 was never tagged or released. 0.3.0 is the first release with the PyBoy RS
backend, so everything listed under 0.2.0 below ships for the first time here. The
`emulator` extra requires `pyboy-rs>=0.1.1,<0.2`; install the
[pyboy-rs v0.1.1](https://github.com/afk-sapien/pyboy-rs/releases/tag/v0.1.1) release wheel.

### Added

- `pokesim_core.cartridges`: a registry of the six clean English cartridges PokeSim plays
  (Red, Blue, Yellow, Gold, Silver, Crystal) with `identify`, `identify_sha1`, `identify_file`,
  `by_version`, `generation`, ZIP `unpack`, header decoding with both checksums (`read_header`),
  refusal reasons (Crystal Rev 0 and the Australian Crystal are refused) and the slot shelf.
- Yellow: `pokesim_core.yellow` with `red_layout` (a Red-layout view of raw Yellow memory),
  `read_pikachu` (happiness, mood, follow, surf and starter flags, `starter_slot`) and
  `YellowEmulator`, a Core `Emulator` whose `memory` uses Red addresses. `open_emulator(rom)`
  picks it for Yellow. `gen1.read_party`, `read_bag`, `read_progress`, `read_starters`,
  `read_trainers`, `gen1_ui.read_battler` and `read_storage` take `version=`.
  `read_starters` reports Yellow's rival evolution.
- `pokesim_core.gen1_battle_power`: PokeSim's Gen I battle power estimates (`BattlePower`,
  `calculated_stat(s)`, `stored_strength`, `stat_exp_bonus`, `dv_rating`) from the caller's
  game tables. `dvs` adds `is_perfect`, `is_shiny` and `shiny_bytes`.
- Trades and the Time Capsule: `gen1_link_metadata` gains the Yellow build,
  `gen2_link_metadata` covers Gold, Silver and Crystal, `timecapsule` converts between
  generations and checks compatibility, and `trade` verifies Gen I and Gen II trades with
  PokeSim's error messages. All pure and read-only.
- `pokesim_core.gen2`: read-only Gold, Silver and Crystal decoding moved from PokeSim with identical output. It has per-version memory maps and charmaps, party and PC boxes (DVs, shiny, held item, friendship, Pokerus, Crystal caught data), bag, pockets and PC items, Pokedex seen, caught and Unown forms, money and Johto and Kanto badges, player and map state, the game clock and RTC base, the Day Care and eggs, and roamers. The full `read_snapshot` takes consumer game tables. Core ships no game tables.
- Gen II `battle_power` and `hidden_power`, Day Care rules (`offspring`, `retrieval_cost`, `branch_parents`) and evolution-line credit (`ancestors`, `level_credit`).
- `pokesim_core.memory_snapshot.snapshot_emulator`: a per-step memory snapshot for any Core emulator class. It reads whole banks with `read_bank_bytes` (with a per-byte fallback for older `pyboy-rs`), serves unbanked Gen I reads from one WRAM copy and is invalidated by ticks, writes, loads and restores.
- `Memory.read_bank_bytes(bank, start, stop)` on the Core emulator.
- `gen2.version_of(rom_bytes)` identifies a Gen II ROM through `cartridges.identify`.
- Decoded Gen II regions are cached by their raw bytes and game tables.
- Optional cartridge tests run when `POKESIM_CORE_GEN2_ROMS` names a local ROM directory.
- `rom.require_rom` accepts any registered version named in `allowed_games`.
- The release also attaches the sdist and a `SHA256SUMS.txt`, and the notes come from this file.

### Changed

- `storage.memory_bytes` uses a snapshot window when the memory offers one. Results are unchanged.
- CI installs the released `pyboy-rs` v0.1.1 wheel (pinned by SHA-256) instead of building a commit, and requires the `bank_bytes` feature.
- The package description now covers all six games. `inspect_rom` and `KNOWN_ROM_SHA1`
  still describe only Red and Blue, as in 0.1.x.

### Compatibility

- All additions are new modules or keyword arguments with Red and Blue defaults. The
  0.1.x pure-Python surface is unchanged. `API_VERSION` stays 1.

## 0.2.0

Never tagged or released on its own. These changes first ship in 0.3.0.

### Added

- Native emulator interface: `Emulator` and `GameBoy` run on the Rust `pyboy-rs` backend. Install it with the `emulator` extra, which pins `pyboy-rs>=0.1.1,<0.2`.
- RTC support: PyBoy 2.7.0 compatible RTC file import and export, explicit clock register access and a deterministic lockable clock. Capability is detected from the `pyboy-rs` clock control flag.
- `CoreCapabilityError`, a `RuntimeError` subclass, raised when the installed backend lacks a needed capability. It does not subclass `NotImplementedError`, so existing `except NotImplementedError` handlers will not swallow it.
- Checkpoints of RTC cartridges store the clock lock in `rtc_clock` beside the state. A locked checkpoint refuses to load on a backend without the equivalent lock.

### Changed

- Checkpoint restore compares the runtime version and state format by default. The old binary sha256 comparison is available as the opt-in `exact` mode.
- Checkpoints and `retag_checkpoint` output keep `pyboy_version: "2.7.0"` when that is truthful, so PokeSim 0.4.x can still load them.
- The README test count and `API_VERSION` documentation are corrected. `press()` is documented as waiting for the tick.
- Backend change for 0.1.x users of `GameBoy` and the `emulator` extra: the backend is now `pyboy_rs`, not `PyBoy`. Code that monkeypatches a fake `pyboy` module must patch `pyboy_rs` instead. Eight tests in the 0.1.4 `test_emulator.py` do exactly this and fail by design against 0.2.0 without `pyboy-rs`.

### Fixed

- `Emulator.checkpoint()` now includes `pyboy_version: "2.7.0"` like `checkpoint_metadata()` and `retag_checkpoint()` do, so PokeSim 0.4.x accepts a Core checkpoint on rollback. The tag is still omitted for locked-clock checkpoints and any state PyBoy 2.7.0 cannot load.

- `export_rtc()` and `stop(rtc_file=)` while the clock is locked write the host-following equivalent instead of the fake locked base (which read as about +1057 days elsewhere). Requires `pyboy-rs` with `rtc_export_follows_host`.
- `restore_checkpoint` on a cartridge with a clock always applies the checkpoint's lock, and a checkpoint with no clock data releases any lock instead of keeping it.
- A checkpoint restores on a rebuilt or other-OS `pyboy-rs` wheel of the same version, as the README says. The backend rejected it before; it now checks state format and cartridge.
- Release workflow: refuses to modify a published release, actions are pinned by commit, and the wheel is attached with a `SHA256SUMS` asset whose hashes are also in the job summary.

### Removed

- The unpublished `acceleration` extra is gone from the published metadata. The native crate stays in the repository and builds from source, see the README.

### Compatibility

- The pure-Python 0.1.x surface (names, signatures and behavior outside the emulator) is unchanged and passes without `pyboy-rs` installed.
- Published 0.1.x wheels are untouched. Consumers pinned by hash to a 0.1.x wheel are unaffected.
- CI builds `pyboy-rs` from a pinned commit and runs the emulator and RTC suites. A separate job builds the native decoder.

## 0.1.4

- Consolidate bounded restorative item use and party switching through caller-owned controllers.
- Add resumable name entry and visible menu readers, keeping name and gameplay choices in consumers.
- Share cached screen glyphs and immutable bulk storage decoding without changing existing reader shapes.
- Add a separate trusted reset API for encounter and event groups, with preflight validation, context checks, change receipts and rollback on write failure.
- Keep benchmark observations, frame budgets, logs, reward timing and simulation strategy in their applications.

## 0.1.3

- Add read-only screen, sprite, battler and owned-storage readers.

## 0.1.2

- Add validated DV-total tail probabilities using all 65,536 stored DV combinations
  with derived HP. Expose inclusive and strictly better counts and probabilities
  under an explicitly uniform reference model. No gameplay policy is included.


## 0.1.1

- Correct the project name to PokeSim Core, the distribution to `pokesim-core`, and the import to `pokesim_core`.
- No changes to game decoding or emulator behavior.

## 0.1.0

- Initial shared core release, published under the incorrect project name.
