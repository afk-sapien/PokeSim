# Decide pipeline

Status: proposed on 2026-11-11. Nothing here is built yet. Every line number was read from main at `2d02e6c2`. This is phase 2 item 4 of the architecture plan of 2026-11-09, the new PR before [Goal system v2](goal-system.md) PR 7. Shadow mode reuses `planning/shadow.py`, and the trace is the one in [Replayable bugs](replayable-bugs.md).

Today each generation rebuilds its goal on every decision through an ordered chain. A source low in the chain wins because it comes later in the file, not because it is worth more, and nothing records that two sources fought. This note replaces both chains with one pipeline. Every source offers, one filter decides what can run, and the arbiter ranks everything that is left in one call.

## 1. Today's chain

### Gen I

The chain is in `policies/strategic.py`. `Choice` (L168-230) holds the pick. `offer` (L216) keeps a candidate only if `wins` (L204) prefers it to the pick, so the arbiter sees two candidates at a time. `replace` (L226) throws away everything weighed so far. While an errand is the pick, `wins` refuses every offer except the errand's own steps, so only a later `replace` cuts in. The order of the lines is the priority order. `step` (L482-490) puts a running errand back as the goal at L489.

| Line | Source | How it sets the goal |
|---|---|---|
| L518 | Hall of Fame ceremony | direct assignment |
| L582-587 | base goal: `collect_plan` after the Champion, else `story_goal`, then `boss_training` at L587 | direct assignment, then boss training replaces it |
| L594 | running collection project | replace |
| L596 | pickup | offer |
| L603 | party upgrade | replace |
| L634 | party release | replace |
| L640 | party box | replace |
| L650 | heal latch | replace |
| L967 | heal | replace |
| L980 | party upgrade | offer |
| L1022 | supplies | replace. It also writes `supplies_prepared` (L1024) and abandons the project (L1026) |
| L1045 | teach a battle move | offer, then a direct assignment at L1047 |
| L1052 | TM development | offers at L1640, L1652, L1660 and L1666 |
| L1056 | trash | replace |
| L1061, L1068 | `collection.choose` (`policies/collection.py:1101`) | replace. Choosing abandons the project before the Champion (`collection.py:1110`) |
| L1076 | pickup | offer |
| L1083 | collect passage | replace |
| L1098 | hideout elevator | replace |
| L1138-1139 | Champion ceremony | direct assignment after the decision |
| L1286, L1288 | victory ascent and drop | direct assignment |
| L1294 | a legendary ends, back to `collect_plan` | direct assignment |
| L1318 | social detour, `_purposeful_detour` (L1934, goal set at L1946) | direct assignment in the walk, for a partner (L1989) or curiosity (L2025) |

That is 11 replaces against 8 offers, plus 9 direct assignments.

Two shadow points watch it today. `overworld` (L1104-1106) compares the arbiter with the chain's pick, but over `choice.candidates`, which restarts at every replace. The `Choice` docstring says so: its arbiter pick is always the pick. So the point agrees by construction and measures nothing about the replaces. `collection` (`policies/collection.py:1144`) compares the project pick.

### Gen II

`step` (`gen2/policy.py:1386`) puts a running errand back at L1399.

| Line | Source | How it sets the goal |
|---|---|---|
| policy.py:371-626 | `story`: Cable Club exit, Time Capsule restore, tower, contest, the Johto story, then `kanto.journey` (`kanto.py:4`) | 81 early returns in source order |
| kanto.py:71 | the collection, once the story is done | return |
| policy.py:368-369 | boss training (`boss_training`, L1103) | replaces the story goal, as Gen I L587 |
| collection.py:811 | `holds`: a contest, Tower challenge, League funding run or postgame League run under way, or no ball pocket that can catch | return before any rung |
| collection.py:798-892 | `journey` builds a `Ladder` (L607) with 27 offer rungs (L850-888) | offers weighed two at a time (L735). Asking a rung can change saved state, so the ladder saves the state before each rung and undoes the losers (L634-683) |
| collection.py:884 | postgame rung, `postgame.choose` (`postgame.py:340`) | an offer that ranks its own options on the full arbiter |
| policy.py:1486 | release | replace |
| policy.py:1532 | heal during a talk | replace |
| policy.py:1564, L1570 | partner move, delete an HM | direct assignment |
| policy.py:1593-1594 | heal or shop errand | replace |
| policy.py:1601 | an errand with no route gives way to the journey goal | direct assignment |
| policy.py:1720 | Sudowoodo walls off Route 36 | direct assignment inside the detour |

