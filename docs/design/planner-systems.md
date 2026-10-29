# Planner systems: replacing special cases

Status: proposal, no code yet. Read from main at `efc9491`.

Most stuck loops of the last month were fixed with a special case: sell a repel, skip a wait when the boxes are full, close two gate tiles, cap one hunt. Each fix works, but the next loop needs another one. This document lists those fixes, groups them by the mechanism that is missing, and proposes five systems that replace them.

## 1. Band-aid inventory

### Recent pull requests

| PR | Where (main) | Symptom patched | Missing mechanism | Cause |
|---|---|---|---|---|
| #133 | `gen2/collection.py:537-539`, `:641-642` | Gold paced Goldenrod for Day Care steps, 29% of frames | Background waits treated as passive progress, never chosen as a foreground goal | B |
| #135 | `gen2/training.py:20-31` `POCKET_SLOTS`, `bag_takes`, `:69` `share_blocked` | Exp. Share swap refused on a full pocket and replanned every 3600 frames, 56.6% | Item moves check bag room before they are planned | A, D |
| #135 | `gen2/training.py:22` `ITEM_REFUSALS`, `:417` `held_back` | The same refused task came back each time its block ended | One refusal count and backoff for every goal | C |
| #137 | `gen2/training.py:35-66` `KEPT_ITEMS`, `VALUABLES`, `spare_item`, `room_goal`, `:345` | A full pocket blocked held-item swaps | A bag arbiter that ranks items by their value to active goals | A |
| #146 | `gen2/policy.py:1467` `tower_travel` | The Battle Tower walk fought every wild battle, then turned back to heal, 35% | Engage or flee decided from the current goal and its HP and PP budget | E |
| #147 | `gen2/collection.py:21` `policy.no_room` in `clock_wait` | A Lapras wait with 14 full boxes blocked the League, 98 to 100% idle | A wait whose payoff is a catch checks box room first, and a wait never blocks other goals | D, B |
| #148 | `policies/shopping.py:29` `spare_repels`, `:100` | Red skipped all three legendary birds with no bag slot for Ultra Balls | The same bag arbiter as #137, built again for Gen I | A |
| #150 | `policies/director.py:55`, `gen2/postgame.py:35` `WEIGHTS`, `:234` | Rematch and League runs took 46% (Blue) and 28% (Gold) of frames | Utility per expected frame instead of per turn in a rotation | B |
| #151 | `gen2/collection.py` `carrier_budget`, `observe_carriers`, `carriers_exhausted`, and one call in `Policy.step` | A 2% held-item hunt took 33 to 98% of frames | One expected-cost budget for every goal, kept across restarts | C, B |
| #153 | `policies/navigation.py:30` `CYCLING_ROAD_CHECKS`, `:279` | A run with no Bicycle paced the Route 18 gate until a two-minute timeout | Navigation reads gate conditions from game data | F, D |

#145 (shared loop error recovery), #149 (a harness check that the cartridge matches the game data) and #152 (a feature) are not band-aids. #149 does point at one real cause: Gen I game data is chosen from an environment variable at import time. That is a separate cleanup and is out of scope here.

### Their predecessors

- Stand-down and backoff: `gen2/standdown.py` (9160209), then the Remedy refusal (103f8c6), Time Capsule backoff (98e6be1), Tower stand-down (938a314), `SHINY_ENCOUNTERS = 100` (beb0919, `gen2/postgame.py:27`) and the Gen I two-minute idle timeout (`policies/collection.py:469`). #135 and #151 are the sixth and seventh budgets, each with its own constants.
- Bag: the `len(items) >= 18` sale rule (ad5b1e7) and selling spent evolution stones (09ae6c7), then #135, #137 and #148. Gen I and Gen II each keep their own lists of what to keep or sell.
- Waits: `while_waiting` (d7be7b9) and releasing spares instead of reloading on a clock wait (3fb9eaf), then #133 and #147.
- Director: new entries first (5869435, 81cbe2a, `director.py:52`), the level 100 weight fix, the League in the Gen II rotation (beb0919, 3894554), then #150. These are three tweaks in a row to one `select`.
- League deadlocks: b110a07, c6b4415, ddc4ad6, 4d0ddd8, fa9e915 and 143fbcd, each guarding one case.
- Gates: `ROUTE_23_CHECKS`, the Saffron drinks and the Cinnabar doors (`navigation.py:27`, `:281`), the gate officer warp carpets (4ce54a2), then #153.
- Fleeing: the shiny session flee (beb0919) and the uncatchable shiny (1275e1e), then #146.

