# Typed goals

Status: accepted on 2026-11-11. Every line number was read from main at `153a4c53` (#538). This is phase 2 item 5 of the architecture plan of 2026-11-09, and PR 7 of [Goal system v2](goal-system.md) section 13. It builds on the [Decide pipeline](decide-pipeline.md), whose section 7 lists what it hands over, and on the trace in [Replayable bugs](replayable-bugs.md).

Today a Gen I goal the planner works on is a project, one dict that mixes what the goal is with what it has done so far. Its kind is a string that about a hundred checks read, 83 of them in `policies/collection.py`. Gen II has no project. Its hunt target, training project and postgame activity are three more dicts with their own switches. When a goal gets stuck, Gen II reloads a save, though the trouble is usually that one goal and not the whole game. A manager can pin a goal only from the best few the planner offers now, and nothing outside the planner can see what else it could do or why it will not.

This note gives every goal one typed record, lets a stuck goal park with a typed failure in place of a reload, serves the planner's goal catalogue as plain data, and makes the pin a director that picks from that catalogue, with every choice in the replay log.

## 1. What a player can notice

Five slices. Slices 1, 2 and 4 change nothing in play. Three changes are on purpose, and each is named again in its slice's PR body.

1. Slice 3. In Gold, Silver and Crystal, a hunt, a training project or a postgame activity that stops making progress parks, and the planner moves on to its next goal. Before, the game reloaded a save and stood the same goal down after the reload. The journal says "Set aside: Find Clefairy. It stopped making progress" and the goal comes back after its stand-down, as before. Red, Blue and Yellow already do this through `recover_stall`.
2. Slice 5. A pin on a goal that cannot run now is accepted and waits with its reason, "Next: Train Bayleef (waiting: no route)". Before, the pin was refused unless the goal was in the planner's best few right now.
3. Slice 5. A pin ranks above every source's own goals, not only above the goals of the source it came from. It still waits for upkeep, for a move the game forces, for an errand under way and for the walk that meets the pick's need.

What moves out of PR 7, as agreed with the lead:

- The hunt template, stop when and the `what` hash in the key move to PR 8 with the form and the share codes. Today's key strings stay, so the stand-down, spent and no-route tables keyed by them keep working.
- Per-tier budgets (goal-system section 8) and an `interrupt_frames` commitment move to a follow-up, since both change play.
- The PR 3 replay bar re-runs after slice 5.
- A mode in the scenario runner that runs the stuck guards, so a stuck replay can reach a park or a reload. Neither the gate nor the replays run the guards today. It is its own PR after slice 5.

## 2. The goal record (slices 1 and 2)

```python
@dataclass(frozen=True)
class GoalSpec:
    kind: str           # 'grass', 'train', 'hunt', 'postgame.shiny', ...
    params: Mapping     # what the goal is, by the kind's schema
    key: str            # today's key string, built by the kind
    title: str
    tier: Tier

@dataclass
class GoalRun:
    spec: GoalSpec
    started: int        # PlayClock frame
    counts: dict        # initial_count, initial_owned, initial_experience, gains
    marks: dict         # progress_mark, checkpoint, race_frames, closest_distance, support_trip, ...
    maps: list          # the maps and flags it has seen, which Gen I keeps beside the project today
    flags: list
    idle_token: object
```

A spec is what the offers draw builds: the species, method, map, fragment, item, flag, target level, trainee and so on. A run is everything written after the goal starts. The split follows one rule, so it can be checked: a field set before `_start` is a param, and a field set after it is run state. Slice 1's PR body lists every field on its side of that line. The instance fields `idle_frames`, `project_maps`, `project_flags`, `progress_token`, `remaining` and `weighed` are run state that lives on `Collection`.

Each kind has one rules class.

```python
class Rules:
    kind: str
    params: tuple                         # (name, type, about) for the catalogue
    def key(self, params) -> str
    def feasible(self, view, spec) -> Failure | None
    def finished(self, view, run) -> bool
    def step(self, view, run) -> Goal | None   # today's project_goal branch
    def budget(self, spec) -> int | None
    def done(self, spec) -> str                # "Pikachu caught", "Level 30 reached"
```

- Gen I has 18 kinds, today's methods: grass, surf, fish, safari, static, gift, trade, fossil, return_fossil, marathon, rematch, trainer, explore, prize, rod, amber, train and evolve. The flags that change a method's meaning (`repeat`, `dv_hunt`, `legendary_return`, `event_return`, `upgrade_evolution`, `scoped_partner`) are params of it.
- Gen II has a kind per ladder rung (26 today, `gen2/collection.py:849-887`) and one per postgame activity (quality, shiny, train, marathon, league). Slice 2 gives records to the three that keep run state: the hunt target (`collection['target']`), training (`collection['training']`) and the postgame activity (`collection['postgame']['activity']`). The other rungs keep their own tables and appear in the catalogue by their goal key.
- The rules classes replace the `finished` cascade (`policies/collection.py:935-985`), the `project_goal` switch (`:1565-1625`), the key builder in `offers.add` (`:1264-1272`) and the method checks spread over strategic, marathon, storage, shopping, team, training and trade. Gen II's kind switches in `postgame.py` and `standdown.py` move the same way.
- The save shape does not change. `GoalRun.to_dict` writes today's flat project dict and `from_dict` reads it, so an older build loads a newer save and the other way round. Slice 1 adds a round-trip test over every project kind a gate rung starts.
- The monitor gets a public spend API, `set_spent(key, frames)` and `since(key)`. The 15 `_table` calls outside `planning/monitor.py` move onto it, in collection, director, strategic, unreachable, standdown and scenarios.

Readers outside the module (`emulator.py:1342`, `replay/validate_progress.py:87-98`, `scenarios.py:413`, `pc.confirmation`, `shop.step`, `pc.step`, `shop.plan`) get the run or its spec, not the dict. Nothing in `planning/`, `app/`, `runtime/` or `web/` reads a project today.

Proof for both slices: the ladder gate plays the same on all 59 rungs, the 51 stuck replays get going the same, and the decide pipeline agrees on every decision. A behaviour change shows as a different frame count on some rung.

## 3. Typed failures park a goal (slice 3)

```python
@dataclass(frozen=True)
class Failure:
    kind: str       # one of the kinds below
    detail: str     # plain words for the journal and the catalogue
```

| Kind | Meaning | Parks a goal | Read by |
|---|---|---|---|
| `stood_down` | its budget ran out without progress | yes, today | the filter, the catalogue |
| `no_route` | its walk found no route lately | yes, today | the filter, the catalogue |
| `claim_held` | its gift claim is held | yes, today | the filter, the catalogue |
| `stuck` | the stuck guard fired while it ran | new in Gen II | the journal, the catalogue |
| `no_progress` | Gen II's no-progress guard fired while it ran | new | the journal, the catalogue |
| `menu_failed` | a menu task for it kept failing | new | the journal, the catalogue |
| `lost` | it lost a boss battle (`planning/losses.py`) | no, the boss rule waits | the catalogue |
| `needs` | a condition it needs is unmet, with the need named | no | the catalogue |
| `not_now` | a rule of its source keeps it out, such as a party too weak for the grass | no | the catalogue |

`decide.STOOD_DOWN`, `NO_ROUTE` and `CLAIM_HELD` become the first three kinds, and `Offer.parked` and `Pin.parked` carry a `Failure`. The API sends its `kind` and `detail`.

### The park rule

A guard fires in `_check_guards` every 60 frames. Gen II parks in place of a reload when all of these hold:

1. The reason is "stuck", "no progress" or "a menu task kept failing".
2. `stalled_objectives` (`gen2/standdown.py:170`) names at least one objective, so a goal is running that can be set aside.
3. The goal running is not a story goal.
4. The snapshot is valid and the game is not in battle.
5. The ladder's streak of stalls without progress is 0. A second stall before new progress climbs to a reload, as today.

The park is `carry_over` (`gen2/standdown.py:192`) without the reload before it: each stalled objective stands down, and the hunt target, the training project and the postgame activity end. The failure kind is kept in a new `failures` table beside `stood_down` in the monitor's tables, which are the supervisor's `Tables` (`runtime/supervision.py:128`). Those survive a reload and a worker restart.

The park counts as one rung of the shared ladder (`Supervisor.climb`), so the streak, the stalled report and the twelve-reload give-up work as before. A reload still happens for a glitched state, a battle that never ended or cannot end, a story goal, and a second stall without progress since the park.

Gen I keeps its rule. `recover_stall` (`policies/strategic.py:1892`) already abandons the project with no reload on every stuck outside battle with a valid snapshot. Slice 3 only types it: the abandoned project's stand-down records `stuck`.

Rule 5 is an adapter setting, `RELOAD_AFTER_PARK`, written beside each generation's guards: `True` for Gen II and `False` for Gen I. A Gen I stall after a park parks again and never climbs to a reload outside battle. The generations differ because Gen II's park is new, so its second stall falls back to the reload it does today, which bounds the change, while Gen I has parked without a reload since `recover_stall` and keeps that play.

### How a parked goal comes back

A park is a stand-down. No new timer is added. The goal is eligible again once `Monitor.until(key)` passes on the PlayClock:

- Gen II: `STAND_DOWN` frames after the park (`gen2/standdown.py:22`), the frames of 50000 decisions.
- Gen I: the director's `RETRY` (`policies/director.py:43`), 60000 frames doubled for each stand-down in a row, three times at most.

The PlayClock never goes back, so a reload neither restarts the wait nor stretches it. Progress on the goal or its end clears its row (`Monitor.clear`), and the `failures` row clears with it. Nothing is parked for good.

### Proof for slice 3

The PR body gives:

- the reload count per rung before and after, on the gate and on the 51 stuck replays, with every rung whose count changed named
- for each stuck replay, the frame it got going before and after, and none later than before
- gate and replay decision agreement, which only changes where a park picks again in place of a reload

The tests cover a stuck Gen II hunt that parks and comes back after its stand-down, a second stall that reloads, a stall during a story goal that reloads, and a stall in battle that reloads.

## 4. The goal catalogue (slice 4)

The catalogue is plain data. It lists what a director can ask for.

```json
{
  "generation": 1,
  "kinds": [{"kind": "grass", "about": "catch a wild Pokémon in the grass",
             "params": [{"name": "species", "type": "species", "about": "the Pokémon to get"},
                        {"name": "map", "type": "map", "about": "the map it is on"}]}],
  "goals": [{"key": "4:grass:59:", "kind": "grass", "params": {"species": 35, "map": 59},
             "title": "Catch Clefairy (missing entry)", "tier": "progress",
             "feasible": false, "why_not": {"kind": "no_route", "detail": "no route"},
             "cost": 42000, "worth": 3.5}],
  "pin": {"key": "4:grass:59:", "label": "Catch Clefairy (missing entry)", "started": false,
          "parked": {"kind": "no_route", "detail": "no route"}},
  "reason": null
}
```

- A kind names what a director can ask for and its params, and a goal's tier is its own, so a kind carries none. Gen I's kinds are its collection rules (`policies/kinds.py`), with the species as a dex number and the map as its id. Gen II's kinds are its ladder rungs (`gen2/collection.py`), whose one param is the key of the goal the rung offers. A goal waits for one of the kinds in `planning/decide.py`. Two are new here: `needs`, something it cannot start without such as a ball or a rod, and `not_now`, a rule of its source that holds it back for now.
- `kinds` comes from the rules classes. `goals` comes from the same offers draw that feeds the pipeline, plus the goals that draw skipped and why. Gen I's `offers` drops a goal silently today when its key is standing down (`collection.py:1273`), when it has no step (`:1363`), when it has no route (`:1366`), when a need is unmet (`:1323`) and on a few source rules (`:1331`, `:1333`). Each skip becomes a `Failure` handed to an optional sink, which a live decision does not pass. Gen II's `survey` (`gen2/collection.py:955`) gets the same sink from the filter's parked offers.
- A goal its game can never offer again, such as a species already caught that the dex does not need twice, is left out. The list is goals a director can act on or wait for.
- `cost` is the candidate's `expected_frames` and `worth` its `value`, from the oracles that already price them (`planning/cost.py`, `planning/values.py` and each source's `candidate`). A goal skipped before its source priced it sends `null` for both. No new estimate code.
- `GET /api/catalogue?q=&limit=` serves it. It follows the access rules of `/api/state`: anyone who can see the adventure reads it, a view link included. It stays out of `VIEWER_PRIVATE` (`web/security.py:18`), and `app/manager.py:70` adds it to the paths the library forwards. `/api/goals` stays the manager's picker. Its rows keep key, label and tier, and gain `feasible` and `why_not`.

