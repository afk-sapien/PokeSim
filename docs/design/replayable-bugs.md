# Replayable bugs

Status: approved on 2026-11-10 with the rulings in section 7. Nothing here is built yet. It was read from main at `63c8427e`. It is phase 1 of the architecture plan of 2026-11-09. It fits [Goal system v2](goal-system.md): game time is PlayClock frames, and v2 PR 6 later builds one supervision ladder on the frame clocks this note puts in place.

A bug is replayable when the same start checkpoint, the same seed and the same outside inputs give the same action log, frame for frame. That must hold in a test and in production, for Gen I and Gen II. Today it holds in neither production loop. A stall cannot be run again, so each bug costs hours of fresh play. 57 stall PRs shipped a test and only 1 shipped a scenario. The live soak found 10 problems when it compared a build with the same build.

## 1. What already holds

The headless path is close. Production is not.

1. pyboy-rs is deterministic for one version. The pyboy session proves it with a 200,000 frame two-process test. Phase 1 only depends on that test (section 4.7).
2. The Gen I policy saves and restores its random generator (section 2).
3. Gen II guards already count frames (`gen2/emulator.py:1067-1090`). Gen II picks a reload save by manifest frame (`reload_target`, `gen2/emulator.py:185`).
4. The Gen II cartridge clock follows game time (`_sync_clock`, `gen2/emulator.py:341`). The host clock is read only for a save with no stored reading.
5. Headless runs pass no clock to the policy (`headless.py:116`). Scenarios seed their runs (`scenarios.py:561`, `:569`). Gate rungs reseed the policy and the game's random bytes at every goal start (`GoalSeeds`, `tools/replay_audit.py:135`).

## 2. Is the random generator restored on a reload?

The Gen I planner review asked whether `load_state_dict` restores `policy.rng`. It does for Gen I. It does not for Gen II.

### Gen I: restored

1. `StrategicPolicy.state_dict` saves `"rng": self.rng.getstate()` (`strategic.py:403-411`).
2. `load_state_dict` puts it back at `strategic.py:436-437`, before `on_restore`. Both a reload (`emulator.py:410`) and a boot (`emulator.py:117`) call it.
3. `NamingController` saves and restores its own generator (`policies/naming.py:19-32`).
4. Adventure choices (fossil, Eevee, Dojo) come from `random.Random(f'{seed}:adventure-choices')` and are kept in the policy and collection state. With no seed they come from `random.Random()` (`strategic.py:241`), but are kept once drawn.

So a Gen I reload replays the same policy draws. Two things stop a reload from replaying exactly: the `secrets.randbelow(180)` idle after it (`emulator.py:924`), and guards that fire on wall time.

### Gen II: not saved

1. `gen2/policy.py` `state_dict` (`:149`) and `load_state_dict` (`:158`) leave the generator out. It is used only for the starter (`:75`) and around a collection dry run that saves and restores it (`gen2/collection.py:943-961`). So the loss changes little today.
2. The Gen II naming generator (`gen2/naming.py:28`) is never saved. Its `state_dict` keeps only target, subject and used. A name chosen after a restart (`:61`) differs from the one chosen before.
3. Rescue buttons use `random.Random(self.recoveries)` (`gen2/policy.py:205`). That is deterministic.

### Production has no seed

`config.SEED` is `None` unless set (`config.py:33`). Both policies then seed from OS entropy on first boot. The Gen I state carries the generator after the first checkpoint, so a replay from a checkpoint already sees the same Gen I draws. A replay from a new game does not.

## 3. Inventory

Each row reaches a bot decision. Section 3.4 lists the clock reads that stay, because no decision reads them.

### 3.1 Gen I emulator (`pokesim/emulator.py`)