### Older special cases found in a sweep

| # | Where | Symptom | Cause |
|---|---|---|---|
| 1 | `gen2/policy.py:921-923` | A hard-coded sell list (Nugget, Pearl and seven TMs), used only when money is under 200 | A |
| 2 | `policies/shopping.py:23-25`, `:79` | `SPARE` and `LUXURIES` sets plus item ids 201 to 250 decide what is sold | A |
| 3 | `gen2/training.py:353-357` | An item is tossed when the PC refuses it | A |
| 4 | `gen2/policy.py:945-949` | Money reserve is 400 at 1200 or more, or fees plus 1000 | A |
| 5 | `policies/shopping.py:40-46` | Safari fee reserve keyed on badges and HMs | A, D |
| 6 | `gen2/collection.py:478-483`, `gen2/kanto.py:90` | League funding fires under fixed money, ball and potion counts | A |
| 7 | `policies/collection.py:814`, `:852` | Rematch weight and director urgency both switch at money 10000 | A, B |
| 8 | `gen2/policy.py:1419-1422` | No balls thrown under 1200 money with three or fewer balls, except for a species list | A |
| 9 | `gen2/policy.py:953`, `:971-981` | Fixed restock targets for balls, potions and revives | A |
| 10 | `policies/director.py:53-57`, `:73-76` | Tier filters and fixed category priorities, each tuned after an incident | B |
| 11 | `gen2/collection.py:446-577` | About 25 sub-planners in a fixed order, first non-empty goal wins | B |
| 12 | `policies/strategic.py:595-720` | Goal overrides chosen by key-prefix exclusion lists | B |
| 13 | `policies/collection.py:866` | Per-method time budgets of 300000, 180000, 108000 and 36000 frames | C |
| 14 | `policies/collection.py:467`, `:602`, `:850` | `PROJECT_COOLDOWN` 12000, 1200 after Champion, 3600 with no candidates, 600 between choices | C |
| 15 | `gen2/postgame.py:26-30` | `QUALITY_BUDGET`, `SHINY_ENCOUNTERS`, `SHINY_MAX_FRAMES` | C |
| 16 | `gen2/collection.py:779-781` | An outing is dropped after 20 "map still loading" steps | C |
| 17 | `gen2/tower.py:70`, `gen2/teams.py:14-16` | Separate retry and backoff copies (`RETRY_AFTER`, `BLOCKED_LIMIT`) | C |
| 18 | `policies/strategic.py:1115-1143`, `:1427` | TM check, teach, deadline and development timers | C |
| 19 | `gen2/policy.py:907-912`, `:987-1012` | Shopping turned off on named maps to stop a walk out and back. Moved to S3: the cost of interrupting a puzzle map | B, C |
| 20 | `policies/strategic.py:695-706`, `:842-917` | Victory Road coordinate boxes for one route and the boulders. Deferred from S2: boulder choreography, not a precondition | D |
| 21 | `gen2/policy.py:1131-1162`, `gen2/champion_shop.py:41`, `gen2/menus.py:154` | Three copies of the protected move set, plus a Move Deleter special case for Waterfall | A |

## 2. Root causes

The four suspected causes hold, with three corrections.

