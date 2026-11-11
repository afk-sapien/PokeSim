# Adventure state store

Status: approved by the lead on 2026-11-10, with the rulings in section 8. Nothing here is built yet. It was read from main at `d37693fa`. It is phase 4 item 2 of the architecture plan of 2026-11-09, budgeted at 16 to 20 agent-hours. It shares files with phase 1, [Replayable bugs](replayable-bugs.md). Section 6 lists them and says how each slice stays out of phase 1's way.

An adventure's state is its checkpoints plus `pokesim.sqlite`. This note gives that database three things it lacks.

1. **One owner.** Only `pokesim/store.py` and a new `pokesim/state/` package touch `pokesim.sqlite`. Today 31 modules use `store.db` directly, 210 times, and 14 places in 8 modules open the file themselves.
2. **A schema version.** `PRAGMA user_version` with ordered migrations in one place. Today the adventure database has none. 12 modules create tables, some on first use, and migrations probe `PRAGMA table_info` (`store.py:110-129`).
3. **Atomic restart resets.** An owner restart resets everything in one transaction, or nothing. Today each generation's restart makes a dozen or more separate commits (`emulator.py:1204-1243`, `gen2/emulator.py:1183-1228`), with autosaves unlinked one by one in between. A crash part way leaves a game that is half old and half new.

## 1. What already holds

1. Checkpoint writing is atomic, synced and checked by SHA-256 (`checkpoints.py:187-205`). The plan keeps it as is, and so does this note. The checkpoint format stays at 1.
2. The registry already versions `app.sqlite` and refuses a newer one (`app/registry.py:60-66`). It copies the old file before it migrates (`_keep_before_migration`). The adventure database copies that design.
3. Most ledgers already guard against counting twice after a reload: receipts in `catches.py`, `activity_ledger.py` and `trade_statistics.py`, a `through` cursor in `adventure_counters.py`, and keep-the-larger in `play_clock.py`. They stay. The registry in section 3.3 only names them.
4. kv keys carry a payload version in their name (`-v1`, `-v2`). That stays. The database version covers tables and columns, not payloads.

## 2. Where adventure state lives today

| Where | What | Written at |
|---|---|---|
| Checkpoint manifest | `policy_state`, `run_memory`, `frame`, `play_clock`, `gen2_history`, `legendary_recovery`, `trade_id`, `reward_id` | `emulator.py:800`, `gen2/emulator.py:540`, `headless.py:100` and `:107`, `gen2/headless.py:117` |
| kv copies of manifest fields | `policy_state`, `run_memory`, `gen2-history`, `play_clock` | `emulator.py:418`, `:732`, `:814`, `:845`, `gen2/emulator.py:582-584` |
| kv ledgers | About 45 keys, such as `league-rewards-v1`, `trade_hold`, `capture-statistics-v1`, `loop-guard-reloads-v1` | Their own modules, through `store.set` or raw SQL |
| Tables | `events` and `kv` (`store.py:35-52`), then `progress`, `statistics_history`, `activity_counts`, `activity_receipts`, `pokemon_trade_receipts`, `progress_events`, `encounter_counts`, `stall_truth`, `capture_receipts`, the shiny tables, `completed_trades`, `completed_events` | `Store.__init__` (`store.py:96-108`) and 12 modules, listed under S1 |

Boot reads the kv copies first (`emulator.py:104`, `:110`, `:117`, `gen2/emulator.py:222`, `:268`). Then the newest autosave replaces all of them, except `play_clock`, whose restore keeps the larger count, and the announced playtime milestones inside `run_memory` (`emulator.py:411-417`).

These open `pokesim.sqlite` outside the worker's `Store`:

| Where | Mode | Why |
|---|---|---|
| `app/coordinator.py:289`, `app/progress_sweep.py:92`, `app/legacy_import.py:31`, `app/migration.py:34` | Read | `trade_hold`, progress, import checks |
| `app/migration.py:50` | Write | Integrity check of the staged copy |
| `stall_truth.py:124` | Write | A lifecycle row from the app supervisor (`app/supervisor.py:495`) |
| `trade/service.py:63`, `trade/pair.py:70`, `:79`, `:133`, `trade/event.py:53`, `:71`, `:81`, `:147` | Read and write | The legacy two-container pair trade (`deploy/compose.trading.yaml`) |