Gen II shadow points are `ladder` (policy.py:1489-1496), `hunt` (collection.py:1079) and `postgame` (postgame.py:348).

### The manager pin

`planning/pin.py` holds the activity a manager set. In Gen II the pinned rung is always asked (`gen2/collection.py:627-629`) and skips the tier cut (L702), the stand-down check (L704) and the no-route check (L712). `settle_pin` (L921) drops it when its rung offered nothing. In Gen I, setting a pin abandons the running project (`policies/collection.py:1446`).

## 2. The target

One module, `planning/decide.py`, used by both generations with their own list of sources.

```python
@dataclass(frozen=True)
class Offer:
    source: str           # 'heal', 'story', 'ladder', 'director'
    goal: object          # today's Goal, the typed goal record after PR 7
    candidate: Candidate  # planning/arbiter.py
    needs: tuple = ()     # needs this goal cannot run without, such as 'party_ready' or 'room'
    serves: str = ''      # for an enabler, the need it meets
    hold: bool = False    # a goal under way
    forced: bool = False  # a move the game forces now, by map or event
    commit: object = None # writes that run only when this offer is picked
```

`decide(sources, view, pinned=None, style=None)` returns a `Decision` with the pick, every offer, the parked offers with their reasons, and the rule that picked. It runs these steps in order.

1. **Gather.** Each source returns its offers. A source only reads, and its writes move to its `commit` (section 5, rule A). The collection pick is the one source that draws a random number, its shuffle at `policies/collection.py:1386`. It keeps that draw at the same point of the decision as today, so the run's random sequence does not change. A test runs every source twice on one state and checks that `state_dict()` is unchanged and that no other source drew.
2. **Filter.** One check for every source, with no exemptions. An offer is parked with a reason when the supervisor stood it down or spent its budget (PR 6), when its walk found no route lately (`no_route`), or when its gift claim is held (PR 5). The reasons are constants in `decide.py`, so a director can read them.
3. **Forced.** A forced offer is the pick. The ceremonies, the elevator, the passage, the victory walk and Sudowoodo are forced, each with the map or event that forces it. The game allows nothing else there, so this is no override, and the trace names it.
4. **Hold.** A goal under way stays the pick. It gives way only to its own steps and to the enablers of its needs. This is today's rule in `Choice.wins` and in Gen II `holds`, written once. It replaces the heal latch and the errand restores (strategic.py:489, gen2/policy.py:1399).
5. **Rank.** The rest go to one `arbiter.rank` call, with the director's key as `pinned`. Worth (PR 4) sets values and readiness (`planning/boss.py`, `gen2/readiness.py`) sets the team needs.
6. **Needs.** The best offer runs if its needs are met. Otherwise the pick is the enabler that serves its first unmet need, and the Decision records the goal it serves. Heal, box, release, supplies, trash and boss training stop replacing. They win because the chosen goal needs them, or as UPKEEP offers when the party needs them for its own sake.
7. **Commit.** The pick's `commit` runs, and nothing else does. Shadow mode never commits.

The needs table is read off today's chain, so the switch starts from today's behaviour. A goal needs every enabler that replaces it today, which is every enabler whose replace comes later in the chain. Slice 1 writes the table for Gen I and slice 4 for Gen II. Any later change to the table is a behaviour change and goes to the lead first.

Item uses where the party stands take one action and end the step before the chain finishes. They are the League treatment, field cures, vitamins in a full bag, medicine during a heal and teaching from TM development (strategic.py:986-1052, L1639-1655). They stay in the step until phase 3 makes them task objects. A step that ends in one is not a decision, and shadow does not count it.

Until a group of sources switches on, the chain that is left runs as one source, `legacy`, which offers its own pick. So a switch moves one group at a time, and every switch PR deletes the chain sites of its group.

## 3. The external director

A director is one more source. It holds at most one standing choice, a goal key from the goal list (`pin.grouped` today, the PR 7 catalogue later). It offers that goal in the pinned lane, which `arbiter._lane` already puts after upkeep and before everything else.