| Where | What it decides now | Replaced by |
|---|---|---|
| `:125`, `:456`, `:717-729` | `stuck_since`, `invalid_since` and `battle_since` start on `time.time()` | `stuck_frame`, `invalid_frame` and `battle_frame`, as Gen II has |
| `:907` | Reload target is the newest file with `st_mtime < since - 30` | `reload_target` by manifest frame, moved from `gen2/emulator.py:185` to `runtime/reload.py` for both |
| `:924` | `self._tick(1 + secrets.randbelow(180))` after a reload | The reload stream (section 4.1) |
| `:941-943` | No guard for 60 s after a reload | 3,600 frames, as Gen II's `last_reload_frame` check |
| `:946-953` | Invalid state grace of 5 s, or `60 / speed` s in a Pokémon Center | 300 frames, or 3,600 frames in a Center. Speed drops out |
| `:955` | Stuck reload after `STUCK_RELOAD_SECONDS` (600) of wall time | 36,000 frames, as Gen II at `gen2/emulator.py:1067` |
| `:965` | Battle timeout after `BATTLE_TIMEOUT_SECONDS` (900) of wall time | 54,000 frames, as Gen II at `:1076` |
| `:821` | Autosave pauses once a battle is 300 s old | 18,000 frames |
| `:1247`, `:1310-1313` | Autosave every 60 s of wall time | Every 3,600 frames |
| `:1276` | `PolicyContext(snap, time.time() - self.stuck_since, time.time(), ...)` | `PolicyContext(snap, clock, mem, sp)`, where `clock` is PlayClock frames |
| `:330`, `:644`, `:758` | StallWatch gets `time.time()` with each progress and check | The game-minute clock decides. The real clock only paces the alert (section 4.8) |

### 3.2 Gen II emulator (`pokesim/gen2/emulator.py`)

| Where | What it decides now | Replaced by |
|---|---|---|
| `:1022` | `self._tick(1 + secrets.randbelow(180))` after a reload | The reload stream |
| `:1231`, `:1283-1285` | Autosave every 60 s of `time.monotonic()` | Every 3,600 frames |
| `:1097` | `self.stall.check(self.frame, time.time())` | As Gen I |
| `:264`, `:707`, `:818`, `:908`, `:916`, `:1048`, `:1057` | `stuck_ts` is written and never read | Deleted |
| `:354` | `host_elapsed` sets the cartridge clock when a save has no reading | Stays. The reading goes in the trace header |

### 3.3 Shared code

| Where | What it decides now | Replaced by |
|---|---|---|
| `policies/collection.py:539-544` | A partner's trade demand lasts 180 s of `time.monotonic()`. It feeds the choice key at `:1036` and storage at `policies/storage.py:63` | 10,800 PlayClock frames. The request is a logged input |
| `policies/smart_random.py:279`, `policies/guided_random.py:38` | `ctx.stuck_seconds > 90` and `> 60` | Their own last-moved frame, read against `ctx.clock` |
| `runtime/preparation.py:93`, `:135`, `:277` | A 1,800 s wall deadline beside the frame budget | Deleted. `max_frames` stays |
| `gen2/preparation.py:80`, `:177` | A 1,800 s wall deadline beside 108,000 frames | Deleted. The frame budget stays |
| `runtime/participant.py:663` | A finished trade sets Gen I `stuck_since` to wall time | `stuck_frame` |
| `stalls.py:147` | LoopGuard scans the journal every 30 real seconds. Its answer stops gifts and reloads | Every 1,800 frames |
| `headless.py:92`, `gen2/headless.py:107` | `secrets.randbelow(180)` when the run has no `rng` | The reload stream. The fallback goes |
| `config.py:33` | `SEED = None` seeds both policies from OS entropy | The adventure seed (section 4.1) |
| `policies/strategic.py:241` | `random.Random()` for adventure choices without a seed | Always the adventure-choices stream |
| `gen2/naming.py:28` | An unsaved naming generator | `stream(seed, 'name', subject)`, which needs no saved state |
| `gen2/policy.py:74` | A policy generator left out of `state_dict` | Saved and restored as in Gen I |
| `runtime/reward_delivery.py:49`, `:108`, `gen2/rewards.py:55`, `:57` | Mew event and return seeds from `uuid.uuid4()`. `gift_slot` turns the seed into the gift's bytes | `stream(seed, kind, championship count)` |
| `rewards.py:94`, `fair_dvs.py:37` | Ledger seed and fair DV key from `secrets`, kept once | Kept. Both go in the trace header. New adventures derive them from the adventure seed |

### 3.4 Clock reads that stay

1. Pacing and streaming: `emulator.py:582-610`, `gen2/emulator.py:492` and `:1112-1135`.
2. Liveness, the one wall check: `last_activity` (`emulator.py:121`, `:1326`, `gen2/emulator.py:245`, `:1302`). The app supervisor reads it to catch a hung process. That code belongs to the pokesim-app session.
3. Timestamps for status and the journal: `progress_events.py:84`, `goal_time.py:50` and `:86`, `last_achievement` (`emulator.py:751`, `gen2/emulator.py:1316`), and the statistics, shiny and tracking rows.
4. Flush throttles: `gen2/steps.py:27` and `legendary_returns.py:66`. The counts live in memory. Only the write to disk waits.
5. Cable session deadlines in `gen2/manual_session.py:246-262`. They time out a partner process. The trade result they produce is a logged input.
6. Folder and row ids: `runtime/reward_delivery.py:112`, `runtime/tm_purchase.py:67`, `gen2/rewards.py:85`, `gen2/celebi.py:43`, `checkpoints.py:225`.