## 3. Design

### 3.1 One owner

A new `pokesim/state/` package holds `schema.py` (the version, the migrations and `connect`), `domains.py` (section 3.3) and one repository module per group of ledgers. The worker still holds one `Store`. It gains the repository methods and `durable()`. Outside the worker, `state.connect(path, read_only=...)` is the one way to open `pokesim.sqlite`, and it checks the version first.

Reads and writes through `store.get` and `store.set` already go through the owner, so they stay. About 50 `trade_hold` reads are of this kind and do not move. What moves is raw SQL on `store.db`.

The last slice adds a test that fails when a module outside `pokesim/state/` and `store.py` uses a store's `db` or opens a `pokesim.sqlite`. That test is `tests/test_state_owner.py`. It covers the package. The modules that own `app.sqlite` and `auth.sqlite` may open those files with sqlite3, and nothing else may.

### 3.2 Schema version

1. Version 1 is today's full shape. Migration 1 runs on a database at version 0. It creates every table the 12 modules create today, runs today's column probes and backfills once, and sets the version. Later migrations are ordered functions, each in its own transaction.
2. A newer version is refused with `Conflict('This adventure was saved by a newer PokeSim')`, as the registry does for `app.sqlite`. Import (`app/migration.py:50`), which backup load also goes through (`app/backup.py:261`), and backup restore (`app/backup.py:169-191`) check the staged copy before it is used. Restore also runs `integrity_check` on each adventure database, which today it runs only on `app.sqlite` (`app/backup.py:185-187`).
3. A migration past version 1 copies `pokesim.sqlite` beside itself first.
4. The read-only store migrates its copy in memory (`store.py:73-82`). A stopped adventure from an older build then reads in the current shape, and its file never changes.
5. `PRAGMA synchronous=FULL` becomes `store.durable()`, one context that sets it for one transaction and then puts it back. The ledgers that move value use it.

### 3.3 State domains

Each kv key, key prefix and table is declared once in `pokesim/state/domains.py`.

```python
Domain('league-rewards-v1', owner='pokesim.rewards', life=RESETS_ON_RESTART, generations=(1, 2), policy_reads=True)
```

The lives are the review's three rewind classes.

| Life | A reload | An owner restart | Kept in |
|---|---|---|---|
| `rewinds` | Goes back with the save | Starts empty | The checkpoint manifest only |
| `resets_on_restart` | Stays | Is reset | kv or a table |
| `survives` | Stays | Stays | kv or a table, with an idempotency key or keep-the-larger |

`policy_reads` marks the keys the policy reads. Phase 1 PR 7 lists exactly those in the trace header (replayable-bugs.md section 4.3 item 5). With the flag there is one list, not two. A second flag replaces `OBSERVATION_READ_KEYS` (`store.py:30-33`), the keys `store.get` may cache.

A test scans `pokesim/` for kv keys: string literals passed to `store.get` and `store.set`, `KEY` constants and `kv WHERE k=` SQL. It fails on a key that is not declared. A new ledger then cannot miss the restart, which is the bug class the review names (app-layer F2).

### 3.4 Atomic owner restart

1. As today, the restart keeps the named before-restart checkpoint. It then flushes the counts held in memory (statistics, steps).
2. `store.restart(generation)` runs one `BEGIN IMMEDIATE` transaction under `durable()`. It resets every `resets_on_restart` domain of that generation, deletes the trade preference rows, writes an empty play clock and sets `restart-pending-v1`.
3. After the commit it drops every autosave through one new `CheckpointStore.drop_autosaves()`, then clears `restart-pending-v1`.
4. A writable `Store` that opens with `restart-pending-v1` set drops the autosaves and clears the key before anything restores. A crash before the commit resumes the old game whole. A crash after it starts the new game whole.
5. The emulator builds its trackers again from the store, as boot does, in place of calling each tracker's `reset`.