### Read only

Serving the catalogue must not change the run. It runs on the game thread through `emu.call`, as `/api/goals` does, and:

- It draws on a copy of the RNG, as `goal_list` already does (`collection.py:1510`), since `offers` shuffles the unseen maps (`:1477`). Gen II's `survey` already restores the RNG and the ladder.
- It writes no state: no monitor row, no navigation cache entry, no pin event, no journal row.
- A test runs a headless gate rung twice, once with a catalogue read every 50 decisions, and checks that the trace's decide digests, the frame count and the final state are identical.

### The shared goal shape

`state.strategy.goal` gets one shape in both generations: key, kind, title, tier, done, stop and parked. `stop` is `null` until PR 8. `tests/test_generation_parity.py` replaces its blanket `state.strategy` entry in `ALLOWED` (`:61`) with entries for the parts that stay each generation's own, each with its reason, and adds `state.strategy.goal` to `REQUIRED`. The Live page's `objectiveOf` reads the new field first.

The pokesim-ui session gets two lines with this slice: the endpoint and its access, and that the picker's rows now carry `feasible` and `why_not`.

## 5. The director takes catalogue goals (slice 5)

The director is one more source offering to the decide pipeline. It holds at most one standing choice, a catalogue key.

### Setting a pin

- `pin_goal` and `unpin_goal` keep the auth checks they have today in `/api/control` (`control_allowed`, `web/app.py:93`). The owner sets a pin, and so does someone the owner gave Can manage. A player and a viewer are refused. Nothing new opens.
- A key in the catalogue is accepted. A feasible goal runs as a pin does today. A goal that is not feasible now is accepted and waits with its `why_not` in `Pin.parked`, and the Next activity line shows it.
- A key not in the catalogue is refused with "Choose a goal from the list", as an unknown key is today.
- A parked pin starts once its failure clears. A pin whose run started and then parks ends, and the journal names the failure, as slice 5 of the decide pipeline does now.