## 4. Design

### 4.1 Clock and seeds

Game time is frames. Guards count the emulator frame, which a reload rewinds together with the saved timers, as Gen II does today. Anything that must never rewind counts PlayClock frames, whose restore keeps the larger count (`play_clock.py`). That covers the reload stream and trade demand.

A new `pokesim/seeds.py` holds two functions.

1. `adventure_seed(store)` creates a seed once and keeps it in kv, the same way `fair_dvs.secret` keeps its key.
2. `stream(seed, *labels)` returns a `random.Random` seeded from the SHA-256 of the seed and the labels, as `GoalSeeds.seed` does.

The streams are policy, adventure-choices, reload (with the PlayClock frame), name (with the subject) and gift (with the kind and count). A reload still idles 1 to 180 frames to move the game's random numbers along. The number now comes from `stream(seed, 'reload', play_clock_frames)`. Two reloads of one save get different idles, and a replay gets the same ones.

`config.SEED` stays as a test override for the adventure seed. An existing adventure gets its seed on the first boot after the change. Its Gen I generator state is already in its checkpoints.

### 4.2 One loop

`pokesim/runtime/game_loop.py` adds `GameLoop`. One step reads the snapshot, asks the decider, runs the action (press, hold, release, gap), writes W_OPTIONS, runs guards every 60 frames, autosaves every 3,600 frames and writes the trace. The decider is the only part per generation. Gen I builds a `PolicyContext`. Gen II calls `step(snapshot, mem, sp)`. Phase 3 widens the decider into the full GameAdapter.

Production `_run` keeps commands, pause, manual mode, pacing and frame publishing. `HeadlessRun` keeps setup and nothing else. Both call the same step, so a test and production play the same frames.

Where the two loops differ in planner behaviour, Gen I wins. Where they differ in clocks, frames win, by the lead's ruling. Gen II already counts frames, so its guard cadence of 60 frames becomes the shared one. The two guard ladders stay separate until v2 PR 6 merges them.

### 4.3 The trace

`pokecore.trace` lives in `packages/pokecore` after the pokecore move. It uses only the standard library and imports nothing else from pokecore, so the bisect shim can load it into an old commit (section 4.6). It is modelled on PokeBench `session.py:388-406`.

A trace is a chain of segments. A segment starts at an autosave or a load and ends at the next one. It is written as `trace/<checkpoint>.jsonl.gz` beside its checkpoint and is pruned with it, so any kept autosave is a replay start.

The first line is the header:

1. Format, ROM SHA-1, start state SHA-256, emulator frame and PlayClock frames.
2. pyboy-rs version, pokecore version, PokeSim commit and app version.
3. Adventure seed, fair DV key, ledger seed and goal reseed settings.
4. The Gen II cartridge clock reading.
5. The kv values the policy reads, such as `trade_hold`, the reward ledger, Mew returns and pins. A test fails when `policy.step` reads a kv key that is not on this list.

Each later line is one record with an index, a frame, a kind and a hash.

| Kind | Fields | When |
|---|---|---|
| `press`, `release` | button | Every button change, the bot's or the owner's |
| `tick` | frames | Every hold and gap |
| `write` | address, value | W_OPTIONS, nickname repair and goal reseed bytes |
| `decide` | goal key, map, x, y, work RAM digest | Every policy step |
| `input` | source, payload | Section 4.5 |
| `load` | state SHA-256, reason | A reload, a trade result or a gift |
| `check` | full state SHA-256 | Every 3,600 frames |

Each hash is SHA-256 of the previous hash and the record without its hash. The first previous hash is the header's. A `decide` record comes every 15 frames or so, so a game hour holds about 14,000 records. The PR measures the size.

### 4.4 The verifier

`pokecore.trace` ships the verifier with two modes.

1. `verify` feeds the log back with no policy. It checks state, ROM and emulator provenance like PokeBench `load_engine` (`session.py:63-87`). It releases every button before the first tick (`session.py:46-60`). Then it applies each press, tick, write, load and input, and fails on the first `decide` or `check` whose digest differs (`session.py:503-505`). A pass proves the log is complete and the emulator deterministic.
2. `redecide` runs a policy. It loads the same state and policy state, feeds only the `input` records at their frames and lets the policy choose. The first action that differs from the log is the divergence. Bisect runs this mode against another commit.