The trade and reward barriers are `survives`, as the comment at `emulator.py:1223-1224` already says. Gen II's `_autosave()` before the restart (`gen2/emulator.py:1186`) goes. The next lines delete its checkpoint, and the `_autosave()` at `:1227` overwrites its kv writes. What it keeps is the flush of step and statistics counts, which step 1 does directly. The `_autosave()` at `:1227` stays, since it writes the new game's first save.

### 3.5 The rewinding state lives once

`policy_state`, `gen2-history` and `run_memory` leave kv. Boot and reload read the manifest only. `run_memory` keeps one field across a reload today, the announced playtime milestones. That field becomes its own key, `playtime-milestones-v1`, for Gen I. It is `resets_on_restart`, not `survives`: the hours are the cartridge's play time, which a new game counts again from zero, and today's restart empties them with the rest of `run_memory`. Gen II keeps its milestones in its history, which rewinds as it does today. `play_clock` stays in kv as `resets_on_restart`: a reload keeps the larger count, and a restart writes an empty clock.

A Gen I save with no manifest loads today, and `_load_state_file` skips the manifest steps for it (`emulator.py:392`, `:409`). For that case only, the last kv copy of `policy_state` stays readable. A Gen II manifest from before 2026-10-16 has no `gen2_history`. A rewind to one keeps the current game's history, as today. A boot on one takes the last kv copy of `gen2-history`, which today's boot reads first, so the journal does not announce every map, catch and badge again. A restart drops both copies, and a later migration drops them everywhere.

## 4. What a restart resets: the generations disagree

The proposed rule: a restart starts a new cartridge game. State that a new game would contradict is `resets_on_restart`. State that counts the adventure's whole life is `survives`. Everything not in this table keeps today's behaviour in both generations.

| State | Gen I restart | Gen II restart | Proposed |
|---|---|---|---|
| League partner records (`league-partners-v2`, `gen2-league-partners-v1`) | Keeps | Resets (`gen2/emulator.py:1192-1195`) | Resets. They describe the cartridge's Hall of Fame, which a new game empties |
| Mew walking returns (`mew-returns-v1`, `gen2-mew-returns-v1`) | Keeps | Resets | Resets. A return is earned and redeemed in one game |
| Mythical gift markers (`pokesim-mew-v1`, `gen2-mythical-gift-v1`, `gen2-gs-ball-distribution-v1`) | Keeps | Resets | Resets. The new game holds no gift |
| Loop guard reload counts (`loop-guard-reloads-v1`) | Keeps | Keeps. The new `LoopGuard` (`:1223`) reads them back from kv (`stalls.py:239`) | Resets. The counts are for the old game's places |
| Goal time (`goal-time-v1`) | Keeps | Keeps | Resets. Its shares and stand-downs are the old game's |
| Supervisor ladder counts (`supervisor-ladder-v1`) | Resets | Resets | Resets. A reload keeps them, but a new game starts the ladder from the bottom |

Lifetime tallies stay `survives` in both: `adventure-counters-v1`, `activity-ledger-v1`, `adventure-statistics-v1`, the statistics history and the journal.

## 5. Slices

Each slice deletes the old call sites it replaces, in the same PR. Line numbers are at `d37693fa`.