### Ranking

`decide.decide` gets `pinned`, so the arbiter's pinned lane (`arbiter._lane`) ranks the pin after upkeep and before every other source's goals. Today the pin outranks only its own source's goals (decide-pipeline section 3). The forced rule, a hold on an errand under way, and the need walk still come first, since they are decided before the rank. A Gen I project the pin interrupts is set aside and comes back after, as now.

### The replay log

The trace records every pin change, and a replay feeds the director's choices back.

1. A manager's set and clear are `input` records with source `pin`, as today (`emulator.py:279`). They are written before the policy reads the pin. The tracer flushes the segment after a pin input (`Segment.flush`, a sync flush of the gzip stream, `packages/pokecore/src/pokecore/trace.py:165`), so a crash between the record and the read cannot lose the pin. Today only `check` records flush.
2. A pin's end, its drop on a stall (`_drop_pin`, `emulator.py:286`), its park and the clear on a load (`emulator.py:427`, `gen2/emulator.py:575`) follow from play. They are written as `pin` outcome records. A replay compares them and does not apply them, so a replay that drops the pin on another frame fails.
3. The pin lives in memory only and is never saved. A segment begins at an autosave, so its header carries the pin in force, and a replay of that segment sets it at frame 0.
4. `redecide` applies pin inputs at their frames, beside the clock inputs `verify` applies today.
5. A headless run takes a pin script, a list of frames and keys, fed through the same `pin_goal` path. A test pins a goal mid-run, replays the trace and gets the same decide digests.