The exit code is 0 for the same run, 1 for a behaviour difference and 2 for a harness failure, such as a missing ROM or a provenance mismatch. A ladder run once failed its first attempt at setup and then passed, so setup failures must never look like behaviour.

### 4.5 Outside inputs

Anything the policy does not decide from the cartridge is an `input` record. Inputs from other threads queue and apply at the next step boundary, so each one has a frame.

1. Owner commands: pins, the Next activity picker, pause and manual play. A manual button is a press with source `manual`. A pause runs no frames.
2. The external director from the v2 addendum. Its choice is logged with goal kind and parameters, and `redecide` hands the policy the same choice at the same frame.
3. Trade demand from a partner (`runtime/participant.py:455`). Today it sets `collection.set_demand` straight from the HTTP thread. It moves onto the command queue.
4. Trade results, League gifts and Mew gifts. Each is a `load` with the new state kept beside the segment.
5. The Gen II clock reading from `_sync_clock`, and `Stop.real_seconds` when it fires (goal system section 3).

### 4.6 Recording an old commit

`171176e` has no trace and no loop, so the bisect tool records a commit from outside.

1. It makes a worktree per commit in a cache folder, with an environment from that commit's own `uv.lock`, cached by the lock's hash.
2. A shim loads `trace.py` from the current checkout. It wraps `HeadlessRun.__init__` in both generations to swap `run.pb` for a recording proxy, and wraps `policy.step` to write `decide` records.
3. It then runs the commit's own rung runner (`tools/stage_ladder.py`) through `runpy`.
4. The proxy passes reads straight through and logs presses, releases, ticks and writes. Each `GoalSeeds` reseed is logged as an input with its digest.

`HeadlessRun` has `pb`, `step` and `reload` at both ends of the suspect range. A commit where the shim cannot attach is a harness failure, never a bad commit.

### 4.7 Determinism tests

1. pyboy-rs: 200,000 frames in two processes give the same state hash. This is the pyboy session's job, with one pyboy-rs version across the repos. Phase 1 depends on it.
2. `tests/test_determinism.py`: the same checkpoint and seed, two headless runs of 20,000 frames each, for Gen I and Gen II, give the same trace head hash. One case reloads once. One case receives a trade demand. It is game-backed, so it runs in the local preflight.
3. The bisect tool records each end twice first. Both recordings must end on the same hash before anything else runs.

### 4.8 Automatic stall capture

Every stall keeps a capture. The triggers are Gen I `_check_stall` (`emulator.py:972`), Gen II `_check_stall` (`gen2/emulator.py:1092`), both `_give_up` paths (`emulator.py:862`, `gen2/emulator.py:927`), a LoopGuard trip and a gate `GateWatch` stall (`tools/stage_ladder.py:493`).

A capture holds the save from before the stall, the trace segments from that save to the notice, the noticed state and the report. It extends `write_stall_bundle` (`checkpoints.py:242`). Gen II gets bundles here, which takes that item off v2 PR 6.

The game-minute clock triggers a capture. The real-minute half of StallWatch (`stalls.py:21-24`) keeps pacing the alert and its repeat, so Max pace does not flood the journal, but a capture never waits for it.

`python -m pokesim.replay capture BUNDLE` turns a capture into a scenario. The state stays in the private scenario folder that `tools/stuck_scenarios.py` uses today. A tracked `scenarios/index.toml` row holds the name, ROM SHA-1, state SHA-256, frame window, expectation and the issue or PR. A scenario for an open stall is expected to fail. The fix PR flips it, and the preflight runs every row it has a save for. That is how a fixed stall becomes a test.

### 4.9 Left for v2 PR 6

Phase 1 converts clocks in place and adds the trace. It does not merge the two guard ladders, add the Rewind event, keep stand-downs across a reload or build the liveness check. Those stay in v2 PR 6. The liveness check in the supervisor and the watchdog is pokesim-app's to coordinate. After PR 5 below, the status field `stuck_seconds` that the watchdog reads (`app/watchdog.py:408`) counts game seconds, so pokesim-app needs to know before it lands.

## 5. The three test cases

All three come from the gate run listed in `tools/ladder/regressions-suspected-20261109.md`. The note does not guess at causes. The lead ruled that the 26 rungs wait for this tooling.

### 5.1 Steps for every case