| # | Slice | Adds | Deletes in the same PR | Agent hours |
|---|---|---|---|---|
| S1 | Schema version | `state/schema.py` with migration 1 and `connect`. Version checks on import, restore and load. Tests: a version 0 copy migrates, a newer one is refused, the read-only store migrates in memory | `SCHEMA` (`store.py:35-52`), the table setup in `Store.__init__` (`:94-108`), the column probes (`:110-129`). The table creation at `activity_ledger.py:64` and `:67`, `catches.py:125`, `gen2/tracking.py:53`, `progress.py:12`, `progress_events.py:15` and `:29`, `shiny.py:47`, `stall_truth.py:26`, `statistics.py:16`, `trade_statistics.py:112`, `trade/pair.py:138`, `trade/event.py:148`. The 14 raw opens in section 2 | 3 |
| S2 | State domains | `state/domains.py` declaring every key and table with today's behaviour, and the undeclared-key test. No behaviour change | `OBSERVATION_READ_KEYS` (`store.py:30-33`) and `PENDING_REWARD` (`:28`), which become domain fields | 2 |
| S3 | Atomic owner restart | `store.restart`, `restart-pending-v1`, `drop_autosaves`, and the lead's ruling on section 4. Tests: a failure at each step leaves the old game whole or the new game whole, in both generations | Gen I, `emulator.py`: the catch reset `:1211-1214`, the unlink loop `:1215-1217`, the shiny reset `:1218-1219`, the store writes at `:1225-1237` (trade preferences, pending reward, milestones, League ledger, records, play clock, run memory, policy state). Gen II, `gen2/emulator.py`: `_autosave` `:1186`, the unlink loop `:1187-1189`, the key loop `:1192-1195`, trade preferences `:1196`, tracker reset `:1198`, records `:1201`, clock key `:1205`. The database half of `reset` in `catches.py:52-57`, `shiny.py:149-153` and `gen2/tracking.py:59-67` | 3 |
| S4 | The rewinding state lives once | `playtime-milestones-v1` as a `resets_on_restart` key (section 3.5). Boot and reload read the manifest only | kv reads at `emulator.py:110`, `:117`, `gen2/emulator.py:222`, `:268`. kv writes at `emulator.py:418`, `:732`, `:845`, `gen2/emulator.py:582`, `:583`. The milestone merge at `emulator.py:411-412`. The raw ledger read at `:414-416` becomes a store call | 2 |
| R1 | Trade and reward ledgers behind repositories | `state/ledgers.py`. Value-moving writes in `durable()` | 82 raw uses in `runtime/participant.py`, `rewards.py`, `runtime/reward_delivery.py`, `runtime/tm_purchase.py`, `gen2/league.py`, `league_partners.py`, `gen2/celebi.py`, `gen2/rewards.py`, `fair_dvs.py`, `trade_statistics.py`, `mew_returns.py`. The five `synchronous` toggles at `gen2/celebi.py:51`, `gen2/rewards.py:95`, `runtime/participant.py:310`, `runtime/reward_delivery.py:166`, `runtime/tm_purchase.py:78` | 5 |
| R2 | Catches, statistics and records behind repositories | `state/tracking.py` | 73 raw uses in `gen2/tracking.py`, `statistics.py`, `catches.py`, `shiny.py`, `gen2/statistics.py`, `milestones.py`, `adventure_counters.py`, `catch_rates.py`, `adventure_records.py`, `money_flow.py` | 3 |
| R3 | Journal, progress and guards behind repositories, and the owner test | `state/journal.py`. The test from section 3.1 | 54 raw uses in `activity_ledger.py`, `league_history.py`, `gen2/activity.py`, `stalls.py`, `progress_events.py`, `stall_truth.py`, `web/app.py`, `goal_time.py`, `gen2/steps.py` | 3 |

That is 21 agent-hours against the plan's 16 to 20. The extra hour is the 14 raw opens in S1, which the review did not count. The raw uses that S3, S4 and R1 to R3 remove add up to the 210 in the introduction.

S1 and S2 can each ship alone. S3 needs S2. S4 needs S2 and phase 1 PR 7. R1 to R3 need S1, and R2 needs S3. R3 lands last, because its test passes only once every raw use is gone.

## 6. Phase 1 overlap, and how the slices stay out of its way

### 6.1 Files shared with phase 1

