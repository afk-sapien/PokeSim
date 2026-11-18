# Runtime map

Status: written from the code on 2026-11-17, from main at `4d4e10e6` plus the PR that added this page. Each claim names the `file:line` it was read from. Paths are under `pokesim/`, except those that start with `tools/` or `packages/`. A bare `:N` is a line in the file named last before it. When a line number has drifted, trust the code.

This page answers what runs, in what order, how often and in which file. Designs and plans are listed in the [documentation index](README.md#designs). Older plans are in [docs/history](history/README.md).

## Processes

1. The manager serves the Adventure Library (`app/manager.py:2099`, uvicorn at `:2154`) and proxies each adventure's pages through `/games/{aid}/{path}` (`:1690`).
2. Its `Supervisor` (`app/supervisor.py:211`, `start` at `:316`) starts one worker process per running adventure, each held by a `Child` (`:65`). The child's command is `python -m pokesim.runtime.worker`, or `--worker` in a frozen build (`:77-78`). The child starts it with `Popen` (`:87`) and writes a bootstrap JSON to its stdin (`:96`).
3. The worker (`runtime/worker.py:274`, `serve` at `:80`) builds a `SimulationRuntime` (`:104`), starts it (`:109`), creates the web app (`:115`) and prints its ready line (`:234-236`).
4. `SimulationRuntime` builds the generation's emulator: the Gen II import is at `runtime/simulation.py:73`, the Gen I import at `:78`, the call at `:91`. Legacy single-game mode builds it at `runtime/legacy.py:37`.
5. The emulator plays on one thread, `emulator` for Gen I (`emulator.py:175`) and `gen2-emulator` for Gen II (`gen2/emulator.py:231`).

The manager starts the monitor (`app/manager.py:359`). Every 3 seconds (`app/supervisor.py:36-38`) one pass (`monitor_once`, `:708`) checks each worker (`check`, `:798`). It calls the worker's `GET /healthz` and `GET /api/summary` (`:820-821`) and stores a changed summary in the registry (`:853`). The worker serves `/api/state` (`web/app.py:592-593`) and `/api/summary` (`:609-610`).

## Hosts

A host owns a PyBoy instance, a policy and a frame counter, and runs the loop below.

| Host | Where | Runs |
| --- | --- | --- |
| `EmulatorBase` | `runtime/emulator.py:50` | Base of both app emulators. Owns the tick (`:223-254`) and the commands queue (`:105-106`). |
| Gen I `Emulator` | `emulator.py:75` | Red, Blue and Yellow in the application. |
| Gen II `Emulator` | `gen2/emulator.py:151` | Gold, Silver and Crystal in the application. |
| `HeadlessRun` | `runtime/headless.py:27` | Scenarios, replays and tools, both generations. |

`GameAdapter` (`runtime/adapter.py:41`) holds what differs between the generations in a headless run, with one `Settings` each (`:35-38`): boot, policy, fresh start, read, options, checkpoint check, load extras, manifest fields and the step before a save. Only `HeadlessRun` builds one (`adapter_for`, `:93-100`, called at `runtime/headless.py:40`).

The application emulators boot and load for themselves, because an adapter cannot express how they differ:
- Their `_boot` returns a fresh machine. It runs again for the reward delivery and TM purchase clones, after a failed restore, for a power cycle with no save and for a new game. An adapter `boot` sets up the whole run once.
- They play with sound and keep one tracer from the store for the adventure's life, made before the first boot. The Gen II Mart stock also takes the store's Champion offers and reports each purchase.
- Their loads check the trade and reward barrier first. Gen II stores the running cartridge clock reading before the load, then locks the clock to the furthest reading the adventure has seen. It writes the options byte at the first valid started snapshot, not at the load.

Both Gen II hosts call two functions of `gen2/adapter.py`: `cartridge_game_data` (`:17`), the game data with the cartridge's own encounter rows and boss parties, and `write_options` (`:28`).

## The loop

`GameLoop` (`runtime/game_loop.py:89`) and `Decider` (`:74`) are shared by all three hosts. The policy benchmark (`benchmark.py:84`) and the Gen II scenario runner (`replay/play_gen2.py:194`) also build a `GameLoop` of their own.

- `Decider.ask` (`runtime/game_loop.py:82-86`) writes the Gen I options byte when it has a writer (`:83-84`), builds a `PolicyContext` (`:85`) and calls `policy.step`. An empty answer becomes one 12 frame wait (`:86`, `IDLE_FRAMES` at `:22`). A Gen II host passes no writer (`runtime/adapter.py:35-38`, `gen2/emulator.py:1021-1022`).
- The options byte is also kept outside the decider. Gen I enforces it on every observation of a started game (`emulator.py:503`). Gen II writes it in `_observe` once after each state load, reload or new game, outside manual control (`gen2/emulator.py:534-536`).
- `PolicyContext` carries the snapshot, the PlayClock frames, the memory and the stack pointer (`runtime/policy.py:43-48`).
- An `Action` is a button, a hold (8 frames by default) and a gap (`runtime/policy.py:21-32`). It lasts hold plus gap, or hold plus the generation's wait when it names no gap (`:30-32`). The wait is 2 frames in Gen I and 16 in Gen II (`runtime/game_loop.py:24-25`).
- `GameLoop.decide` (`runtime/game_loop.py:104-113`) replaces the pending actions with the new answer (`:108`) and then writes a trace record (`:109-112`).
- `GameLoop.act` (`runtime/game_loop.py:115-127`) pops one action and plays it (`:117-118`). Then it autosaves if due (`:120-121`) and runs the guards if due (`:122-126`).
- `play` (`runtime/game_loop.py:30-54`) presses, ticks the hold, releases in a `finally` (`:51-53`), then ticks the gap or wait (`:54`).
- `GameLoop.step` (`runtime/game_loop.py:129-133`) is one decision and every action it asked for. Only runs outside the application use it: `runtime/headless.py:123`, `replay/validate_progress.py:72` and `tools/verify_cartridge.py:723`.

### One pass of the Gen I run loop

`Emulator._run`, `emulator.py:1029`.

1. Build the loop with the options writer (`:1032-1033`) and make sure a trace segment is open (`:1040-1041`).
2. Run queued commands (`:1042-1045`). A new input epoch clears the pending actions (`:1048-1049`) and drops queued manual presses (`:1051-1052`).
3. A manual press replaces the pending actions (`:1053-1054`). Manual control with no press plays a one frame wait (`:1055-1057`). A pause sleeps and starts the next pass (`:1058-1063`).
4. Decide only when no action is pending (`:1064-1068`). Preparation, when set, goes through the decider in place of the policy (`:1067-1068`). One Gen I decision covers every action it returned, the sum of their holds and gaps.
5. Record activity events (`:1069-1077`), play one action (`:1086`), then, with isolated RAM, handle TM purchases and reward delivery (`:1091-1100`).
6. An error in a pass goes to `loop_failed` (`:1103-1105`), which stops the run when a fatal error is set or the same pass failed ten times in a row (`loop_errors.py:7-12`). On exit the run makes a final autosave unless a fatal error is set (`emulator.py:1106-1108`).

### One pass of the Gen II run loop

`Emulator._run`, `gen2/emulator.py:1018`.

1. Build the loop with a 16 frame wait, and autosave only while the policy is not backing out (`:1021-1022`). Make sure a trace segment is open (`:1029-1031`).
2. Run queued commands (`:1032-1039`). A trade hold sleeps and skips the pass (`:1040-1043`). Rewards and the Celebi check run every 300 frames (`:1044-1049`).
3. Preparation skips the decider and sets the pending action itself (`:1050-1051`). Manual control and pause also skip the decision (`:1052-1061`).
4. Decide (`:1062-1067`), then play one action (`:1068`).
5. An error goes to `loop_failed` (`:1070-1072`). On exit the run flushes its step log and makes a final autosave unless a fatal error is set (`:1073-1077`).

The Gen II policy returns exactly one action (`gen2/policy/__init__.py:257`), so one Gen II decision covers one action: its hold plus its gap, or plus the 16 frame wait. Most are short, but a straight walk is one `Hold` across several tiles, held up to 16 frames a tile plus 32 and released early when its stop check says so (`gen2/policy/navigation.py:249`, `Hold` at `runtime/policy.py:36-40`).

### HeadlessRun

`HeadlessRun` builds its adapter (`runtime/headless.py:40`) and a `GameLoop` with no guards and no autosave (`:51`). Its tick only advances PyBoy and the frame, so nothing observes (`:115-118`). `step` calls `loop.step` (`:120-124`).

Callers: `scenarios.py:757`, `replay/rung.py:107`, `replay/find_stalls.py:60`, `tools/stage_ladder.py:178`, `tools/benchmark_decisions.py:290`, `tools/quality_hunt_watch.py:92` and ten test files.

## Cadences

| What | How often | Where |
| --- | --- | --- |
| Decide | Gen I: when no action is pending. Gen II: every pass the steps above do not skip. | `emulator.py:1064-1068`, `gen2/emulator.py:1062-1067` |
| Observe | When a tick crosses a multiple of 30 frames. Ticks move 4 frames at a time, 1 while sound plays. | `runtime/emulator.py:42-43`, `:232-233`, `:251-252` |
| Guards | At least 60 frames apart, checked after an action ends, and again after a reload moves the frame back. | `runtime/game_loop.py:20`, `:122-126` |
| Autosave | Every 300 seconds of game time. | `config.py:40`, `runtime/game_loop.py:102`, `:120-121` |
| Gen II rewards | Every 300 frames. | `gen2/emulator.py:1044-1049` |

Observation reads the snapshot and writes the journal: Gen I `_observe` (`emulator.py:465`) calls `_observe_snapshot` (`:499`), and Gen II has `_observe` (`gen2/emulator.py:527`). The Gen I guards skip manual control, pause and preparation (`emulator.py:1024-1027`). The Gen II guards also skip a trade hold (`gen2/emulator.py:915`). Both stand down for 3600 frames after a reload (Gen I `RELOAD_QUIET_FRAMES`, `emulator.py:53`, checked at `:793`, and `gen2/emulator.py:923`). The Gen II guards also stand down while the policy is idle, waiting for the cartridge clock (`gen2/emulator.py:925-931`).

## Policy

The protocol is `Policy` (`runtime/policy.py:72`). `step` returns one or more actions to play before the policy is asked again (`:80-82`). It also has save, restore, reset, goal and pin hooks (`:87-135`).

- Gen I: `StrategicPolicy` (`policies/strategic.py:157`), `step` at `:442-444`.
- Gen II: `Policy` (`gen2/policy/__init__.py:35`), built from parts, `step` at `:224-230`, the body in `_step` (`:259`).

### The decide pipeline

Each generation fills a `Ballot` from its sites (`policies/pipeline.py:27-48`, `gen2/pipeline.py:25-39`). `Ballot.decision` calls `decide.decide` (`policies/pipeline.py:88-92`, `gen2/pipeline.py:81-85`). The running goal is the decision's pick (`policies/pipeline.py:94-97`, `gen2/pipeline.py:87-90`).

`decide` (`planning/decide.py:147`) keeps the latest offer of each goal, parks the offers that cannot run, then picks in order: a move the game forces, a goal under way, the arbiter's rank, then the enabler of the best goal's first unmet need (`:3-5`). It is live in both generations (`policies/pipeline.py:1-8`, `gen2/pipeline.py:1-9`). The Gen II collection rungs run an inner `decide.decide` at their site (`gen2/collection.py:905-906`). The `pipeline` shadow point only records the pick (`policies/strategic.py:1090-1094`, `gen2/policy/__init__.py:250-254`).

Gen I step order, in `policies/strategic.py`: observers (`:479-487`), Hall of Fame (`:490-496`), naming (`:498-505`), shortcut (`:509-517`), map transition (`:522-536`), ballot sites (`:546-580`), release and box (`:600-620`), boss and heal latch (`:621-628`), the retry when nothing on screen changes (`:644-691`), then `_dispatch` (`:692`, defined at `:705`). The overworld goes to `_overworld` (`:875`, defined at `:907`), which makes the offers (`:907-1094`).

Gen II step order, in `gen2/policy/__init__.py`: rescue (`:277-280`), the Ruins puzzle, naming and other screens (`:283-325`), battle (`:326-328`), `nav.observe` (`:331`), the ballot with journey and release (`:339-346`), menu task (`:352-364`), conversations, which run under the heal errand (`:378-391`), HM errands (`:397-437`), heal and shop (`:460-470`), parking goals with no route (`:471-483`), `nav.toward` (`:497-507`), then it commits the pick (`:512`) and follows it (`:514`).

### What survives between decisions

This table lists the plan-like state, not every field.

| State | Gen I | Gen II |
| --- | --- | --- |
| Goal | `goal` (`policies/strategic.py:174`), set from the pick (`:580`) | `goal` (`gen2/policy/__init__.py:52`) |
| Trip, the errand under way | `Trip` (`planning/errand.py:41`), resumed at `policies/strategic.py:451-462` | `trip` (`gen2/policy/__init__.py:57`), resumed at `:237-246` |
| Menu | menu context, cleared on restore (`policies/strategic.py:302`) | `menu` (`gen2/policy/__init__.py:60`) |
| Shortcut | `ShortcutRunner` (`policies/strategic.py:210`), cancelled on restore (`:252`) | blocked shortcuts (`gen2/policy/__init__.py:83`) |
| Walk path | a path deque (`policies/navigation.py:257`), reused while the target is unchanged (`:761-766`), cleared on restore (`:417`) | none |
| Rescue presses | none | `rescue` (`gen2/policy/__init__.py:96`), filled on a recovery (`:204-208`), played first in a step (`:277-280`) |
| Navigator memory | `visits`, `blocked` and `failures` beside the walk path (`policies/navigation.py:251-254`) | `blocked`, `visits`, `explored`, `exploring`, `failed_edges` and `searches` (`gen2/navigation.py:97-103`) |

Gen II stores no walk path. `toward` (`gen2/navigation.py:377-405`) routes again on every call and drops the expired region failures (`:381`). Its BFS search caches progress per start (`gen2/routes.py:13-19`). A Gen I restore resets about 60 fields in `on_restore`, the trip, menu and shortcut among them (`policies/strategic.py:245-324`).

## Planning

Shared by both generations, in `planning/`. Each module's first line says what it owns.

| Module | Owns |
| --- | --- |
| `arbiter`, `values`, `cost` | Ranking goals: what progress is worth, what a goal costs. |
| `decide` | The pipeline above. |
| `goals`, `catalogue`, `pin` | Goal records (`planning/goals.py:19-24`), the goal catalogue and the manager's pin, which ranks after upkeep and before every other source (`planning/pin.py:1-4`). |
| `errand` | Errands as task objects (`planning/errand.py:41`). |
| `conditions`, `boss`, `readiness`, `league`, `losses` | Preconditions and boss readiness. |
| `ledger`, `monitor`, `unreachable` | Resources, progress backoff per goal, walk targets with no route. |
| `progress`, `shadow` | Progress events from two snapshots, and shadow records: the decide pipeline's record, and the arbiter beside the old order at the two Gen II points that still use it (`planning/shadow.py:1-8`). |
| `stance`, `throws` | Fight, flee or catch, and catch odds. |

There is no goal queue. The manager's pin holds one goal.

## Supervision

`runtime/supervision.py` is one ladder for both generations (`:1-21`): rung 0 parks the goal, rung 1 reloads and the third reload in a row reports, rung 2 restarts a League attempt from its entry save, and rung 3, after twelve reloads, gives up on the stuck goal or holds when there is nothing to give up. The limits are at `:47-56`. `Supervisor` is at `:215` and `climb` at `:257`. The counts live in the adventure store under `KEY` (`:41`), so a worker restart keeps them (`:3-5`).

What starts a climb:

- Gen I `_check_guards` (`emulator.py:782`): a glitched state (`:805`), stuck for 600 seconds (`:806-816`, `config.py:42`), a battle over 900 seconds (`emulator.py:817-819`, `config.py:43`), a battle that cannot end (`emulator.py:820-822`), then the stall check (`:823`). A Gen I stuck run first tries the policy's `recover_stall`, which replans with no reload (`:807-814`). The Gen I `_unstick` climb passes no park (`:728-730`).
- Gen II `_check_guards` (`gen2/emulator.py:913`): a glitched state (`:943-944`), a menu task that failed three times (`:945-946`), the battle timeout (`:947`), a battle that cannot end (`:949-951`), stuck (`:952-953`), no progress for three times the stuck limit (`:954-955`), an unchanged screen, which asks the policy to recover (`:956-960`), then the stall check (`:961`). The Gen II climb parks and reloads after a park (`:832-834`).
- Both stall checks run `EmulatorBase._check_stall` (`runtime/emulator.py:418`), which journals the entry through the generation's `_event`.

## Trace and capture

- The trace keeps one segment per autosave, in `states/trace/<autosave>/segment.jsonl.gz` (`runtime/trace.py:1-8`, `:39-40`). Each autosave opens the next segment in `EmulatorBase._write_autosave` (`runtime/emulator.py:310-312`).
- Capture keeps a stall bundle at each trigger, the kinds `quiet`, `give_up`, `loop`, `gate` and `ladder` (`runtime/capture.py:1-6`, `:19`). Bundles are written by `checkpoints.py:154-156` into the stalls folder (`:295-296`).
- `replay/capture.py` and `replay/diverge.py` read them back.

## State

`state/` is the one owner of `pokesim.sqlite` (`state/__init__.py:1-4`). Its modules are `schema`, `kv`, `domains`, `journal`, `ledgers`, `claims`, `manifests` and `tracking`. `Store` (`store.py:29`) imports it (`:18`) and opens the database through `schema.connect` (`:78`). Game decoding comes from pokecore (`packages/pokecore/src/pokecore/`).

## Measured

Each run plays 216000 frames, one game hour, from a fixture copied from a save, niced, one at a time, with seed 7 in place of the tool's 12345 (`replay/profile_simulation.py:84`). Shares are of the run's wall time, from the tool's timers, which count only the emulator thread (`:24-25`, `:126-136`). Emulator is `CoreEmulator.tick` with its hooks, policy is the policy's `step`, observe is the emulator's `_observe`.

```sh
python -m pokesim.replay profile-simulation capture --source ADVENTURE --output FIXTURE \
    --rom ROM --game-data GAME_DATA
python -m pokesim.replay profile-simulation run --fixture FIXTURE --output OUT \
    --frames 216000 --profiler timers --cpu 13
```

Nearly all simulated time is past the Champion, thousands of hours in, so the deep postgame saves are the standard set and every speed change is measured on them. A Gen II fixture needs game data that holds the Gen II tables. Snapshot from 2026-11-17, at `40679ae6` with the Gen II egg scan building the PC's rating key once per scan, and with the cartridge clock's host time fixed:

| Save | Wall | Frames per second | Emulator | Policy | Observe |
| --- | --- | --- | --- | --- | --- |
| Red, 17,136 hours | 40.3 s | 5362 | 22.5% | 27.9% | 26.1% |
| Gold, 6,873 hours | 62.9 s | 3432 | 16.4% | 62.8% | 11.0% |
| Crystal, 6,680 hours | 267.3 s | 808 | 4.1% | 90.9% | 2.9% |

Shallower saves, from 2026-11-17 at `4d4e10e6`:

| Save | Wall | Frames per second | Emulator | Policy | Observe |
| --- | --- | --- | --- | --- | --- |
| Red, late game | 29.1 s | 7412 | 29.1% | 20.2% | 25.6% |
| Red, 4 badges | 23.7 s | 9100 | 37.2% | 15.2% | 25.6% |
| Gold, late game | 38.4 s | 5618 | 26.8% | 42.6% | 16.6% |
| Gold, 4 badges | 25.7 s | 8417 | 41.5% | 16.5% | 23.0% |

These are one run each on one machine. Rerun them before comparing.

## Known duplication

- The Gen I and Gen II `Emulator` classes still write 20 same-named methods twice (Gen I line / Gen II line): `__init__` 83/155, `_boot` 188/233, `start` 215/313, `freeze` 228/323, `status` 248/1086, `_load_state_file` 314/440, `_shot_png` 431/392, `current_frame` 438/383, `_observe` 465/527, `_watch_boss` 470/685, `_note_progress` 490/707, `_autosave` 657/417, `_reset_watch` 681/732, `_give_up` 687/745, `_unstick` 712/825, `_check_guards` 782/913, `set_trade_preference` 851/1122, `_new_game` 974/974, `_start_new_game` 986/983, `_run` 1029/1018.
- Twelve more same-named methods fill `EmulatorBase` hooks: `held_back`, `_frame_png`, `_manifest_fields`, `_take_control`, `_resume`, `_flush_before_restart`, `_event`, `_note_achievement`, `_shiny_reason`, `_species_name`, `_headroom` and `_identity`.
- `EmulatorBase` holds the one journal sink, `_journal` and `_push` (`runtime/emulator.py:374-396`), and the methods that were written twice before it: `_shared_status` (`:90`), `_drop_pin` (`:144`), `pc_values` (`:157`), `request_release` (`:169`), `_write_autosave` (`:304`), `_report_missed_shiny` (`:398`) and `_check_stall` (`:418`). Each generation's `status` adds its own keys to `_shared_status`. Each `_autosave` keeps its own checks of whether a moment may be saved and its own flushes, then calls `_write_autosave`.
- The choice of save at startup is still written twice, Gen I `_restore_first_valid` (`emulator.py:293`) and Gen II `_prepare_start` (`gen2/emulator.py:335`). Gen I catches every error, boots a fresh machine after each failed load and groups the reasons for the Library. Gen II catches only load errors and keeps its machine. With no save it syncs the clock, and then it starts the League rewards, clears a stale trade hold and pauses for an exchange. Sharing the loop would need a hook for each difference, more lines than the loop itself. Gen II pushes without tags (`PUSH_TAGS`), and only the Gen I stall entry names the saved moment (`STALL_NOTE`).
- `_run` and `_unstick` stay written once per generation, and the emulator merge stops here.
- Only 29 lines of `_run` (87 in Gen I, 67 in Gen II) and 25 of `_unstick` (68 and 87) are the same. A shared version of each would need about five hooks to save 10 to 20 lines.
- The application boots and loads without the adapter, for the reasons under [Hosts](#hosts). Moving that work into the adapter would grow it by more than it takes out of the emulators. The Gen II emulator imports `SCREEN_FRAMES`, `cartridge_game_data`, `new_history` and `write_options` from its adapter module (`gen2/emulator.py:32`). The Gen I emulator imports `SNAPSHOT_EVERY` and does not use it (`emulator.py:37`).
- Two tools keep a fallback import of a module this tree no longer has, and both still need it. `tools/benchmark_decisions.py:283` (`pokesim.headless`) runs the headless loop of the source root it is given, and releases up to v0.6.2 ship that module. `tools/quality_hunt_watch.py:78` (`pokesim.gen2.headless`) reads an installed application, which can be such a release.

## Ownership

| Area | Owner | Boundary |
| --- | --- | --- |
| Shared game decoding | `pokecore.gen1`, `pokecore.rom`, `pokecore.gen1_ui`, `pokecore.storage` | Owns ROM identities, WRAM constants, text and numeric decoding, party and bag reads, cached screen decoding, and immutable storage records. PokeSim wraps these in its application types. See [Shared game core](shared-core.md). |
| Library ownership | `pokesim/app/manager.py`, `pokesim/app/supervisor.py` | Owns the library and supervises independent adventure workers. |
| Runtime ownership | `pokesim/runtime/simulation.py`, `pokesim/runtime/legacy.py` | Opens storage and emulator, retains directory locks through shutdown, and reports final-save errors. Legacy mode keeps its separate owner. |
| Shopping controller | `pokesim/policies/shopping.py` | Owns buying, selling, and restocking state. Returns menu decisions and supply plans from explicit snapshot, goal, and project inputs. |
| Storage controller | `pokesim/policies/storage.py` | Owns PC operation, reserve destination, and pending release confirmation. Rechecks protection and slot identity before release. |
| Generation II runtime | `pokesim/gen2/emulator.py`, `pokesim/gen2/policy/`, `pokecore.gen2` | Runs Gold, Silver and Crystal adventures with their own policy, Cable Club and Time Capsule adapters. |
| Checkpoint files | `pokesim/checkpoints.py` | Owns file publication, checksums, manifests, lookup, and autosave retention. Can be used without SQLite or an emulator. |
| HTTP endpoints | `pokesim/web/app.py` | Validates requests, applies viewer restrictions, and connects runtime services to responses. |
| Journal detail presentation | `pokesim/web/event_page.py`, `pokesim/web/static/event.js` | Renders escaped event data independently of routing. The browser requests rewinds and displays rejected requests without navigating away. HTTP routes retain access checks. |
| Desktop lifecycle | `pokesim/desktop.py`, `pokesim/desktop_setup.py`, `pokesim/platform_io.py` | Opens the Adventure Library locally. Retains explicit legacy setup and platform support helpers. |
| Trade preferences and presentation | `pokesim/trade/preferences.py`, `pokesim/web/trading.py` | Defines partner eligibility and shapes broker results for the local game UI. |
| Atom presentation | `pokesim/web/feed.py` | Renders event dictionaries without reading configuration, querying storage, or creating an HTTP app. Uses XML serialization and separately escapes embedded HTML. |
| Pokédex reference | `pokesim/web/pokedex.py` | Assembles Pokédex entries from the generated tables and reshapes one snapshot dictionary for the Pokédex page. Reads no configuration, storage, or emulator state, and creates no HTTP app. |
| Policy orchestration | `pokesim/policies/strategic.py` | Coordinates observed screens, goals, navigation, collection, and action confirmation. |
| Domain decisions | Other modules in `pokesim/policies/` | Own battle scoring, routes, progression, team preparation, naming, puzzles, and collection planning. |