```
python -m pokesim.replay record --rung silver/badges_6 --at 171176e --twice
python -m pokesim.replay record --rung silver/badges_6 --at main --twice
python -m pokesim.replay diverge 171176e main --rung silver/badges_6
python -m pokesim.replay bisect --rung silver/badges_6 --good 171176e --bad main --suspects 344,346,353,354,357,358,359,373,378,379,382,383,389,392
```

1. Record the rung at `171176e` and at main, twice each. Both pairs must match (section 4.7).
2. Record `171176e` once more with main's pyboy-rs. #398 moved pyboy-rs from 0.1.4 to 0.1.5 after the baseline, and the gate's main numbers ran on `1be5e711`, which has it. If the emulator alone moves the rung, the report says so and the bisect holds pyboy-rs at 0.1.5 for every commit.
3. Find the first frame where the action logs diverge, and the first frame where the goal keys diverge. A small early action change can be harmless, so both are reported.
4. Bisect over the suspects in merge order, testing main as it stood right after each one merged. Then test the parent of the first bad commit. If that parent is already bad, bisect the full first-parent range of 139 commits from `171176e` to `63c8427e`, about 8 runs.
5. Diverge the first bad commit against its parent.

A commit is bad when its waste is more than 2.0 points over the baseline (`GATE_WASTE_POINTS`, `tools/stage_ladder.py:89`) or when it has a stall the baseline lacks.

#375 is not a confound for gate rungs. The gate always passes seed 7 (`tools/stage_ladder.py:539`, and `:536` at `171176e`). With seed 7, `GoalSeeds` keeps the key it had before #375 (`tools/replay_audit.py:145-148`). So both ends meet the same goal rolls. The reseed input records prove it on every run.

Outputs go to the private ladder folder, since ladders hold private game data. The report is JSON with a short Markdown summary beside it.

All three cases are Gen II. The tool is done only when it has also run one Gen I rung, `blue/badges_2`, at both ends with a passing self check. That rung is reported, not investigated.

### 5.2 crystal/post_game, 0.0% to 32.1%, no stall

A commit is bad on waste alone.

The report adds the waste split by category from `run.json` at both ends, and the first 3,600-frame window whose waste passes the baseline's.

Done when all of these hold:

1. Both ends pass the self check.
2. The waste recorded at each end matches the gate's number to 0.1 points, or the report says why not.
3. The first bad commit is named, with its waste and its parent's.
4. The first action divergence and the first goal divergence between them are given with frame, map, position and both goal keys.
5. A scenario from the last `check` before the waste window is in `scenarios/index.toml`, expected to fail.

### 5.3 silver/badges_6, 1.3% to 25.9%, new stall

The stall is a retry loop: `route:red_gyarados:LAKE_OF_RAGE:18,23` stood down 4 times in a row. Two predicates run as two bisects that share runs: the stall on this key, and the waste. They may name different commits.

The report adds the frame of each stand-down, the loop period in frames, and the first `decide` record of the first round of the loop.

Done when all of these hold:

1. Steps 1 to 4 of section 5.2 hold for both predicates.
2. `replay capture` has turned the `GateWatch` bundle into a scenario. It expects no stand-down of this key to repeat 4 times in 108,000 frames.
3. That scenario fails on main and passes at the parent of the first bad commit. This runs the path from stall to test once from start to finish.

### 5.4 gold/new_game, 5.7% to 23.7%

A commit is bad on waste alone. The baseline is not zero, so the 2.0 point margin is over 5.7%.

A new game picks the starter (`gen2/policy.py:75`) and the first names. The report checks that both ends pick the same starter and names before the first divergence. It also gives the cartridge clock reading at the start and at the first divergence at both ends.

Done when steps 1 to 5 of section 5.2 hold.

## 6. PR plan

The trace and the bisect tool go first. The gate rungs already run headless with seeds and no reload watchdog (`tools/replay_audit.py:39`), so they need no production change to be replayable. Putting these first unblocks the 26 rungs after about 12 agent-hours. The production clock work follows.

Each PR deletes the old call sites its new definition replaces, in the same PR.