| File | Phase 1 PR that touches it | State store slice | How they meet |
|---|---|---|---|
| `docs/design/replayable-bugs.md` | All | None | This note does not edit it |
| `pokesim/emulator.py` | 3, 4, 5, 6, 7, 8 | S3 (restart branch), S4 (boot reads, `_load_state_file`, `_autosave`) | S3 changes only the restart branch, which no phase 1 PR names. S4 waits for PR 7 |
| `pokesim/gen2/emulator.py` | 3, 5, 6, 7, 8 | S3, S4 | As above. S3 keeps the policy rebuild at `:1212`, whose seed PR 3 changes |
| `pokesim/checkpoints.py` | 7 (traces pruned with their save), 8 (`write_stall_bundle`) | S3 adds `drop_autosaves` | `drop_autosaves` and `prune_autosaves` share one per-save removal, so PR 7's trace pruning covers both with one change |
| `pokesim/seeds.py` (new) | 3 | S2 | PR 3 declares the adventure seed in `domains.py`, one line, as `survives` |
| `pokesim/stalls.py` | 5 (LoopGuard scan at `:147`) | R3 (`:223`, `:239`), S3 ruling on `loop-guard-reloads-v1` | R3 waits for PR 5 |
| `pokesim/runtime/reward_delivery.py`, `pokesim/gen2/rewards.py` | 3 (gift seeds) | R1 | R1 waits for PR 3 |
| `pokesim/runtime/participant.py` | 4 (trade demand at `:455`), 5 (`:663`) | R1 (`:310` and the ledger SQL) | R1 waits for PR 5 |
| `pokesim/rewards.py`, `pokesim/fair_dvs.py` | 7 (their seeds go in the trace header) | R1 | R1 keeps `fair_dvs.secret` and the ledger seed read with their signatures, so PR 7 is unaffected |
| `pokesim/headless.py`, `pokesim/gen2/headless.py` | 3, 4, 6, 7 | None | The state store never touches them. They write manifests, not kv |
| The trace header's list of kv keys the policy reads | 7 | S2 (`policy_reads`) | Whichever lands second deletes its own list and reads the other |

Phase 1 files the state store never touches: `runtime/game_loop.py` and `runtime/reload.py` (new), `policies/*`, `runtime/preparation.py`, `gen2/preparation.py`, `gen2/policy.py`, `gen2/naming.py`, `config.py`, `benchmark.py`, `pokesim/replay/`, `packages/pokecore`, `scenarios/index.toml` and the replay tools.

### 6.2 Rules for every slice

1. New code goes in `pokesim/state/` and `store.py`. Phase 1 touches neither.
2. Only S3 and S4 edit the two emulator loops. S3 edits only the restart branch. S4 lands after phase 1 PR 7.
3. No slice changes a manifest field, the checkpoint format, `policy.state_dict` or a kv payload. Checkpoints and traces recorded before a slice replay the same after it.
4. A slice that shares a file with an open phase 1 PR waits for that PR, then rebases. It never asks phase 1 to rebase.
5. After S2, the only thing phase 1 owes the store is one `domains.py` line for each new kv key. The undeclared-key test says so on the PR.

## 7. Not in scope

1. What a reload keeps, stand-downs across a reload and persisted reload counts. Those are v2 PR 6. Its new domains, and the PR 5 claims table, get declared in `domains.py`.
2. `app.sqlite` and `adventure.json`. The registry already has its own version.
3. Loading a named checkpoint from before a restart. Today `rewards.initialize` guards the gift ledger after such a load (`emulator.py:428-430`, `gen2/emulator.py:642-645`). Other `resets_on_restart` domains stay reset, as they do today.
4. The scripts in `tools/`. They check, soak and profile copies or live folders, outside any worker. Eight of them open `pokesim.sqlite` with sqlite3 or use a store's `db`: `check_managed_app.py`, `check_managed_cable.py`, `live_soak.py`, `pc_dry_run.py`, `profile_simulation.py`, `quality_hunt_watch.py`, `replay_progress.py` and `sample_live.py`, whose remote script does it on the server. The owner test does not cover them.

## 8. Rulings

The lead approved this note on 2026-11-10 with these rulings.

1. **Section 4.** All five rows reset on restart, as proposed. S3 carries one condition. A test proves that resetting the Mew, mythical gift and GS Ball markers cannot hand out a second gift while the first one survives in the adventure's storage or its collection. If it can, S3 stops and the case goes to the lead before Gen I changes.
2. **Who writes the slices.** pokesim-app writes every slice, including those in the emulators, `pokesim/gen2` and the trackers. Before each PR that touches a file in table 6.1, it tells the pokesim session in one line. Rule 4 of section 6.2 holds: the state store slice waits and rebases, and phase 1 never does.
3. **The legacy pair trade** (`trade/service.py`, `trade/pair.py`, `trade/event.py`, `deploy/compose.trading.yaml`) keeps working through `state.connect`. Retiring it is not part of this work.
4. **Preflight.** A slice that changes behaviour carries the `preflight` commit status before it merges. S3 is one. The others say in their PR whether they change behaviour.
