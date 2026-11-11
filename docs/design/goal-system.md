# Goal system v2

Status: proposal for review. Nothing here is built yet. It was read from main at `171176e` (#342). It builds on [Planner systems](planner-systems.md) and keeps its names: S1 ledger, S2 conditions, S3 arbiter, S4 monitor and S5 stance. It replaces the standalone stall design. There is no separate stall document.

The owner wants a goal tree. Each goal has four parts: what, done when, stop when and priority. Today the planner has tiers, fixed producers and five ways to say "progress". This document turns the tiers into templates, gives every goal the same four parts, and gives every part one owner.

## 1. Band-aid inventory

Each row is a rule that one place decides on its own. The goal system replaces each with one shared mechanism.

### Worth: what to keep, take or let go

| Where (main) | Rule | Missing mechanism |
|---|---|---|
| `rewards.py:114-140` `wasted()` | A League gift is skipped when it would rate as a spare. #334 passes `marks=` to `pc_rated` and `release_rated` instead of the old monkeypatch | One worth call before any acquire |
| `runtime/reward_delivery.py:117`, `gen2/rewards.py:68` | The two callers of `wasted()`, one per generation | The same |
| `gen2/collection.py:840`, `:845`, `:853`, `:859` | `offer('returned')`, `offer('gifts')`, `offer('breed')` and `offer('hatching')` each decide if the result is worth a slot | The same |
| `gen2/breeding.py:97` `pairings` | Breeding chooses pairs by its own rule | PR 4a-2 asks `release.keeps_hatch` for a demanded baby |
| `app/coordinator.py:975` `_benefit`, used at `:620` and `:1121-1122` | Trade benefit, rule one | PR 4a-2 moves it to `trade/worth.py` `gain` |
| `app/coordinator.py:1186` `_would_keep` | Trade keep check | The same |
| `broker/routine.py:12` `benefit` | Trade benefit, rule three | PR 4a-2 moves it to `trade/worth.py` `gain` |
| `broker/inventory.py:130` `spare_entries`, return at `:141`, used at `:178` | Offers spares rated without demand or focus | PR 4a-2 moves it to `trade/worth.py` `spares` and `given`, with demand |
| `gen2/release.py:53` `plan_partners` | Protects only breeding, training and tower identities, never a family | Demand by evolution family |
| `gen2/release.py:88` `release_rated` | Release order for Gen II | One worth call |
| `gen2/release.py:107-122` `keeps_another`, used at `gen2/emulator.py:685-687` | A phantom Entry decides if a return or repeat gift would be the next spare (#336) | The same |
| `runtime/participant.py:415-433` `would_keep` | The trade participant's keep check | The same |
| `policies/team.py:64`, `policies/storage.py:65`, `strategic.py:1359`, `gen2/policy.py:738`, `gen2/ledger.py:190` | Other readers of `pc_rated` or `release_rated` | Read the oracle |

`pcvalue.py` already has the scoring. `Inputs` at `:84` carries demand, focus, wishes and favor. `rate` is at `:144` and `releases` at `:210`. Groups are by dex number and Unown letter, not by family. Nothing passes `focus=`, so the input that should carry the owner's hunt is never set.

### Progress: what counts as moving

| Where (main) | Definition |
|---|---|
| `stalls.py:13` `PROGRESS_EVENTS` | badge, catch, evolve, obtain, champion, item, trainer, level, map |
| `stalls.py:74` `REAL_PROGRESS` | badge, catch, event_return, evolve, hatch, champion, trainer, level, map. Used by LoopGuard |
| `stalls.py:50` `held()`, `:61` `advanced()` | A held count rise or any experience |
| `gen2/journal.py:23` `NOT_PROGRESS` | Everything except seen, faint, blackout, money, playtime and name |
| `emulator.py:677` | Inline tuple: the `PROGRESS_EVENTS` list plus trade |
| `gen2/emulator.py:624` | Any journal type outside `NOT_PROGRESS` sets `last_achievement` |
| `gen2/emulator.py:801` `_note_progress`, score at `:805` | A new high in badges, event flags, owned, areas, experience or League wins |
| `planning/progress.py:43-49` | S4: a held rise is a catch, a held drop is room |
| `app/watchdog.py:407-427` `_quiet` | A fingerprint of last achievement id, owned, badges, Hall of Fame, League wins and areas, over 3600 real seconds (`Limits.no_progress`, `:42`) |

LoopGuard (`stalls.py:93`) reads journal titles with three regexes, `_RECEIVED`, `_RELEASED` and `_RETURNED` at `:82-85`. Its reload counts live only in memory.

Two gaps follow from these lists.

1. Kanto Marathon writes a `marathon` journal row only at start (`policies/marathon.py:147`) and finish (`:158`). Checkpoints write nothing, and `marathon` is in none of the lists. A run that is racing well looks silent to the watchdog.
2. Catches land only in `capture_receipts` (`catches.py:84` `record_receipt`, `gen2/tracking.py:133` and `:154`). A duplicate catch writes no journal event. The receipts are read by statistics and the activity ledger, never by a stall check.

### Supervision: budgets, reloads, give-up, status

| Concern | Gen I (`emulator.py`) | Gen II (`gen2/emulator.py`) |
|---|---|---|
| Reload cap | `MAX_RELOADS = 12` at `:42` | `MAX_RELOADS = 12` at `:96` |
| Reloads before reporting | none | `STALL_RELOADS = 3` at `:95` |
| League restart | none | `LEAGUE_RESTARTS = 3` at `:102`, `league_restart` at `:106` |
| Guard clock | wall time, `time.time()` in `_check_guards` at `:851` | frames, `_check_guards` at `:967` |
| Give up | `_give_up` at `:779` | `_give_up` at `:856` |
| Unstick | `_unstick` at `:802` | `_unstick` at `:885` |
| Help request | `help_request` at `:287-297`, `progress_status` at `:299` | built inline in `status` (`:1218`) at `:1242` |
| Stall bundle | written at `:759` and `:896` | not written |

`config.py` adds `STUCK_RELOAD_SECONDS` 600, `BATTLE_TIMEOUT_SECONDS` 900, `STALL_ALERT_GAME_MINUTES` 120 and `STALL_ALERT_REAL_MINUTES` 15.

### Gifts and claims

Each gift source is written twice.

| Gen I | Gen II |
|---|---|
| `runtime/reward_delivery.py` (177 lines) | `gen2/rewards.py` (129 lines) |
| `legendary_returns.py` (147 lines), `claims` at `:84`, `consume` at `:72` | `gen2/returns.py` (411 lines), `claims` at `:186`, `consume` at `:171` |
| `mew_returns.py` (65 lines), `consume` at `:47` | `gen2/steps.py` (71 lines), `consume` at `:56` |

The League reward marks live in a third place, `store.league_marks` at `store.py:284`.

### Frame budgets

There is a budget per goal (S4, three times `expected_frames`) but no budget per tier. The spec reports that RACE was re-offered 65 times in 6.5 days. The marathon's own limits are `BUDGET` 180000, `INTERVAL` 1296000 and `IDLE_LIMIT` 7200 (`policies/marathon.py:14-17`).

## 2. The goal

A goal is one record. Every tier's work becomes a goal made from a template.

```python
@dataclass(frozen=True)
class Goal:
    key: str              # stable, such as 'hunt:gold:161:shiny:3f9a2c'
    template: str         # 'hunt', 'story', 'upkeep', 'race', 'upgrade', 'filler'
    what: dict            # template fields, such as species and DV rule
    done: Condition       # S2 condition that ends the goal as a success
    stop: Stop            # ends the goal without success
    tier: Tier            # S3 tier, the priority
    parent: str = ''      # the goal this one supports, empty for a root
```

Rules:

1. A root goal comes from a template, the owner or a share code.
2. The key is the template, the game, the species or target, a readable tag, and the first 6 hex characters of a SHA-256 over the canonical JSON of `what`. Two hunts for the same species with different DV rules get different keys.
3. A support goal comes from an unmet need. S1 turns a shortage into a `Need`. S2 turns an unmet precondition into an enabler. Each becomes a child goal with `parent` set.
4. S3 ranks every live goal in the tree in one pass. A child inherits no priority. It is scored on its own value, which includes the value it unlocks for its parent.
5. A support child (heal, balls, money, a rod) charges its frames to its root goal and to the root's tier, not to UPKEEP. A hunt that spends most of its time healing shows that time as hunt time, and the tier budgets in section 8 see it.
6. S4 measures each goal by the typed progress events it owns (section 4).
7. A goal ends as done, stopped or expired. Each end writes one progress event. The tree then falls back to the next goal S3 ranks.

A root with `stop=never` never ends. Its children still end. That is how "shiny Magikarp, never stop" keeps buying balls and fighting for money.

## 3. Hunt templates

The hunt is the reference template. The owner's main goals are shiny and high-DV catches.

### Schema

```python
@dataclass(frozen=True)
class Hunt:
    species: int                     # national dex number
    shiny: bool = False
    dv_min: tuple = ()               # (stat, minimum) pairs, stats named atk, def, spd, spc
    dv_total: int = 0                # minimum sum of the 4 stored DVs, 0 for none, at most 60
    where: str = 'auto'              # 'auto' or a map constant
    method: str = 'auto'             # 'auto', 'grass', 'old rod', 'good rod', 'super rod', 'headbutt'
    stop: Stop = Stop.never()
```

```python
@dataclass(frozen=True)
class Stop:
    frames: int = 0       # emulated frames, 0 for no limit
    real_seconds: int = 0 # running wall time, paused time excluded
    steps: int = 0
    level: int = 0        # the lead reaching this level
    attempts: int = 0     # encounters with the target species
    any_of: bool = True   # True stops at the first limit, False needs all of them
```

Rules for the fields:

1. No hunt may name `hp`, in either generation. The HP DV is built from the low bits of the other four in Gen I (`pokecore/dvs.py:6` `hp_dv`) and in Gen II (`pokecore/gen2/ram.py:68` in `individual`). The form shows it as derived.
2. `dv_total` is the sum of the 4 stored DVs (Attack, Defense, Speed and Special), so its range is 0 to 60.
3. `shiny` in Gen I means shiny once moved to Gen II, which is the existing rule in `pokecore/dvs.py:44` `is_shiny`.
4. The form and the share code decoder reject impossible rules. Shiny fixes Defense, Speed and Special at 10, so shiny with a Defense, Speed or Special minimum above 10 is rejected. Shiny also needs Attack bit 1 set, so shiny with an Attack minimum of 16 or more cannot occur and a `dv_total` above 45 (15 plus 3 times 10) is rejected too.
5. `where='auto'` picks the map and method with the most target encounters per frame, from the generated game data, at the current time of day. It is re-chosen when the period changes.
6. If the hunt has no target at this time of day, it parks when the owner chose the map and moves when `where` is auto.
7. `done` is built from the fields. A catch that meets every DV rule and the shiny rule is done.
8. A DV-threshold hunt keeps the best catch so far. Its score is the sum of shortfalls under each minimum, lower is better, and zero is done.
9. A Gen I DV-threshold hunt with Fair wild DVs off is allowed. The form shows a warning that the cartridge draw is correlated and the odds are unknown. It requires a stop when. The Live page shows the DV rate observed from the hunt's encounters, so the owner can see how often the rule is met in practice.
10. A hunt takes the tier the owner gives it. The default is PROGRESS, so a never-ending hunt does not outrank STORY. The owner may set it to STORY on the form.

### Game time is frames

Gen I playtime caps at 255:59:59 and Yellow is stuck there. Gen II caps at 999:59. So every game-time stop, budget or rate counts emulated frames, never the in-game clock.

1. All frame counts come from `PlayClock.frames` (`play_clock.py`). That clock already counts frames, ignores cartridge limits, and never moves back on a reload because `restore` keeps the larger count.
2. `Stop.frames` counts only the PlayClock frames spent while the goal or one of its children is the active goal. Frames while the goal is parked (night on a fixed map, a clock wait) or outranked by another goal do not count. S4 keeps this count per goal, beside the frames it already tracks for the budget.
3. `Stop.real_seconds` counts running wall time only, under the same rule. Paused time does not count.
4. One game hour is 216000 frames (`FRAMES_PER_GAME_MINUTE` 3600 in `stalls.py:11`, times 60).
5. Rates such as encounters per game hour are encounters per 216000 active PlayClock frames.
6. The form's "game hours" field stores frames. The page converts for display only.

### The hidden Pokémon and Stop when fields

These fields are new UI. The page today has no hunt form. The mapping:

| UI field | Hunt field |
|---|---|
| Hidden Pokémon: species picker | `species` |
| Hidden Pokémon: Shiny checkbox | `shiny` |
| Hidden Pokémon: DV minimums, one box per stat | `dv_min` |
| Hidden Pokémon: DV total | `dv_total` |
| Hidden Pokémon: Where (Auto or a map) | `where`, `method` |
| Stop when: Never | `Stop()` |
| Stop when: game hours | `Stop(frames=hours * 216000)` |
| Stop when: real hours | `Stop(real_seconds=hours * 3600)` |
| Stop when: steps, level, attempts | `Stop(steps=...)`, `Stop(level=...)`, `Stop(attempts=...)` |
| Stop when: "first of" or "all of" | `any_of` |

A saved hunt also sets the pcvalue `focus` input for its species family. That is the hook the oracle uses to keep hunt candidates (section 5).

### Share code

The format follows the randomizer code (`PSR1-<GAME>-<OPTS>-<seed>`, `pokecore/randomizer.py:223`).

`PSH1-<GAME>-<BODY>-<CHECK>`

1. `GAME` is the cartridge, such as `GOLD`.
2. `BODY` is Crockford base32 of a packed record: species (9 bits), flags (shiny, method, where-is-auto), four DV minimums (4 bits each), DV total (6 bits), a map id only when the owner picked one, and each stop limit as a varint. An auto location stays auto, so a code works across versions of the data.
3. `CHECK` is two base32 characters of a CRC over the rest.
4. Decoding rejects a code for another game, a species the game lacks, and every impossible rule from the list above.

Example: shiny Sentret on Route 29 in Gold with no stop would read like `PSH1-GOLD-5H2R0K8-QT`. The exact characters come from the encoder.

## 4. Typed progress events

Every tier writes typed progress events to one store table, `progress_events`. The existing `progress` table is a snapshot table and is left alone. S4, the watchdog, LoopGuard, live_soak and the report button all read this table.

### Row

| Field | Meaning |
|---|---|
| `frame` | PlayClock frame |
| `ts` | wall time, for display only |
| `kind` | see the table below |
| `goal` | the goal key that caused it, empty when none |
| `tier` | the goal's tier |
| `species` | dex number, when a Pokémon is involved |
| `identity` | trainer id, DVs and species fingerprint, the key `gen2/emulator.py:813` already builds |
| `score` | the goal's score after the event, such as the best shortfall |
| `net` | 1 if it counts as progress, 0 if it does not |
| `rewound` | set by the rewind event (section 6) |

### Kinds

| Kind | Net | Written by |
|---|---|---|
| `dex` | yes | any tier, on a new owned entry |
| `improve` | yes | the goal whose score got better, or the oracle when a kept Pokémon fills family demand or a plan need |
| `item` | yes for a key item or HM, no for a pickup or a purchase | UPKEEP and STORY |
| `badge`, `league`, `event`, `area` | yes | STORY |
| `checkpoint` | yes | RACE, one per marathon checkpoint |
| `catch` | no | every catch, from the same hook that writes `capture_receipts` |
| `receive` | no | gifts, returns, trades, hatches |
| `release` | no | every release, with the reason from the oracle |
| `room` | no | S1 make_room |
| `level` | no | any battle. A training goal whose score rises writes its own `improve` |
| `goal` | no | every goal start, done, stop, expire and stand-down |
| `plan` | no | diagnostics, such as boss ready's "Went in unready", and every reload or power cycle, with `identity` naming the reason, such as `reload:battle cannot end` |

Net comes only from `dex`, `improve`, a needed `item`, and the STORY and RACE kinds. A catch or a receive is never net by itself. A duplicate catch raises the held count, so counting held rises as progress would count churn as progress. When a caught or received Pokémon is kept because it fills family demand or a plan need, the oracle writes a separate `improve` row for it. LoopGuard still counts receive and release cycles by species from the `receive` and `release` rows.

In shadow mode the journal entry that reports a new owned entry, a badge, a League win, a new area or an item also writes its row, under the goal running at the time. An `event` row is a story flag this run has not seen set before, and its score is the count of flags seen. These rows follow the journal, so a reload can write one again. The rewind event (section 6) marks the ones a reload undoes.

### Encounter counters

Encounters are not rows. A shiny hunt would write about 20000 of them. S4 keeps one counter row per goal per game hour in a table `encounter_counts`:

| Field | Meaning |
|---|---|
| `goal` | goal key |
| `hour` | active PlayClock frames divided by 216000 |
| `encounters` | all wild encounters in that hour |
| `target` | encounters with the target species |
| `met_rule` | target encounters whose DVs met the hunt's rule, for the observed DV rate |

The rates in the absolute checks and the observed DV rate read these counters. They never count as net. The cartridge's wild battle hook counts each encounter in memory, and the next decision adds them to the counters with the running goal's target and rule.

### Which definitions it replaces

The five lists in section 1 become one function, `progress.counts(event) -> bool`, that reads `net`. `LoopGuard` reads `receive` and `release` rows by `species` instead of titles. The watchdog's `_quiet` fingerprint becomes "the newest `net` row frame".

This switch happens in two steps (section 13). First the rows are written in shadow mode and nothing reads them for decisions. The five readers move to `net` only after the two-week replay meets its bar.

Until the switch, the stall clock in all six games moves on the supervisor's high-water rule (`Supervisor.progressed`). Red, Blue and Yellow also move it on a rise in Pokémon held, so a long hunt is not a stall while the hunt rate is in shadow. That rise is one setting, `stalls.GEN1_HELD_RISE`, read by `stalls.held_rose` and the replay's `OldChecks.receipt`. The switch deletes all three, because a held rise is churn and the healthy hunt rate takes its place. Gold, Silver and Crystal never count it.

### The Kanto Marathon case

Each marathon checkpoint writes a `checkpoint` row with `tier=RACE` and `net=1`. Gen I queues it through `activity_events` (`policies/collection.py:585`). Gen II queues it through `take_events` (`gen2/marathon.py:132`). A run that is racing now shows a fresh `net` row every checkpoint, so the watchdog sees it move.

### Absolute checks per goal

S4 keeps three numbers per goal, all over active PlayClock frames.

1. Encounters per game hour for the target species, from `encounter_counts`. A hunt with no end reports this rate and an expected time to success, not a stall.
2. Catches per improvement. This is `catch` rows over `improve` rows for the goal. A high ratio means the goal catches a lot and gains little.
3. Churn flag. It is set when the best kept score stays flat over N catches for the goal. N is 10. By construction every hunt catch must improve, so 10 flat catches is already a fault. The two-week replay may raise N. The flag shows on the Live page and in the report.

### The stall rule

A goal is stalled when no `net` row lands in the window, unless the active goal reports a healthy rate. A hunt's rate is healthy while its target encounter rate stays at or above a quarter of its expected rate. A goal that is waiting on a clock or a condition is parked, not stalled.

Liveness is a separate check (section 6). A hung worker writes no rows and reports no rate, so it would look the same as a stall. The liveness check tells them apart.

## 5. The worth oracle

One call in `pcvalue.py` decides worth for every producer.

```python
def worth(mon, box, inputs) -> Worth: ...

@dataclass(frozen=True)
class Worth:
    score: int
    keep: bool        # would be kept if acquired now
    locked: bool      # invested, never a spare
    replaces: tuple   # identities it would push out, cheapest first
    reasons: tuple    # pcvalue part names, for the journal
```

`mon` may be a phantom with unknown DVs, as `keeps_another` builds today. `box` is the S1 ledger's view of party and PC, including reservations.

### Rules

1. Every producer calls `worth` before it acquires. Producers are gifts, returns, trades, breeding, hunts and training.
2. A producer that will take the mon calls `S1.reserve` for a slot before it starts. The reservation names the goal and is released on done, stop or rewind.
3. Invested Pokémon are locked. A mon is invested when its stat experience reaches `TRAINED_STAT_EXP` (100000, `pcvalue.py:51`), or a live goal names its identity. A locked mon is never in `releases`.
4. Hatches are not locked. A hatched mon is kept by family demand and plan needs, as any other mon is. A lock on every hatch would fill the boxes with eggs nobody needs.
5. Demand counts by evolution family. A family is the evolution tree from the generated data. It keeps one mon per stage the dex still needs, plus one per open plan need, and no more. A bred Squirtle then counts toward Wartortle and Blastoise. It is not a spare just because a Blastoise is held. This fixes the case where a bred Squirtle was released as a spare Blastoise, which `plan_partners` (`gen2/release.py:53`) could not see. A mon kept for this reason writes an `improve` row (section 4). Before the Champion no wild copy is caught for family demand alone, since the Pokédex waits for the story. Blue's ladder caught three such copies on the way to Bill and blacked out on Route 6.
6. The hunt's `focus` sets the family's focus weight (`WEIGHTS['focus']` 150). The best candidate for an open DV hunt is locked until the hunt ends.

### Box full of locked mons

If every party and box slot holds a locked or demanded mon, nothing can be released. The oracle reports a `full_locked` state instead of a spare.

1. Every producer that needs a slot parks. It does not retry, catch, release or reload.
2. One alert fires, once per entry into the state. It names the box counts and the goals waiting for room.
3. Goals that need no slot keep running.
4. The state ends when a slot frees up, from a goal ending, a lock lifting or the owner releasing a mon. Producers then unpark.

Parked producers write no rows and spend no budget, so the state can never loop. `pcvalue.deadlocked` (`pcvalue.py:282`) and `full_notice` (`:273`) are the starting point for it.

### Call sites it replaces

| Today | After |
|---|---|
| `rewards.wasted` (`rewards.py:114-140`) and its `marks=` path | `worth(gift).keep` |
| `gen2/collection.py:840`, `:845`, `:853`, `:859` | each `offer` calls `worth` |
| `gen2/breeding.py:97` `pairings` | pairs ranked by `worth` of the expected child |
| `app/coordinator.py:975` `_benefit`, `:1186` `_would_keep` | `worth` on both sides of a trade |
| `broker/routine.py:12` `benefit` | the same |
| `broker/inventory.py:130` `spare_entries`, `:141` | spares are `not keep and not locked` |
| `gen2/release.py:53` `plan_partners` | folded into locks and family demand |
| `gen2/release.py:88` `release_rated`, `:107` `keeps_another` | `worth` with a phantom |
| `runtime/participant.py:415-433` `would_keep` | `worth` |

The readers in `policies/team.py:64`, `policies/storage.py:65`, `strategic.py:1359`, `gen2/policy.py:738` and `gen2/ledger.py:190` read the same oracle and do not change behavior.

PR 4a-2 moves trades and hatching onto the PC value rows. In `trade/worth.py`, `gain` scores an incoming Pokémon by the reason the recipient's PC would keep it: a new entry, the only copy, a copy its family needs, or a rarer, shiny or trained copy. Level alone is no gain. `spares` and `given` list what a trade may give. A copy kept only for a linked adventure that lacks the species is marked For trade (`pcvalue.gives`), so a trade may still give it. `release.keeps_hatch` decides if an egg is worth hatching, and `pairings` asks it before it breeds for a demanded baby.

## 6. Shared supervision

A new module, `runtime/supervision.py`, owns budgets, the reload ladder, give-up and status. Each generation supplies an adapter.

```python
class Adapter(Protocol):
    generation: int
    def frame(self) -> int: ...
    def saves(self) -> list: ...                 # newest first, each with its PlayClock frame
    def load(self, save) -> None: ...
    def restart_league(self) -> bool: ...        # False when the game has no restart point
    def bundle(self) -> dict: ...                # stall evidence, never the save bytes
    def details(self) -> dict: ...               # the goal tree for status

class Supervisor:
    def __init__(self, adapter, store, clock): ...
    def tick(self, frames): ...
    def status(self) -> dict: ...
    def help_request(self) -> dict | None: ...
```

### One ladder for both generations

1. Unstick: reset the current goal and let S3 choose again.
2. Reload the newest good save. After 3 reloads with no `net` row, report the stall (`STALL_RELOADS` 3, now in both).
3. Restart the League when the adapter has a restart point (`LEAGUE_RESTARTS` 3).
4. Give up after 12 reloads with no `net` row (`MAX_RELOADS` 12).

Every timer counts PlayClock frames. The Gen I wall-clock guard at `emulator.py:851` moves to frames. `STUCK_RELOAD_SECONDS` and `BATTLE_TIMEOUT_SECONDS` become frame limits at 60 frames a second. Reload counts persist in the store, so a worker restart does not reset them.

The policy's own waits are named `Budget`s in the supervisor, each a PlayClock frame count that a reload neither restarts nor stretches. `REFUSED_SHORTCUT` (3600, about a game minute) is each generation's wait before it tries a refused Core shortcut again. Gen I's own waits are `PARTNER_TRAINING` (18000) between development excursions, and `DETOUR_REST` (3600), `LOOK_AROUND` (1800) and `CHAT_REST` (900) between chats and curiosity detours. A policy reads the PlayClock through its decider (`Gen1(clock)`, `Gen2(clock)`). Caps on tries, such as `REFUSAL_LIMIT` and `STRANDED_LIMIT`, stay counts, since a slow screen or a long walk would spend frames without another try. A timer that restarts at every restore, such as a navigator's short timers, a curiosity detour's own end or the action watch, keeps the emulator frame, since it never sees a rewind. The trade preparation's runner keeps the emulator frame too, since each of its keys carries the frame it began on.

`help_request` and `progress_status` are written once, in the supervisor (`Supervisor.help_request`, `Supervisor.progress`). Each generation only gathers what they read. Gen II keeps stall bundles through `runtime/capture.py`, the same as Gen I, so `Adapter.bundle` is not needed for them.

### Liveness, the one wall-clock check

Frames cannot see a hung worker, because a hung worker runs no frames. So there is exactly one wall-clock check, in two places.

1. The supervisor records the PlayClock frame and the wall time on every tick.
2. While the adventure is running (not paused, not in manual mode, not stopping), PlayClock must advance. If it has not moved for 15 real minutes, the adventure is not live.
3. The watchdog runs the same check from outside the worker, from the `play_clock` field in status. A worker that stops answering status counts as not moving.
4. Not live raises one liveness alert. It is not a stall and it does not climb the reload ladder. The fix is a worker restart.

PR 6 runs the check in the watchdog only (`Watchdog._live`, `Limits.not_live`). A worker whose game loop hangs still answers status with a clock that stands still, and a worker that hangs entirely stops answering, so the watchdog sees both. A second copy in the worker would only send the same alert twice. The library's monitor still restarts a worker whose frame count stands still for a minute (`app/supervisor.py` `check`), so the alert means a restart did not help. The watchdog's quiet window, `Limits.no_progress`, counts PlayClock seconds.

The stall rule in section 4 runs only while the adventure is live. Stalls and liveness are reported as different alert types.

### The rewind event

A reload moves the cartridge back. Today each ledger finds out on its own, or does not. The supervisor emits one event:

```python
@dataclass(frozen=True)
class Rewind:
    from_frame: int     # PlayClock frame before the load
    save_frame: int     # PlayClock frame the save was written at
    save: str
    reason: str
```

Every ledger reconciles on it.

| Ledger | Reconcile |
|---|---|
| S1 reservations | drop reservations made after `save_frame` |
| Claims ledger (section 7) | claims staged or delivered after `save_frame` go back to open. A gift delivered after the save is not in the reloaded cartridge, so it must be delivered again |
| `capture_receipts` | receipts after `save_frame` are marked rewound, not deleted |
| `progress_events` | rows after `save_frame` get `rewound=1` and stop counting as net |
| S4 monitor | spent frames stay spent, because the frames were really used |
| LoopGuard | counts persist and the reload is counted |
| PlayClock | unchanged. It never moves back |

## 7. Shared gift pipeline and claims ledger

One pipeline delivers every gift: League rewards, legendary returns, event returns and Mew steps. Each generation supplies only the cartridge write.

### Claims ledger

One table, `claims` (`pokesim/state/claims.py`, schema version 2):

| Field | Meaning |
|---|---|
| `source` | `league` today. `legendary`, `event` and `mew` join in PR 5b |
| `key` | dex number or reward seed |
| `state` | `open`, `delivered`, `declined`. `consumed` arrives with PR 5b |
| `frame` | PlayClock frame of the last change, or none for a claim moved from the old League ledger |
| `species` | the Pokémon a delivery wrote |
| `seed` | the gift seed, so a reopened claim writes the same Pokémon |
| `reasons` | why the oracle declined it, or why it reopened |
| `reward_id` | the delivery that settled it, so the gift's own result save never reopens it |

PR 5a keeps no `staged` state in the table. A gift is staged and committed inside one delivery, so a crash between them leaves the claim `open` and the pending record finishes or rolls it back. Schema version 2 moves each old League ledger into rows once: the gifts it settled become `delivered` rows with no frame, which never reopen, and the rest become `open`.

### Pipeline

1. A source makes a claim `open` when it is earned (wins, steps, return interval).
2. Before staging, the pipeline calls `worth`. If `keep` is false, the claim goes to `declined` with the reasons. This replaces `wasted()` and `keeps_another`.
3. If `keep` is true, it reserves a slot through S1 and stages the gift. PR 5a stages and commits in one step with no stored `staged` state.
4. Delivery is idempotent. Before it writes, the generation reads party and boxes for the claim's identity (the reward seed sets the DVs and trainer id). If the mon is already there, the claim goes straight to `delivered` with no write.
5. Otherwise the generation writes the mon into the cartridge. The claim goes to `delivered`.
6. A rewind sends claims delivered after `save_frame` back to `open`, except the one whose own result save is being loaded. The next delivery finds the cartridge without the mon and writes it again. A rewind to a save that already holds the mon finds it in step 4 and writes nothing.

Before PR 5a, both generations took the next League gift from a stored `delivered` count and raised it when the gift was written, and a reload never moved that count back. The ownership barrier is what kept a gift from being lost: after a delivery, `custom-reward-barrier-v1` refuses every save older than that gift (the restore check in `emulator.py` for Gen I, `_behind_barrier` in `gen2/emulator.py`). The ledger keeps that barrier. Reopening a claim on rewind covers the saves the barrier lets through, and the idempotent check in step 4 makes a second delivery safe either way.

PR 5a moves League rewards in both generations onto the `league` rows, and `store.league_marks` now reads them. PR 5b moves the pairs `legendary_returns.py` and `gen2/returns.py`, and `mew_returns.py` and `gen2/steps.py`. The single pipeline then replaces `runtime/reward_delivery.py` and `gen2/rewards.py`.

## 8. Frame budgets per tier

S4 has a budget per goal. This adds a share cap per tier over a rolling window of one game day (5184000 PlayClock frames).

| Tier | Share cap | Re-offer limit |
|---|---|---|
| STORY | none | none |
| UPKEEP | 20% | none |
| PROGRESS | none | none |
| RACE | 5% | once per `INTERVAL` (1296000 frames) after any end, a stand-down included |
| UPGRADE | 50% | S4 backoff |
| FILLER | the rest | S4 backoff |

A tier over its cap is skipped by S3 until the window rolls. The RACE limit stops the re-offer loop the spec reports. A RACE goal that stands down waits a full interval, as a finished one does.

A support child charges its frames to its root goal's tier, not to UPKEEP (section 2, rule 5). So the heal, ball and money trips of a PROGRESS hunt count against PROGRESS, and UPKEEP's 20% cap holds only upkeep that no root asked for.

## 9. The report button

### What it shows

It appears on every stall alert, on the Live page and in the notification link. It builds a report from the evidence record:

1. App version and commit.
2. Game and generation.
3. Location: map name and coordinates.
4. Alert type: no progress, loop, churn, low encounter rate, box full of locked mons, not live, or given up.
5. The goal tree with S4 numbers: every live goal plus the last 20 ended ones.
6. The last 200 `progress_events` rows and the last 100 journal titles.
7. The last 300 lines of `worker.log`.

### What it never holds

ROMs, saves, usernames, emails, `PUBLIC_URL`, IPs, tokens and notification credentials (`NTFY_URL`, `NTFY_TOKEN`, `TRADE_TOKEN`, `TRADING_URL`). The stall bundle's `.state` files are never read.

The report is built from an allowlist of fields. It is not a scrub of a full dump. Log lines and journal titles pass through a filter that replaces URLs, IP addresses, email addresses, token-like strings and absolute paths with a tag. The filter also replaces every account name and every adventure title it reads from the store, so a name or title in a log line is caught even when it looks like plain text.

### Flow

1. The user sees the full report in a dialog before anything leaves the page.
2. Send downloads the report file.
3. Send also opens a GitHub new-issue link with a new `stall-report.yml` template. The link carries only version, game and stall type.
4. The user attaches the file by hand.

### Redaction test

`tests/test_stall_report.py` builds an adventure with a sentinel in every banned source: `PUBLIC_URL`, `NTFY_URL`, `NTFY_TOKEN`, `TRADE_TOKEN`, an account name, an adventure title, an email, an IP in a log line, an absolute path in a log line, a save path and the ROM path. The account name and the adventure title also appear inside log lines and journal titles. It builds the report and the issue link. It fails if any sentinel appears in either, or if the link holds a field outside version, game and stall type.

The guide and the self-hosting doc say the report is built locally and sent only by the user. There is no telemetry.

## 10. Walking the three test goals

The facts below come from the generated game data (`encounters`, `maps` and `events` in the Gen II data bundle, `collection.json` in the Gen I bundle) and `pokecore/dvs.py`.

### (a) Gold, shiny Sentret on Route 29, never stops

Facts:

1. The Gen II shiny rule is Defense, Speed and Special DVs at 10 with Attack bit 1 set (`pokecore/gen2/ram.py:130`). That is 8 in 65536, or 1 in 8192.
2. In Gold, Route 29 grass has Sentret in 40% of slots in the morning and the day (30% at level 3 and 10% at level 2). It has none at night. The only other Gold grass source is Route 1, 20% by day.

Walk:

1. The owner saves the hunt: Sentret, Shiny, Where Route 29, Stop when Never. The goal is `hunt:gold:161:shiny:<h6>`, where `<h6>` is the hash of `what` (section 2, rule 2). Its tier is PROGRESS.
2. `done` is "a shiny Sentret is held". `stop` is never.
3. S3 picks the hunt. S5 asks the oracle on every encounter, not only on Sentret. The hunt sets CATCH for a shiny Sentret. The oracle sets CATCH for any shiny and for any species the dex is missing, as the Gen I fix on `gen1-catch-churn` already does (commit 9565d12, "Missing and shiny Pokémon are still always caught"). Every other encounter is FLEE.
4. Each encounter adds to the goal's `encounter_counts` row for the current game hour. It writes no row of its own. S4 reports Sentret encounters per game hour and an expected wait of about 8192 Sentret encounters, which is about 20480 grass encounters in the day.
5. At night Route 29 has no Sentret. The owner chose the map, so the hunt parks rather than moves (section 3, rule 6). Its `feasible` is false, the goal is parked, not stalled, and its `Stop.frames` count does not advance. S3 runs the next goal until morning.
6. Balls run low. S1 raises `Need(POKE_BALL)`. A child UPKEEP goal walks to the Cherrygrove mart.
7. Money runs low. Wild battles in Gen II pay no money, so S1 raises a money need. S3 picks a trainer rematch or a sale as the child goal.
8. HP or PP runs low. A child heal goal runs.
9. The root never ends. Each child ends on its own and writes a `goal` row.

The watchdog sees the encounter counters and the child `net` rows. The hunt reports a healthy rate, so no `net` row in the window is not a stall. A stall alert fires only if the Sentret rate drops below a quarter of expected for one game hour in the day. Separately, the liveness check alerts if PlayClock stops moving for 15 real minutes.

### (b) Red, a Pidgey with Atk, Def, Spd and Spc at least 12, stop after 3 game hours

Facts:

1. In Gen I the HP DV is built from the low bits of Attack, Defense, Speed and Special (`pokecore/dvs.py:6`). The form shows HP as derived.
2. Each of the four DVs is at least 12 in 4 of 16 values. With uniform DVs, all four is 1 in 256.
3. Uniform DVs need the Fair wild DVs setting. With it off, the cartridge draws correlated bytes (`fair_dvs.py:1-12`), and the odds of this set are not known. The hunt is still allowed (section 3, rule 9).
4. Red lists Pidgey in the grass of Route 1 (map 12) and Route 2 (map 13) at levels 2 to 5, and on later routes.
5. 3 game hours is 648000 PlayClock frames. It is never read from the cartridge clock, which caps at 255:59:59 in Gen I and is stuck there in Yellow.

Walk:

1. The goal is `hunt:red:16:dv:<h6>`, `dv_min` atk, def, spd and spc at 12, `Stop(frames=648000)`. The hash keeps it apart from another Pidgey hunt with a different rule.
2. `where='auto'` picks Route 1 or Route 2 by Pidgey encounters per frame.
3. The planner reads the wild DVs in battle. S5 asks the oracle on every encounter. It sets CATCH for any shiny, for any species the dex is missing (as in (a)), and for a Pidgey whose shortfall score beats the best kept Pidgey for this goal. It sets FLEE or FIGHT otherwise.
4. If Fair wild DVs is off, the form showed the warning and required this stop when. The Live page shows the observed DV rate from `encounter_counts`: Pidgey encounters that met the rule over all Pidgey encounters.
5. Each better catch writes `catch` (net 0) and `improve` (net 1). The new best is locked by the goal.
6. The oracle marks the old best as not locked. It stays only while family demand or a plan need wants a Pidgey. Otherwise it is the cheapest spare and goes at the next release. That release writes `release` with reason "replaced by a better hunt catch".
7. If a catch reaches zero shortfall, the goal is done.
8. `Stop.frames` counts only frames while this hunt or one of its children is active. If 648000 active frames pass first, the goal expires. It writes a `goal` row that names the best kept, such as "Atk 13, Def 12, Spd 9, Spc 14". The best stays locked as the hunt's result. S3 falls back to the next goal.
9. Catches per improvement and the churn flag show if the run keeps catching Pidgey with no gain. Every hunt catch must improve, so 10 flat catches set the flag.

### (c) Crystal, shiny Magikarp, never stops, no Old Rod

Facts:

1. The Old Rod comes from the fishing guru in the Route 32 Pokémon Center 1F. His object is at (1, 4) and runs `Route32Pokecenter1FFishingGuruScript`. He asks a yes or no question first. The flag is `EVENT_GOT_OLD_ROD`.
2. With the Old Rod, Magikarp is 85% of bites on Route 32, Route 30, Route 31, Violet City, Cherrygrove and New Bark (70% and 15% slots).
3. The shiny odds are 1 in 8192, as in (a).
4. Today Gen II only fetches the Good Rod (`gen2/policy.py:651-652`, the Olivine guru), and a rod method needs the rod item (`gen2/collection.py:1082`). So the Old Rod enabler is new.

Walk:

1. The goal is `hunt:crystal:129:shiny:<h6>`, `method='auto'`, never stops.
2. Auto picks the Old Rod, because it is the earliest rod with Magikarp. The hunt's precondition is `Item(OLD_ROD)`.
3. S2 finds it unmet. Its enabler is `Event(EVENT_GOT_OLD_ROD)` at the Route 32 guru. A child goal `get:old_rod` is spawned with `parent` set to the hunt. S2's `Reach` checks the walk to Route 32.
4. The child talks to the guru, answers YES, and ends done when the flag is set. It writes `event` and `item`.
5. The hunt becomes feasible. Auto picks Route 32, next to the Pokémon Center, for fast heals.
6. Each bite adds to the goal's `encounter_counts` row. S5 asks the oracle on every bite, so any shiny and any missing dex entry is caught, as in (a).
7. Ball, money and heal children run as in (a). They and `get:old_rod` charge their frames to PROGRESS, the root's tier. The root never ends.

## 11. Fitting in work in progress

### Boss ready (Step 2h)

It is a new S2 precondition in `planning/boss.py`. `Gate.decide(key, fighters, reachable, where)` returns READY, HEAL or UNREADY. Its limits are `READY_HP` 0.5, `READY_PP` 0.5, `STRONG_SHARE` 0.5, `SELF_KO_SHARE` 0.1 and `TRIPS` 3.

In the goal tree it is the `done` precondition of each boss goal. HEAL spawns a child heal goal. UNREADY after `TRIPS` heal trips lets the parent go in and writes a `plan` row, "Went in unready". Gen II rival battles are scripted with no goal key. They stay outside the gate until they get one.

### Live soak (Step 3)

`tools/live_soak.py` runs the real Manager on the cold backup and three seeded post-game rungs for 2 game hours. It checks releases, receipts, churn, real progress, reloads, journal growth and repeated titles per game hour against a baseline. That comparison is advisory. `deploy_host.sh` refuses a commit without a passing boot and load smoke, which plays each copy for 5 game minutes, saves and reloads it.

It is the soak gate for every PR below from PR 2 on. After PR 3 switches the readers to `net`, its invariants read `progress_events` instead of titles. During PR 2's shadow mode it reads titles as today and also reports where the shadow rows disagree. That closes its blind spot where duplicate catches write no event. Its other blind spots stay listed in its report.

## 12. Two-week journal replay on the desktop

This checks the progress model on real history before the stall tiers switch to it. It runs on the desktop, never on the deploy host.

### Tool

`tools/replay_progress.py`:

```
replay_progress.py run STORES_DIR --days 14 --out REPORT_JSON [--labels LABELS_JSON] [--churn-n 10]
replay_progress.py report REPORT_JSON
```

1. Input is two read-only copies on the desktop. The main one is the hosted app's newest cold backup, extracted outside the repo, for two weeks of real play. The second is a copy of the local dev instance's data folder, for the stall hunt games and their fresh stall events. The tool never opens a live data folder. It reads `events`, `capture_receipts`, `progress`, `kv` and the stall bundle reports. It never reads save state.
2. It rebuilds `progress_events` rows from the journal and receipts, as the new writers would have written them.
3. It runs the old checks (StallWatch, LoopGuard and the watchdog fingerprint) and the new model side by side over the same rows.
4. Ground truth is each stall bundle, help request, give-up, owner restart and the optional labels file.
5. It runs as one process under `nice -n 10`, inside the load gate.

### Report per adventure

| Column | Meaning |
|---|---|
| Stalls caught | true stalls the model flagged |
| Stalls missed | true stalls it did not flag |
| False alarms | flags with no true stall within one game hour |
| Time to detect | PlayClock frames and wall minutes from stall start to flag, median and worst |
| Old model | the same columns for today's checks |

The bar to switch: every labeled stall caught, at most one false alarm per adventure per week, and median time to detect no worse than today. Agent time is about 3 hours to build, plus about an hour of run time on the desktop.

### First run, November 2026

The first run did not meet the bar, so the switch to `net` is held.

1. Every adventure with real play time failed. The `net` model raised 23 to 168 false alarms in 14 days, where the old checks raised 6 to 40. It also missed more stalls on four of them.
2. Most false alarms are a gap in the input, not in the model. Training and marathon progress count only through `improve` rows a goal writes and RACE `checkpoint` rows. Old journals have neither, so the replay cannot rebuild them, and the hours before each false alarm show only level-ups, rematches, evolutions and races. The net kinds stay as they are, since counting level-ups would count churn as progress again.
3. The ground truth was weak. It was the old StallWatch's own alerts plus 14 stall bundles, since each adventure keeps only its newest 5. Help requests and owner restarts were not stored.

The switch decision moves to after PR 7. Then the replay runs on the dev instance's own shadow rows, which will have real `improve`, `checkpoint` and `encounter_counts` rows, with a backup copy of the hosted app as a second check. The bar stays the same.

## 13. PR sequence

Each PR is proved by the live soak gate and by behavioral parity tests. The soak takes about 15 minutes of wall time under the heavy lock. Estimates are agent time.

| # | Scope | Agent time | Proof |
|---|---|---|---|
| 1 | Behavioral parity tests | 3 hours | the new tests pass on main, with known gaps marked xfail and named |
| 2 | `progress_events` and `encounter_counts` tables and kinds, in shadow mode. Catches, receives, releases, marathon checkpoints and goal ends write rows. Nothing reads them for decisions yet | 4 hours | parity tests, soak, a test that a marathon checkpoint and a duplicate catch each write a row and that a catch and a receive are net 0 |
| 3 | `tools/replay_progress.py` and the two-week replay. The first run missed its bar, so the switch of the five definitions, LoopGuard and the watchdog to `net` moves to after PR 7 (section 12) | 4 hours plus 1 hour run | the tool's tests, the report in section 12 |
| 4 | Worth oracle with locks, family demand and the `full_locked` state. Every call site in section 5 moves to it | 6 hours | parity tests, soak, the bred Squirtle case as a test, a full box of locked mons parks producers and fires one alert |
| 5 | Claims ledger and shared gift pipeline, with idempotent delivery | 6 hours | parity tests, soak, staged and delivered claims reopen after a rewind, a second delivery of a held mon writes nothing |
| 6 | `runtime/supervision.py`, one ladder, the rewind event, frame clocks, the liveness check in the supervisor and the watchdog, Gen II stall bundles | 6 hours | parity tests, soak, both generations give the same ladder for the same scripted stall, a frozen PlayClock raises one liveness alert after 15 real minutes |
| 7 | Goal record with the `what` hash in the key, hunt template, stop when in active frames, per-tier budgets with support children charged to the root's tier, the shared goal shape in `state.strategy` | 8 hours | the three test goals as headless tests, soak, the `state.strategy` entry leaves ALLOWED |
| 8 | Hidden Pokémon and Stop when fields, share codes | 4 hours | round-trip tests for codes, a page test for the form |
| 9 | Report button, `stall-report.yml`, redaction test, guide and self-hosting text | 4 hours | `tests/test_stall_report.py`, `tests/test_no_private_strings.py` |

Total agent time is about 45 hours plus about 2.5 hours of soak time. Boss ready and the live soak land first, as Steps 2h and 3 already plan.

### How PR 1 fixes the parity test

`tests/test_generation_parity.py` walks the state, statistics and activity payloads and only checks that a key is filled in both. Its `ALLOWED` list excuses `state.strategy` as a whole (`:60`), so nothing checks that both planners report the same goal shape.

PR 1 adds `tests/test_behavior_parity.py`. It runs the same scripted situations on both generations and compares what the planner does, not which keys exist:

1. A full box with a gift due: both decline or both make room.
2. A stall with no progress: both climb the same ladder rungs in the same order.
3. A marathon checkpoint: both write a progress row.
4. A duplicate catch: both write a catch row.
5. A hunt with a threshold: both catch only an improvement.

Cases that fail today are marked xfail with the PR that fixes them. PR 7 then removes `state.strategy` from `ALLOWED` and adds `state.strategy.goal` to `REQUIRED`, with the fields key, title, tier, done and stop.

## 14. Decisions

1. A Gen I DV-threshold hunt is allowed with Fair wild DVs off. The form shows a warning that the odds are unknown, requires a stop when, and the Live page shows the DV rate observed from encounters (section 3, rule 9).
2. A fixed-location hunt with no target at this time of day parks if the owner chose the map and moves if `where` is auto.
3. Family demand keeps one mon per stage the dex still needs, plus one per open plan need, and no more.
4. A never-ending hunt does not outrank STORY by default. The owner may set the tier to STORY on the form.
5. A real-time stop when counts running time only. Paused time does not count.
6. The churn flag uses N = 10 catches, because every hunt catch must improve by construction. The two-week replay may raise it.
7. A share code carries a fixed map only when the owner picked one. Auto stays auto, so a code works across versions of the data.
8. The report holds the live goals plus the last 20 ended ones.

## 15. Open questions

1. Should a non-League goal run between two League tries? After a Crystal League loss, main walks a collection training goal and heals for about 10 game minutes before the next try, and that took one try more than going straight back on 2 seeds of 2. The goal tree work decides it.