- Its offer passes the same filter. An offer that cannot run is parked, and the reason goes back to the director: a `pin.gave_up` row now, a typed failure after PR 7.
- It never overrides. Forced moves, holds, UPKEEP and needs still go first, the same as for any source.
- Its choice enters through the trace as an `input` record with source `director`, so a replay makes the same choice at the same record.
- Today's manager pin becomes the first director in both generations. In Gen II it asks the rung it names through the ladder, with no exemption.

## 4. Shadow mode

### How it runs

On each decision, after the chain sets the goal, `decide` runs on the same state. No commit runs, so shadow changes no state and draws no random number. In slice 1 each chain site records its offer, named by its source, when it calls `offer` or `replace` or sets the goal. At the end of the decision the pipeline ranks those offers. So it weighs what the chain weighed, nothing runs twice and no source draws again. Guards that read the chain's pick at that moment, such as `not choice.errand`, stay at their sites in slice 1. Each switch slice turns its sites into source functions, moves those guards into the hold rule, and measures again in shadow before it switches. Gen II's ladder stays one source in shadow and reuses the pick and the candidates the ladder already built, so no rung is asked twice.

### What it records

1. The trace's `decide` record gains an optional `pipeline` field with the key the pipeline picked, its source and the rule that picked it. pokecore's replayer compares the field when the logged record has it, and leaves it out when the logged record does not, so old segments still verify. A replay then also checks that the pipeline is deterministic.
2. A new shadow point, `pipeline`, counts decisions and agreements and sorts each disagreement into one difference. The differences are `tier`, `score`, `key`, `unlisted`, `passive` and `idle` from `arbiter.compare`, plus `parked` (the chain's goal was filtered) and `need` (one side picked an enabler and the other did not).
3. `pokesim/replay/rung.py` already adds up the frames of each step by the shadow's pick. It also adds up the frames where the pipeline's key equals the chain's key.
4. `python -m pokesim.replay audit` and the ladder gate report print, per rung and per source, the decisions, the share agreed, the share of frames agreed, the differences and the top three disagreements.

No progress rows are written, so the soak clock keeps running.

### How agreement is measured

A decision counts when either key changes since the last one, as the `overworld` point counts today. Long waits under one goal would otherwise drown the moments that matter. Frames count on every step. The decision share shows how often the two disagree. The frame share shows how much of the run would play differently.

### The switch bar

The data comes first from the ladder gate (59 rungs, about 3 minutes) and the 51 stuck-scenario replays, then from local dev soak runs on origin/main of 24 game hours per generation. TyNet is never used. Each switch PR states its measured numbers in its body. If a rung sits under 95%, the lead hears which rung and why before anything is tuned to pass. A source group switches on when all four hold.

1. No `unlisted` difference. The pipeline sees every goal the chain picks.
2. STORY and UPKEEP picks agree on every decision. A disagreement left here is named in the switch PR and goes to the lead before merge.
3. At least 98% of frames run under a goal both picked, over each generation, and no rung is below 95%.
4. Every remaining disagreement is named in the switch PR as fixed or as accepted.

After a switch, the gate must show 0 stalls, no rung more than 1 point more wasted than its baseline, and the same milestones earned on every rung.

If shadow adds more than 5% to gate time, it runs on every fourth decision and on every decision where the chain's key changes.

## 5. Changes on purpose

Slices 1 to 4 aim for no behaviour change, and the switch bar checks it. These choices change behaviour on purpose.

The lead approved all three on 2026-11-11.

**A. A source writes only when its goal is picked** (slices 2, 3 and 4). Today a site writes while choosing even when a later site overrides its goal. Under this rule each write below moves to its source's `commit` and runs only when that offer is picked. It is a deliberate difference from the Gen I reference. Gen II already works this way, since the ladder undoes the losers, and a goal that loses should leave nothing behind. Do not move one of these writes back before the pick.

| Write | Today | Source |
|---|---|---|
| the swap's `pc.species` and `pc.destination` | strategic.py:978-979, before its offer | party upgrade |
| `release_spare`, and clearing the swap | strategic.py:629, L632-633 | party release |
| clearing the swap | strategic.py:638-639 | party box |
| `supplies_prepared` on the project | strategic.py:1024 | supplies |
| the supplies abandon | strategic.py:1026 | supplies |
| the abandon before the Champion | `policies/collection.py:1110` | collection |
| the committed `project`, `idle_token` and marathon timer | `policies/collection.py:1127-1132`, L1148 | collection |
| the pickup's `active` and its `expires` | `policies/pickups.py:110-111` | pickup |
| `tm_plan` and `tm_frame` for a TM purchase | strategic.py:1664-1665 | TM development |
| `next_goal`, the goal shown behind an errand | strategic.py:1067, L1075 | collection, pickup |

Observations that every decision makes stay where they are, such as the heal latch update (L959), the pickup scan timer (`pickups.py:90`) and clearing a finished swap (L599). Slice 4a adds the Gen II `_step` writes to this table before 4b moves them.

**B. A pin passes the checks** (slice 5). A pinned Gen II rung no longer skips the stand-down check (`gen2/collection.py:704`) or the no-route check (L712). A rung the watchdog gave up on is parked, where today the pin asks it again. A pin comes from the owner in the UI, and a pin that silently does nothing is a bug. So the same PR puts the parked reason into the adventure's API state and shows it in the UI where the pin is set. The UI part is agreed with pokesim-ui through the lead.

**C. A pin keeps the project** (slice 5). Setting a pin in Gen I no longer abandons the running project (`policies/collection.py:1446`). The pin wins by its lane, and the project resumes after it. The project's budget counts only the frames it runs. A test checks that the project resumes with its progress intact after the pin ends.

## 6. Slices

Each switch slice deletes the old call sites it replaces in the same PR. Estimates are agent time.

| # | Slice | Deletes | Time |
|---|---|---|---|
| 1 | Pipeline and Gen I shadow: `planning/decide.py`, every Gen I chain site recording its offer with its source, the Gen I needs table, the trace field, the `pipeline` point and the report | the `overworld` shadow point (strategic.py:1104-1106), which agrees by construction | 5 hours |
| 2 | Gen I upkeep and party switch: heal, upgrade, release, box, supplies and trash become needs and UPKEEP offers. Holds replace the heal latch and the errand restore | replaces at L603, L634, L640, L650, L967, L1022, L1056, the offer at L980, the heal latch, the restore at L489 | 3 hours |
| 3 | Gen I story and collection switch: base goal and boss training, the project, `collection.choose`, pickups, teaching, TM development and the forced moves | `Choice` (L168-230) with `offer` and `replace`, replaces at L594, L1068, L1083, L1098, offers at L596, L1045, L1076, L1640-1666, direct assignments at L518, L582-587, L1047, L1138-1139, L1286, L1288, L1294, the `legacy` source, the `collection` shadow point (`collection.py:1144`) | 4 hours |
| 4 | Gen II, in two PRs. 4a is shadow: story, holds, ladder and the `_step` sites as sources, with the Gen II needs table. 4b switches them | 4a: the `ladder` shadow point (policy.py:1489-1496). 4b: boss training (L368-369), release (L1486), heal (L1532, L1593-1594), partner and HM (L1564, L1570), the no-route fallback (L1601), Sudowoodo (L1720), the errand restore (L1399), the `holds` return (`collection.py:811`) | 4 hours |
| 5 | Director source: the manager pin becomes the director in both generations, and its choices go into the trace. A parked pin's reason reaches the API state and the UI, and a test checks that a Gen I project resumes intact after a pin | the pin exemptions (`gen2/collection.py:627-629`, L702, L704, L712), the Gen I pin abandon (`policies/collection.py:1446`) | 2 hours |

The total is 18 agent hours, plus the shadow runs before each switch. Slices 2 and 3 wait for slice 1's shadow data, and 4b waits for 4a's.

## 7. What it leaves

To PR 7:

- The typed goal record of goal-system section 2. Until then an offer carries today's `Goal` and a reason constant.
- Typed failures that park a goal in place of a reload, and the parked reason a director reads.
- Frame budgets per tier, which join the filter as one more reason.
- The goal catalogue for an outside director: each kind, its parameters, whether it can run now and why not, its cost and worth.
- Commitment by `interrupt_frames` in place of the absolute hold, which would let a much better offer cut into an errand. That is a behaviour change, so it waits for typed goals and their budgets.
- The 47-key collection project dict.

To phase 3:

- One Policy protocol and a shared loop with a game adapter per generation.
- The 27 Gen II rungs as separate offers in the shared arbiter, which removes the `Ladder` and its undo copies.
- The Gen II story's ordered returns, which stay one `story` source until then.
- League and training rules moved into planning.
- Splitting `gen2/policy.py`, with errands, latches and the Gen I social detour as task objects. The detour stays in the walk until then, because it draws random numbers and sets the goal only for its own excursion.