- **A. No resource model.** Confirmed, and it is the largest group. Bag slots, item PC slots, box slots, money and move slots are checked ad hoc at the point of failure. Gen I and Gen II fixed the same full-bag bug twice (#137, #148). It also explains the open Silver and Gold end state: every spare boxed duplicate holds an item (51 of 57 in Silver, 33 of 33 in Gold), so nothing can be released, so nothing can be caught.
- **B. No unified goal utility.** Confirmed. Gen I picks by "last writer wins" in `StrategicPolicy.step` plus a weighted lottery for side projects. Gen II has a fixed ladder of about 25 sub-planners. Neither weighs value against expected time, so cheap-looking turns of a long goal (a rematch, a wait) crowd out progress.
- **C. No progress detector.** Corrected: it exists in pieces. Gen I has backoff in `AdventureDirector.finish` (`director.py:113`). Gen II has stand-down in `gen2/standdown.py` but it only knows hunt, train, postgame and team keys. About ten hand-set budgets sit on top. The missing part is a shared definition of progress, not the backoff itself.
- **D. No precondition check.** Confirmed, and it overlaps with A. #135, #137, #147 and #148 are all "a goal started without the slot or box it needs". When goals declare their needs, one check covers both.
- **E. New: battle choices ignore the goal.** #146 and the shiny flee rules exist because engage, flee or catch is decided without knowing what the current goal needs or what HP and PP it can spend.
- **F. New: navigation has no model of world conditions.** Gates that need a Bicycle, a drink, a badge or an event are added as tile lists after each stall (#153, `ROUTE_23_CHECKS`, Saffron, Cinnabar).

## 3. Proposed systems

All five live in a shared `pokesim/planning/` package below the generation split. Each generation supplies a small adapter that reads its own memory map.

### S1. Resource ledger (cause A)

Interface:

```python
@dataclass(frozen=True)
class Need:
    pocket_slots: dict[str, int] = field(default_factory=dict)  # "balls": 1
    box_slots: int = 0
    party_slots: int = 0
    money: int = 0
    move_slot: str | None = None   # protect a move such as "SURF"

class Ledger:
    def snapshot(self) -> Resources            # read from the save or memory
    def reserve(self, goal: str, need: Need) -> Reservation | Shortfall
    def release(self, goal: str) -> None
    def make_room(self, shortfall: Shortfall) -> list[Goal]   # sell, deposit, toss, unequip, release
```

- Each item, box mon and move gets a value from the goals that want it (a ball is worth more while a legendary goal is active). `make_room` evicts the lowest value first and never touches a reserved unit.
- Money reserves (Safari fees, League funding, restocks) become reservations instead of thresholds.
- Plugs into `ShopPlanner.plan` and `cash_reserve` (`shopping.py:40`, `:112`), `_release_target` (`strategic.py:353`), Gen II `Policy.shop` (`policy.py:906`) and `training.spare_item` (`training.py:43`).
- Deletes: `POCKET_SLOTS`, `bag_takes`, `share_blocked`, `KEPT_ITEMS`, `VALUABLES`, `spare_item`, `room_goal`, `spare_repels`, sweep rows 1 to 9 and 21.
- Also fixes the Silver and Gold deadlock: a box slot shortfall can ask to unequip a spare duplicate's item, then release it.

Migration:
1. Read-only `Ledger.snapshot` for both generations, logged next to the existing checks. No behaviour change.
2. Gen II bag: replace #135 and #137 with `reserve` and `make_room`.
3. Gen I bag and money: replace #148, `SPARE`, `LUXURIES` and the Safari reserve.
4. Boxes and party, including unequip then release.
5. Move slots: one protected move set used by HM teaching, the Champion shop and the Move Deleter.

Sweep rows closed: 1, 4, 6, 7, 8 and 9 in #172, 2 and 5 in #169, 21 in #168, and the box rule in #167. Row 3 stays by choice. The tossed item is the ledger's least-worth spare (`gen2/ledger.py` picks it), and the toss is only the action taken when the item PC refuses the deposit, so no threshold is left there.

As built (#165 to #169 and #172), the interface differs in a few places:
- `make_room` returns the `Unit`s to give up, worth least first. The caller turns them into goals.
- `read` takes `kinds` and `boxes`, so a caller reads only the room it needs and passes the policy's box ranking.
- `Ledger.compare` logs where the ledger would choose differently from an existing check, used while a rule moves over.
- Box space is `box_wanted` with `BOX_RESERVE` 5 and `BOX_REFILL` 10. A release visit that starts below 5 free slots frees up to 10. Its frames do not count against the Gen I project it interrupts.
- `FIELD_MOVES` and `LEARN_KEPT` live in `planning/ledger.py`, shared by both generations' move checks.
- Gen I money comes from `money_needs` (the cash reserve and the Safari fee). The Gen I rematch uses `funds_short`, the cash reserve plus ten Ultra Balls.
- Gen II money comes from `money_needs`, `supplies` and `held_money`.
- A Gen II spare whose item is taken off goes back to its box when a PC step is refused, and `Take` closes the PC text the withdrawal leaves up.
- A Gen II release visit (`gen2/ledger.release_step`) finishes a spare whose item is coming off, then ends at `BOX_REFILL`. Before that fix one Crystal visit released to 34 free slots.
- A drop in Pokémon held is a `room` progress event in `planning/progress.py`, so the monitor and the replay audit count a release visit as progress.
- The Gen II headless runner adds the planned Champion shop item to the clerk's list, as the managed runtime does. Without it every replayed Champion shop visit stood down.

### S2. Precondition check (causes D and F)

Interface:

```python
class Condition(Protocol):
    def holds(self, world: World) -> bool
    def enabler(self, world: World) -> Goal | None   # a goal that would make it hold

def feasible(goal: Goal, world: World, ledger: Ledger) -> Feasibility
    # ok, or the missing conditions and the goals that would enable them
```

- A goal declares `requires()`: items, badges, events, a ledger `Need`, and reachability of its target map.
- Navigation edges carry conditions taken from game data (gate scripts, item checks, event flags) instead of tile lists. An edge whose condition fails is closed and its enabler is offered as a goal.
- Plugs into Gen I `Collection.goal` (`collection.py:871`) before a candidate is accepted, Gen II `prerequisites` and `usable` (`gen2/collection.py:307`, `:664`), and the route planner in `policies/navigation.py`.
- Deletes: the `no_room` check in `clock_wait` (#147), `CYCLING_ROAD_CHECKS`, `ROUTE_23_CHECKS`, the Saffron and Cinnabar lists, sweep rows 19 and 20.

Migration:
1. `Condition` types and `feasible`, with tests built from the stuck scenarios.
2. Gate conditions extracted from game data for Gen I, checked against today's hand lists.
3. Navigation uses them and the hand lists go.
4. Collection goals declare `requires()`, starting with catches (box room) and legendaries (balls).
5. The same for Gen II, with its own gate data.

Sweep rows closed: none. Row 19 moved to S3, since it weighs a shop walk against leaving a puzzle map, which is utility, not a precondition. Row 20 stays open, deferred from S2: it is boulder choreography and needs its own batch. The #147 and #153 band-aids, `ROUTE_23_CHECKS` and the Saffron and Cinnabar lists are gone.

As built (#176 to #180), the interface differs in a few places:
- The Gen I gate table, `policies/gates.py`, is generated, not hand-written. `tools/gen1_gates.py` builds it from the pinned pokered scripts and writes the source commit in its header, and `tests/test_gen1_gates.py` regenerates it and fails on drift whenever a pokered or pokeyellow checkout is present (CI fills `.reference`). Red and Yellow agree on every gate.
- Conditions are `Item`, `Count`, `Can`, `Badge`, `Event`, `Reach` and `AnyOf`, in `planning/conditions.py`. `Can` asks the adapter a whole-snapshot question, such as room to catch or a party that surfs. `Requirements` pairs conditions with a ledger `Need`, and `feasible` reserves that need under a key.
- Navigation keeps one condition per gate (`GUARD_GATES`), read through `StoryWorld`. The Route 23 Earth Badge guard now blocks only x below 14, as the game does.
- Gen I collection sources declare `source_requires` instead of goals declaring `requires()`. The Safari fee is a `Need(money=800)` on the ledger.
- Gen II has no hand-written gate lists, since its navigation reads map events from pokecore, so it has no generated table. Its clock wait asks `gen2/ledger.catch_room`, which needs a box slot once the party is full, or a spare the ledger can release.

### S3. Utility arbiter (cause B)

Interface:

```python
@dataclass
class Candidate:
    key: str
    tier: Tier             # STORY, PROGRESS, UPKEEP, FILLER
    value: float           # progress it buys: dex entries, badges, legendaries, levels
    expected_frames: float # travel plus expected encounters times frames per encounter
    passive: bool = False  # waits that accrue on any walk (Day Care steps, clock)

class Arbiter:
    def choose(self, candidates: list[Candidate], state: State) -> Candidate
```

- Score is `value / expected_frames`, with a higher tier always first. Story stays a hard tier, rematches and League runs are `FILLER`, and passive waits are never chosen. They only accrue while something else runs.
- `expected_frames` uses the real encounter odds. That fixes the held-item hunt that prefers a near Route 28 spot (10%) over Silver Cave Outside (90%), and it charges the grass walk between water points.
- Plugs in where the Gen I override chain sits (`strategic.py:319-362`, `:595-720`) with `director.select` as its scorer, and where the Gen II `collection.journey` ladder sits (`gen2/collection.py:441-577`). Each sub-planner returns a candidate instead of returning first.
- Deletes: the tier filters and fixed priorities in `director.py`, `gen2/postgame.py` `WEIGHTS`, the money-based rematch weight, the #133 and #147 wait rules, sweep rows 10 to 12, and row 19 (moved from S2), where a shop walk is weighed against the cost of leaving a puzzle map half done.

Cadences that S4 left in place and S3 should replace with its own scoring: `PROJECT_COOLDOWN` (sweep row 14), the tower `RETRY_AFTER` rest, the shiny session slice (`SHINY_ENCOUNTERS` and `SHINY_MAX_FRAMES`), the strategic development and TM check timers (row 18) and the Gen II `attempts` recency of 18000 decisions.

#### Scoring

Line numbers in this subsection are from main at 45374eb.

- **Tier.** `STORY` before `UPKEEP` before `PROGRESS` before `FILLER`. An enabler that S2 offers for a failed condition (a box room visit, a restock) takes the tier and value of the goal it unblocks, not its own.
- **Value.** One unit for both generations: a new dex entry is 1.0, a legendary is a dex entry, a species' first level 100 credit is 0.5, a perfect species is 0.5, and a quality catch is 0.5 times the expected drop in the species' best DV tail. Money has no value of its own. It is worth what it funds, so the rematch is worth its prize only while `funds_short` (`policies/ledger.py:131`) holds and a small constant otherwise. The lead approved these weights (see Decided).
- **Expected frames.** `planning/cost.py` gives `travel + needed / chance × frames_per_encounter`, the shape Gen II already uses in `search_expected` (`gen2/standdown.py:31`). `needed` for a quality hunt is the expected catches until a better copy, one over P(better). Travel uses the route planner's length.
- **Interrupt cost.** A candidate that cuts into a running goal adds the frames to walk back to it, plus the frames sunk into the current map when its puzzle resets on exit (boulders, switches, an unfinished League run). That is how row 19 goes: a shop walk out of Ice Path or the League costs the sunk frames, so it loses unless the need is urgent, with no named map list.
- **Ties** break on key so the choice is deterministic. The recent-kind decay (`director.py:114`, `:122`) goes, since S4 backoff already moves the arbiter off a stalled goal.

#### Boundary with S4

- S3 supplies `expected_frames`. S4 starts each goal with a budget of three times that and stands it down with backoff when no progress event comes. A stood-down key is left out of the arbiter's list until its `until`.
- S3 decides when a hunt is no longer worth doing (its value falls as P(better) falls, or the target is met). S4 decides when a hunt is not progressing. Neither keeps a fixed catch count.
- After a stand-down the arbiter picks the next candidate, which covers Gold event-9335.
- A shiny search becomes `FILLER` at a constant rate, and S4 counts each target species encounter as its progress event. That needs a small S4 change, flagged below.

#### Gen I and Gen II share it

- `planning/arbiter.py` and `planning/cost.py` are shared. Each generation has one adapter that turns its sources into candidates: Gen I in `policies/collection.py` and `policies/strategic.py`, Gen II in `gen2/collection.py` and `gen2/postgame.py`.
- Parity: arbiter detail shown on the Live page goes under `state.strategy`, which `tests/test_generation_parity.py` already allows as a per-generation planner shape. Any new statistics or activity field, such as an arbiter share in the audit, is filled by both generations in the same PR. The shadow comparison in step 3 goes only to the log and the replay audit.

#### Steps

1. **Arbiter core.** `planning/arbiter.py` (`Candidate`, `Tier`, `choose`, `compare`) and `tests/test_arbiter.py`. Nothing calls it, so behaviour is preserved. Unit tests on fixed candidates: tier order, value over frames, interrupt cost, passive never chosen, and the Yellow Dojo gift (`43:gift:177:HITMONLEE`) outranking a long hunt. Closes no rows.
2. **Shared cost and Gen I odds.** `planning/cost.py` takes over `search_expected` from `gen2/standdown.py:31`. `tools/gen1_wild.py` generates a Gen I wild table (`policies/wild.py`) from the pinned pokered and pokeyellow data, with a drift test `tests/test_gen1_wild.py` built like the gate test. Preserves behaviour, with an equivalence test that Gen II `search_expected` returns what it did. Closes the S4 known gap once step 5 uses it.
3. **Shadow mode in both generations.** Gen I `Collection.choose` and the `_overworld` chain, and the Gen II `journey` ladder and `postgame.choose`, build candidates and call `Arbiter.compare` while the old order still decides. Preserves behaviour, with equivalence tests on the stuck scenarios that the chosen goal is unchanged. One read-only batch reads the would-have-chosen shares, with no 2-point bar. Closes no rows.
4. **Red box room enabler (Gen I).** See the Red answer below. `policies/team.py` (`spare_entries` reachability at `:85`), `policies/storage.py` (`release_target` at `:23` offers the unlist plan), `policies/strategic.py` (the release visit at `:358` and `_release_target` at `:1101`), `duplicates.py` (offer a party duplicate, if allowed), and an enabler on `Can('catch')` for the catch sources (`policies/collection.py:831`). Changes behaviour. Red batch, bar: `collect_rematch` down at least 2 points and a `room` progress event in each save. Closes no sweep rows. It does not need steps 1 to 3 and could go first.
5. **Gen I side projects on the arbiter.** `policies/director.py` loses the new entry and rematch-last filters (`:96-100`), the priorities and decay (`:114-122`), and `new_entry` counts a legendary only when unowned (`:27` returns True for a returned repeat, such as Red's Articuno). `policies/collection.py` loses the rematch weight `10 if short else 2` (`:972`), `urgent=short` (`:1010`), `PROJECT_COOLDOWN` (`:31`), the 1200 and 3600 cooldowns (`:630`, `:1008`) and the 600 frame gap (`:765`). Catch kinds take `expected_frames` from step 2 instead of `EXPECTED_FRAMES` (`:38`). Changes behaviour. Batch, bar: 2 points on Red `collect_rematch` and Yellow `collect_hunt` (14.7%), and the Dojo gift no longer stands down. Closes rows 10 and 14.
6. **Gen II postgame on the arbiter.** `gen2/postgame.py` loses `WEIGHTS` (`:35`), the rotation in `choose` (`:215`), `SHINY_ENCOUNTERS`, `SHINY_BREAK_ACTIVITIES` and `SHINY_MAX_FRAMES` (`:27-30`). A quality hunt ends at the first better copy instead of `QUALITY_CATCHES` 3 (`:26`), and `reachable` (`:256`) and `quality` (`:275`) rank by value over cost. `planning/progress.py` counts a target encounter for a shiny search. Changes behaviour. Batch, bar: Gold Golduck (63.7%, 29.0 wasted, 3 stalls), Silver Girafarig (55.9%, 27.7 wasted) and Crystal's Silver Cave shiny search (17.6%, 7.4 wasted) each down at least 2 points. Closes row 15.
7. **Gen I overworld overrides.** `policies/strategic.py` `_overworld` (`:590-760`) and the story, collection and release choices (`:324-372`) become candidates. `_tm_development` (`:1114`) loses its 18000 and 3600 timers and becomes a candidate worth the move it gives. Changes behaviour. Batch on all three Gen I games. Closes rows 12 and 18.
8. **Gen II ladder.** Each rung of `gen2/collection.py` `journey` (`:480`) returns a candidate. `while_waiting` (`:54`) is passive. The #133 and #147 wait rules, the `attempts` recency of 18000 (`:662`) and the tower `RETRY_AFTER` 50000 (`gen2/tower.py:53`) go. The shop-off map list (`gen2/policy.py:938-947`, `:984-1004`) is replaced by interrupt cost. Changes behaviour. Batch on all three Gen II games. Closes rows 11, 17 and 19.

#### Red answer

Red is not out of work the way Blue is. It has open goals it cannot reach, and nothing offers the goal that would reach them. From the three S2 saves, read without stepping:

- Frame shares (S2 after, the same as the base): `collect_rematch` 42.3% with 7.6 wasted, the League 35.0%, marathon 5.9% (all wasted), `collect_plan` 5.9%, ceremony 5.4%, heal 3.8%, `collect_train` 0.9%.
- Long goals still open: 26 quality hunts (136 species with a readable best tail, 66 above `GOOD_TAIL`, 81 with their searches spent), and the perfect and high quality goals. No perfect species is held. Level 100 credit covers 150 of 151 and only Snorlax is missing, finished in the third save.
- Every catch source fails `Can('catch')` (`policies/collection.py:831`, `ram.py:196`). The boxes hold 240 of 240 with the party full, so `can_catch` is False.
- `spare_entries` finds 16 spares (Muk, Kabutops, Rapidash and others), but all 16 are unlisted. The first slot of box 11 holds a trade nickname with a list break byte (`ram.py:336` `LIST_BREAKS`), so the 19 slots after it never show. `policies/team.py:85` reserves them, `_release_target` (`strategic.py:1101`) returns None and the release visit (`:358`) never fires.
- What is left is training (it ends when Snorlax reaches 100), marathon and the rematch fallback. The rematch's prize money is worth nothing to Red: money is 151763 against `funds_needed` 12300, so `funds_short` is False and the weight is the floor of 2 (`:972`).
- Blue, for contrast: 151 of 151, level 100 credit 151, 240 stored, 0 spares, 0 unlisted. Its 27 open quality hunts are also blocked by full boxes, and there is nothing to release under today's keep rules. That is a real end state.

The missing goal is a box room enabler that reopens box 11's list. Free a party slot by releasing the weaker Pidgeot (level 38, while the level 40 one keeps Fly), withdraw the nickname breaker, release spares up to `BOX_REFILL`, and deposit the breaker last so it hides nothing behind it. The arbiter values the enabler at the catches it unblocks (step 4).

#### Decided

The lead approved the plan as picked and confirmed these on 2026-10-29.

- Party releases stay off. The step 4 enabler never releases a party duplicate.
- Shiny progress belongs to S4. A target species encounter counts as progress for the monitor, so a live shiny search is not stood down as idle. The planner's own shiny search stays `FILLER`, and the value weights give it no extra worth.
- The value weights are approved as written under Scoring: a new dex entry 1.0 (a legendary counts as one), a species' first level 100 credit 0.5, a perfect species 0.5, and a quality catch 0.5 times the expected drop in the best DV tail. The rematch is worth its prize while `funds_short` holds and a small constant otherwise.
- Step 4 went first (#186, with the #188 fix).

#### As built

- Step 1 is #194. `planning/arbiter.py` ranks by tier, then value over expected plus interrupt frames, with ties on key. Passive candidates are never ranked, and an empty or all-passive list chooses nothing. `compare` names how the arbiter's pick differs from the chosen key. The seeded 18-run batch was byte-identical to the aac30ee baseline.

### S4. Progress monitor with backoff (cause C)

Interface:

```python
class Monitor:
    def start(self, key: str, expected_frames: float) -> None
    def observe(self, key: str, frames: int, events: list[ProgressEvent]) -> Verdict
        # CONTINUE, or STAND_DOWN until a frame or decision count
    def shares(self) -> dict[str, float]   # frame share per goal for audits
```

- A progress event is defined per goal kind: a dex entry, an item obtained, a level, a badge, a target encounter, a map reached.
- The budget is a multiple of the goal's own `expected_frames` (three by default), counted across restarts. After that comes exponential backoff, kept in the save like today's stand-down.
- Merges the two halves that exist: Gen I backoff from `director.finish` and Gen II `stood_down` from `standdown.py`.
- Deletes: sweep rows 13 to 18, `ITEM_REFUSALS`, `SHINY_ENCOUNTERS`, `QUALITY_BUDGET`, the #151 carrier budget and the tower and team retry copies.

Migration:
1. `Monitor` with `shares()` only, used by the replay audit. No behaviour change.
2. Gen II stand-down moves onto it with today's constants.
3. Gen I director backoff and idle timeout move onto it.
4. Budgets switch from constants to `3 × expected_frames`.
5. The remaining per-feature counters go.

As built (#155, #156, #157, #162), the interface differs in a few places:
- A progress event clears the frames spent on a key but keeps its stand-down count, so a goal that progresses and then stalls again still backs off from where it was.
- `observe` takes `now`, the frame or decision count the backoff is measured in.
- `Monitor` adds `stand_down(progressed)`, `standing_down`, `until` and `clear`. `start` takes a `budget` override.
- Backoff is `Backoff(base, doublings)`.
- Gen II state stays in `collection['stood_down']` so older saves keep their waits. Gen I state is in `director.progress`.
- Known gap: Gen I uses `expected_frames` declared per kind of project until S3 adds encounter odds, because the Gen I `collection.json` has no odds.

Counters fall into three kinds. Real budgets (Gen I per-method budgets, the #151 carrier budget, the Gen II quality hunt, training and the TM plan deadline) use three times expected, counted across restarts and cleared by progress. Attempt counts (`ITEM_REFUSALS`, the teams `BLOCKED_LIMIT`, the outing "map still loading" 20 steps) move to the monitor in their own unit. Cadences are not budgets and go to S3.

### S5. Goal-aware battle stance (cause E)

Interface: `goal.stance(encounter, ledger) -> FIGHT | FLEE | CATCH`. The default comes from the goal kind (travel flees plain battles, training fights, a hunt catches its target). HP and PP are ledger resources, so a goal that needs them for its destination flees early.

- Deletes the `tower_travel` key list (#146) and the shiny session flee rules.
- Migration: one step per generation, after S1.

## 4. How we prove it works

- **Replay audit.** Each system ships with a before and after replay on all six games under the load limits (one batch, at most six processes, `nice -n 10`). It reports frame share per goal from `Monitor.shares()`, stall count (stand-downs plus reloads), and wasted frames (frames in goals that ended with no progress event).
- **Pass bar.** No goal above 15% of frames unless it is intended (the Bug-Catching Contest), no new reloads, and wasted frames below the baseline.
- **Regression set.** The private stuck scenarios already replayed by the full suite, plus one scenario per fix in section 1. Each must still pass with the special case deleted.
- **Unit tests.** Ledger arithmetic and eviction order, condition and enabler pairs, arbiter ordering on fixed candidates, and monitor budgets and backoff.

## 5. Estimates (agent time)

| System | Agent work | Replay time |
|---|---|---|
| S4 progress monitor | about 3 to 4 hours | two batches, about 40 minutes each |
| S1 resource ledger | about 5 to 6 hours | three batches |
| S2 preconditions | about 4 to 5 hours | two batches |
| S3 utility arbiter | about 8 to 10 hours | five batches plus one read-only shadow batch, the largest change in behaviour |
| S5 battle stance | about 2 hours | one batch |

Suggested order: S4 first, because it merges code that already exists and gives every later step its metric. Then S1, S2, S3 and S5. The lead picks the final order.

## 6. Open findings to fold in

- Silver and Gold are stuck in League runs (94% and 95.7%) because spare duplicates hold items. Silver has 251 of 251, 14 full boxes and a full party, and 51 of 57 boxed duplicates hold an item. In Gold all 33 boxed duplicates hold one, and 30 of them are also trained. Fixed by S1 step 4.
- Gold save event-9335 idles 98% after a lost League run. S4 should stand that goal down and S3 should pick the next.
- The held-item hunt ranks spots by distance plus a fixed term, and spends half its time on a 10% spot. The Poliwhirl surf hunt prefers Route 28 (10% Poliwhirl) over Silver Cave Outside (90%). About 80% of its battles are grass species met walking between water spots, so it gets about 7 Poliwhirl battles per game hour and one item takes about 7 game hours. Fixed by S3 expected frames, with S5 fleeing off-target battles.
- Red's "Train CHEESEKING to level 30" takes 79.8% of frames at about 0.3 level gains per 10000 frames, and Yellow's training takes 58.8%. S4 progress rate and S3 cost should cover both. These need checking in the next audit.
- Blue at 151 of 151 with full boxes is a real end state. Rematches as filler are the intended result there. Checked again for S3: 0 spares and 0 unlisted. Red is not in the same state. Its 16 spares sit behind a list break in box 11 (see the S3 Red answer).
- Crystal's 47% wasted in the S4 baseline was an audit artefact. The audit counted only level ups as training progress, but Furret climbs from level 82 to 97 per run. The audit now counts trainee experience, and that training is productive.
- Red's CHEESEKING and Ditto gain 14 to 16 levels per run, so Red's training share is slow progress, not a stall.
- Yellow's `party_release` loops releasing from a full box (3 stalls in the baseline). S1 should own box space.
- Screen recoveries are high in the baseline: Yellow 490, Blue 588, Red 115 per batch. Worth a look of its own.
- Yellow's Fighting Dojo gift (`43:gift:177:HITMONLEE`, 4 stalls in the S1 baseline) is put off by the generic 36000-frame "other" expedition budget, on efc9491 and later. No special case. S3 test case: a cheap one-time gift must outrank the generic budget, because its utility is high and its expected cost is a short walk.
- Fixed in #170 and deployed at 26390ca: Crystal kept a level 20 roam lead after every beast was caught, Crystal's storage goal flipped between two Pokémon Centers at the same distance, and Blue's guided detours jumped Route 22 ledges, which #150 exposed. None of these were band-aids, so they need no rows.
- Hunts the Gold and Silver League deadlock was hiding, and that show up once S1 #167 clears it, for S3 and S4. Gold's Golduck quality hunt on Route 6 takes 62.5% of frames with 12.1 wasted, and `hunt:114` stands down in all 3 saves. Silver's shiny hunt on Route 14 takes 55.9% with 28.1 wasted, because a shiny search logs no progress until a shiny appears. S4 needs a progress signal for shiny searches, or S3 needs to weigh their odds. Yellow's hunt projects (`78:fish:161`, `130:grass`, `166:grass`) time out inside collect_hunt.
- Fixed in #174: Gen 2 replanned during the wild-battle start transition and counted hunt battles as `collection_wait`. The bug came in with 3a94920.