## 6. Slices

| # | Scope | Deletes | Behaviour change | Agent time |
|---|---|---|---|---|
| 1 | Gen I `GoalSpec`, `GoalRun` and 18 rules classes, the monitor's spend API | the project dict's switches, the `finished` cascade, the key builder, the `_table` calls | none | about 4 hours plus 1 hour of gate and replays |
| 2 | Gen II records for the hunt target, training and the postgame activity | the kind switches in `postgame.py` and `standdown.py` | none | about 3 hours plus 1 hour |
| 3 | `Failure`, the park rule, the `failures` table | `decide`'s reason strings, the reload for a parkable stall | Gen II parks in place of a reload | about 3 hours plus 1 hour |
| 4 | The catalogue, `/api/catalogue`, `state.strategy.goal` | the blanket parity entry | none in play | about 3 hours plus 1 hour |
| 5 | The director on catalogue keys, ranking across sources, the pin records | the pin's own lane inside each source | parked in place of refused, ranking across sources | about 3 hours plus 1 hour |

Each PR deletes what it replaces, runs the targeted tests, and gives the gate and replay agreement in its body. Heavy runs go through `tools/load_gate.sh heavy`. Every second merged slice is reported to the lead.

## 7. Decisions and open questions

Decided on 2026-11-11:

1. Gen I does not reload after a park, and Gen II does on a second stall without progress. It is the `RELOAD_AFTER_PARK` adapter setting in section 3.
2. A pin keeps today's auth check: the owner and anyone the owner gave Can manage.

Open:

1. Should the catalogue name each kind's family (catch, gift, trade, evolve, breed, train, battle, item, explore, upkeep), so a director can ask for "the best catch" in either generation? It is cheap but not asked for yet.