| # | PR | Adds | Deletes in the same PR | Agent hours |
|---|---|---|---|---|
| 1 | Trace and verifier | `pokecore.trace`: header, records, hash chain, `verify` and `redecide`, provenance checks, exit codes. Tests for the chain, a tampered record and both modes | pokecore's record and replay wrappers (`emulator.py:407-445`), which PokeSim never calls, after a check that PokeBench does not call them either | 7 |
| 2 | Replay diverge and bisect | `python -m pokesim.replay` with `record`, `diverge` and `bisect`, the old-commit shim, the environment cache and the self check. Then the three cases run | `tools/stage_ladder.py:533` importing `tools.replay_audit`, and `tools/live_soak.py:1135` importing `stage_ladder.compare`. The rung runner and `compare` move into `pokesim/replay/` | 5 |
| 3 | Seeds | `pokesim/seeds.py`, the adventure seed and the streams. Gen II policy generator saved and restored | `secrets.randbelow` at `emulator.py:924`, `gen2/emulator.py:1022`, `headless.py:92` and `gen2/headless.py:107`. `random.Random()` at `strategic.py:241`. The `uuid4` gift seeds at `runtime/reward_delivery.py:49`, `:108` and `gen2/rewards.py:55`, `:57`. The naming generator at `gen2/naming.py:28` | 3 |
| 4 | Wall time leaves the policy | `PolicyContext.clock` in PlayClock frames. Trade demand on frames, through the command queue | The `stuck_seconds` and `real_time` fields (`policies/base.py:26-27`) and their callers: `emulator.py:1276`, `headless.py:116`, `benchmark.py:116`, 7 call sites in 6 tools and 69 test constructors. The monotonic window at `policies/collection.py:539-544`. The wall reads at `smart_random.py:279` and `guided_random.py:38` | 3 |
| 5 | Supervision on frames | Gen I guards, battle timeout, invalid grace and autosave pause on frames. Autosave every 3,600 frames in both loops. `runtime/reload.py` with `reload_target` | The rows of section 3.1 except `:924` (PR 3) and `:1276` (PR 4), with the mtime pick at `emulator.py:907`. The write-only `stuck_ts` in Gen II. The wall deadlines in both preparation modules. The LoopGuard real-second scan at `stalls.py:147`. `participant.py:663` | 5 |
| 6 | One loop | `runtime/game_loop.py` with the per-generation decider. Production and headless call it | The action code in `emulator.py:1292-1309`, `gen2/emulator.py:1268-1279`, `headless.py:114-125`, `gen2/headless.py:133-142` and `benchmark.py:116-117`. The tool loops in `play_gen2`, `playthrough`, `validate_progress`, `validate_legendary_recovery`, `verify_gen2_postgame`, `verify_gen2_trading` and `benchmark_decisions` move onto `HeadlessRun` | 6 |
| 7 | Trace in production | Both loops write segments. Outside inputs are logged. `tests/test_determinism.py` | The five manifest builders (`emulator.py:800`, `gen2/emulator.py:540`, `headless.py:100` and `:107`, `gen2/headless.py:117`) become one shared builder that carries the header fields | 4 |
| 8 | Automatic stall capture | Captures at every trigger in section 4.8, Gen II bundles, `replay capture` and `scenarios/index.toml` | `tools/stuck_scenarios.py add` (`:61-88`). The bundle writer in `tools/find_stalls.py`, which moves onto the shared capture | 5 |

That is 38 agent-hours, plus the pyboy session's 5 for the determinism test and one pyboy-rs version. The plan has 40 for phase 1. The extra 3 pay for the old-commit shim. The three cases then need about 1 agent-hour to start and read, plus machine time of 6 to 10 rung runs each. Each run plays 108,000 frames.

PRs 3 to 5 can each ship alone. PR 6 needs 3 to 5. PR 7 needs 1 and 6. PR 8 needs 7.

## 7. Decided

The lead ruled on the open questions on 2026-11-10.

1. pyboy-rs: the bisect holds pyboy-rs at 0.1.5 for every commit. It reports 0.1.4 against 0.1.5 once, as its own result.
2. Autosave: it stays at 3,600 frames with 20 kept saves. That covers 20 game minutes, and the stuck reload looks back only 10. The stall capture keeps its own save from before the stall. PR 5 measures the save cost at Max pace and reports back only when it passes 2% of loop time.
3. Mew gift seeds: they come from the adventure seed with the kind and the championship count. A gift claimed again after a rollback gets the same DVs, because a rollback must not be a reroll.
4. Trace in production: the full trace is kept and pruned with its autosave. PR 7 reports the measured bytes per game hour, and reports back only when one adventure's kept traces pass 50 MB.
5. Order: the trace and the bisect tool come first, then the clock work. PR 1 of this plan starts after the pokecore move has merged, since it lives in `packages/pokecore`. The three cases run as soon as PR 2 lands.
