# Gen II rung builds

Status: PRs 1 to 4 built, the rest declined (3g). Every line number was read from main at `b1ebb9ff` (#665). Paths are under `pokesim/` unless they start with `tests/` or `data/`.

The question: how do the Gen II activities (the rungs) stop being asked and built again when nothing they read has changed, and how does the draft wrapper go away.

Every number below comes from the deep Gold and deep Crystal speed fixtures (`data/speed-fixtures`), run for 216000 frames at `b1ebb9ff` with the timers profiler, unless it says otherwise. Section 4 lists the raw output.

## The short answer

1. **Make the draft shallow.** Today every rung's build runs inside a deep copy and a roll back (gen2/collection.py:798). On the deep Gold save the draft's own work costs 6.67 s of a 57.8 s run, and on deep Crystal 10.46 s of 70.4 s. A draft that copies the collection, each monitor table and the milestones one level down, and compares them right after the build, measured 2.02 s and 3.65 s on the same runs. It needs one rule: a build replaces a collection value and never edits one in place. A test-only check holds every build to it. That is PRs 1 and 2, and they delete the pickle fingerprint (gen2/collection.py:749-796), the held copy and the per-decision token.
2. **Keep the costly pure helpers in Facts.** training.projects, the hunt's wanted list with its helpers, and the PC pick read a few snapshot regions that stage 2 already hands back as the same objects. That is PRs 3 and 4.
3. **Keep asking every rung at every decision for now.** Keeping whole rungs saves more on paper, about 10.4 s of the 16.6 s of build on deep Gold and about 22 s of 24.4 s on deep Crystal. But it needs each rung's reads named, by hand or by a recording proxy, and both are the machinery the speed rule turns away. Measure again after PR 4, and then consider it only for rungs whose draft writes nothing.

PRs 2 to 4 leave every decision as it is by construction. PR 1 can differ in one place only, a rejected build that edited an object some goal or menu task already held (section 3b). The trace sha on the deep saves shows whether that ever happens.

## 1. Today's model

At each Gen II decision, journey (gen2/collection.py:1113) writes the prerequisites list (:1129) and returns an activity under way if held() gives one (:1130-1134). Otherwise it offers up to 26 rungs in a fixed order (:1169-1210). Rungs.offer (:909) skips a rung whose best tier cannot beat the best offer so far (:918) and a rung the watchdog stood down (:920). Every other rung is built inside draft (:938). The deep Gold run drafted 90375 times in 3615 rung decisions, 25 a decision. Deep Crystal drafted 197424 times in 8226, 24 a decision.

draft (:798-841) does five things.

1. It collects the slots a build may write (_slots, :699-706): each collection key, each monitor table, the menu task and the milestones (`completed`).
2. It takes a deep copy of them (:826), unless it may reuse a copy held from an earlier draft that wrote nothing. Inside one decision a token (Rungs.token, :882) lets it reuse the copy while every slot still holds the same object (:819). Otherwise a pickle fingerprint of the slots decides (:822-824).
3. It runs the build. The price and the block run inside it, since they read what the build wrote, such as the hunt's new target (:931-937, hunt_price :1392, hunt_blocked :1405).
4. It compares every slot with the copy (:829-835), the menu task by identity and everything else with `!=` (_differs, :716-719). Each changed slot is a write. The milestones are deep copied again (:835), because putting them back clears and refills the dict the emulator shares (_set, :732-735).
5. It puts the copied values back (:836-837) and returns the writes.

The writes land by one rule (the Rungs docstring, :853-857):

- A picked rung's writes land when the pick commits (:1245).
- A rung that offers nothing lands them at once (:949-955), since they record what it saw. A League funding request there stops the later rungs (:954).
- A passive goal, the Day Care walk, lands them at once (:963-966).
- A goal that is blocked or has no route never lands (:943-948).
- A build that raises leaves its writes in place, since nothing is put back.

The survey (:1263-1292) is separate. It saves everything with _save (:709), runs one whole journey and restores with _restore (:740). Only a manager's goal list asks for it.

Three kinds of state sit outside the draft.

- Attributes a build sets on the policy or the map, never rolled back today: storage_pick (gen2/policy/storage.py:151-153), legend_decision (gen2/quests.py:129, read at gen2/battle.py:694), static_sleeper (gen2/quests.py:434, read at gen2/battle.py:692), _breeding_pairings (gen2/breeding.py:155), nav.objects (gen2/ruins.py:18-19 and gen2/quests.py:611) and _champion_idle (gen2/champion_shop.py:416).
- policy.decisions, which counts steps. observe raises it once a step (gen2/policy/__init__.py:264), never once an ask.
- The PlayClock (policy.clock), on which stand-downs are timed (gen2/standdown.py:118-126). Gen II budgets count decisions and waits count PlayClock frames (planning/monitor.py:7-11).

## 2. Measured at depth

### The draft's cost

draft_cost.py times draft, the build inside it, the fingerprint and the deep copy. Its build timer wraps built() (:931), so the build includes the price and the block.

| Measure | Deep Gold | Deep Crystal |
|---|---|---|
| Wall | 57.8 s | 70.4 s |
| Policy | 33.1 s | 46.5 s |
| Steps | 7129 | 8621 |
| Rung decisions | 3615 | 8226 |
| Drafts | 90375 | 197424 |
| Offer | 25.35 s | 36.92 s |
| Draft | 23.25 s | 34.81 s |
| Build | 16.58 s | 24.35 s |
| Fingerprint | 1.00 s in 10165 calls | 1.31 s in 16613 |
| Deep copy | 2.40 s in 10165 | 2.89 s in 15636 |
| Rest of the draft | 3.27 s | 6.25 s |
| **Draft minus build** | **6.67 s, 11.5% of wall** | **10.46 s, 14.9%** |

The rest of the draft is building the slot dicts, the compare and putting written slots back. The earlier cProfile figures for draft minus build, 15% on deep Gold and 17% on deep Crystal, carry the profiler's own overhead, so this note uses the timer figures.

The first rung of every decision takes a fingerprint and usually a deep copy, because the token is new each decision (:882) and observe changes the monitor tables between decisions. After that a draft copies again only after a rung that wrote.

| Save | Rung that copies | Copies | Fingerprint and copy | After whose write |
|---|---|---|---|---|
| Gold | super_rod, the first | 3615 | 1.27 s | the last decision's |
| Gold | prizes | 3466 | 1.14 s | breed's phase |
| Gold | champion_shop | 3080 | 0.99 s | store's errand |
| Crystal | super_rod, the first | 8226 fingerprints, 7249 copies | 2.01 s | the last decision's |
| Crystal | store | 8226 | 2.14 s | phones' wait marks |
| Crystal | legends | 153 | small | training's project |

So removing only the writes made at every ask, under today's draft, would save about 2.1 s on Gold (prizes and champion_shop) and 2.2 s on Crystal (store), and keep all the fingerprint code.

### A shallow draft, measured

shallow_cost.py wraps the real draft. Before each build it copies the collection dict, each monitor table and the milestones one level down. Right after the build it compares the collection values by identity, each monitor table and the milestones with one `==`, and the menu task by identity. The real draft still runs, so every decision is main's.

| Measure | Deep Gold | Deep Crystal |
|---|---|---|
| Copy | 0.659 s, 7.29 µs a draft | 0.836 s, 4.24 µs |
| Compare | 1.359 s, 15.04 µs | 2.818 s, 14.27 µs |
| Together | 2.02 s | 3.65 s |
| Today's draft minus build | 6.67 s | 10.46 s |
| **Saving** | **about 4.65 s, 8.0% of wall** | **about 6.81 s, 9.7%** |
| Drafts that saw a change | 10159 | 8387 |
| Collection keys, mean | 21.04 | 22.02 |
| Monitor table entries, mean | 745.6, at most 746 | 621.98 |
| Milestones, mean | 28 | 29 |

Putting changed values back was not timed. It is a few assignments in each draft that saw a change. A first version compared each table key by key and cost 90.28 µs a draft on Gold and 73.84 µs on Crystal, so the compare must test each whole table with `==` first and look inside only a table that differs.

Most monitor table values are numbers and failure names. The no-route attempts table holds dicts (planning/unreachable.py:40-45), but record() replaces a row whole and never edits one, so a one-level copy is still exact. PR 1's check would catch a later change to that.

### Build cost per rung

Clean timer runs, in seconds. "Draft minus build" for super_rod, prizes and champion_shop is the copying after another rung's write, above.

| Deep Gold | Build | Draft minus build |
|---|---|---|
| hunt | 5.95 | 0.19 |
| training | 3.73 | 0.16 |
| store | 1.61 | 0.16 |
| funding | 1.53 | 0.14 |
| hatching | 1.12 | 0.14 |
| contest | 0.98 | 0.12 |
| breed | 0.71 | 0.16 |
| npc_trades | 0.28 | 0.12 |
| peer_store | 0.19 | 0.14 |
| super_rod | 0.01 | 1.43 |
| prizes | 0.01 | 1.27 |
| champion_shop | 0.01 | 1.13 |

| Deep Crystal | Build | Draft minus build |
|---|---|---|
| training | 7.17 | 0.32 |
| hunt | 6.11 | 0.31 |
| funding | 2.05 | 0.27 |
| store | 2.00 | 2.44 |
| phones | 1.80 | 0.31 |
| npc_trades | 1.66 | 0.24 |
| hatching | 1.44 | 0.29 |
| contest | 1.12 | 0.25 |
| peer_store | 0.30 | 0.28 |
| pickups | 0.27 | 0.24 |
| legends | 0.06 | 0.32 |
| super_rod | 0.01 | 2.40 |

Where the build time goes, from cProfile (build_profile.py). cProfile inflates every call, so only the shares are used.

- Gold hunt, 11.12 s under the profiler: encounter_points (gen2/collection.py:111) 2.66 s, nav.local 2.60 s, supply_room (gen2/release.py:263) 2.12 s, the hopeless check (:1435) 1.15 s, standing_down 0.99 s in 176865 calls, item_hunts (:194) 0.67 s, pc_rated (gen2/policy/storage.py:43) 0.63 s.
- Crystal hunt, 17.11 s: hunted 11.76 s at 144 calls a build, inside hunt_wanted (:376-392, called at :390). Under it, own_wanted (:359) 4.66 s, item_hunts 5.01 s, supply_room 4.92 s and pc_rated 2.04 s overlap.
- training, 5.63 s on Gold and 12.32 s on Crystal: projects (gen2/training.py:173) 3.24 and 7.13 s, requested (:137) 2.43 and 4.69 s.
- Crystal phones, 3.97 s: storage_goal (gen2/policy/storage.py:123) 3.35 s, with 11 nav.walk calls an ask.
- Crystal store: needs (gen2/store_stock.py:252) and _targets (:200) 2.26 s.

From those shares, projects is about 58% of training's build, so about 2.1 s of clean time on Gold and 4.1 s on Crystal. hunted is about 69% of Crystal's hunt build, about 4.2 s. These are estimates until PRs 3 and 4 measure them.

### What each rung reads, and how often it repeats

rung_trace.py records, for each build, the snapshot fields, memory symbols, policy attributes, top-level collection keys and monitor keys it read, plus the goal, price and block it gave and the slots it wrote. "Same" counts asks whose reads equal the same rung's previous ask, at two levels.

- **L1** drops the raw PlayClock, reads a monitor stand-down time only as whether it has passed, and drops the postgame activity's progress frame.
- **L2** also drops policy.decisions, the position (x, y, facing), the frame, the tiles, the step count, the map objects and the Day Care struct.

Recording slows the builds by about 60% on Gold and 51% on Crystal, so this run's walls are not used.

| Deep Gold, 3615 decisions | Goals | Wrote | Landed | Same at L1 | Same at L2 | L2 same, goal differs | Distinct outputs |
|---|---|---|---|---|---|---|---|
| hunt | 3615 | 3460 | 3311 | 2144 | 3584 | 1187 | 222 |
| breed | 3615 | 3466 | 3311 | 2266 | 3582 | 0 | 3 |
| store | 3226 | 3080 | 3 | 44 | 3383 | 0 | 3084 |
| training | 0 | 0 | 0 | 2278 | 3610 | 0 | 1 |
| funding | 0 | 0 | 0 | 2279 | 3611 | 0 | 1 |
| champion_shop | | 4 | 4 | 0 | 3606 | | 5 |

| Deep Crystal, 8226 decisions | Goals | Wrote | Landed | Same at L1 | Same at L2 | L2 same, goal differs | Distinct outputs |
|---|---|---|---|---|---|---|---|
| phones | 8226 | 8226 | 7240 | 0 | 954 | 0 | 8226 |
| breed | 8226 | 1 | 1 | 8188 | 8196 | 0 | 2 |
| training | 985 | 153 | 12 | 8177 | 8177 | 0 | 18 |
| store | 114 | 2 | 2 | 8090 | 8186 | 0 | 5 |
| hunt | 0 | 0 | 0 | 8193 | 8193 | 0 | 1 |
| funding | 0 | 0 | 0 | 8203 | 8203 | 0 | 1 |

Every rung was asked at every decision. Outputs are the goal with its price and block. The rest repeat almost always at L1: on Gold hatching 3612, contest 3611, and super_rod, prizes, npc_trades, peer_store, pickups and the small quests about 3594 to 3614. On Crystal hatching 8189, npc_trades 8205, contest 8203, peer_store 8196 (28 goals, 1 write), pickups 8176. champion_shop wrote 4 times on Crystal and never repeated at L1, because it reads policy.decisions. tower and postgame were never asked with a build on either save.

At L1 no rung gave a different goal for the same inputs, on either save. So the recorded reads are complete enough to key a kept answer on these runs. At L2 the Gold hunt gave a different goal 1187 times, because its walk point depends on the position (gen2/collection.py:1582-1596).

What changed between asks, from the same run:

| Rung | Inputs that changed most |
|---|---|
| Gold hunt | PlayClock 3317, postgame progress frame 2466, y 710, x 651, decisions 159 |
| Gold training | PlayClock 3614, postgame progress frame 2466, Day Care 1332 |
| Gold store | frame 3226, decisions 3226, tiles 2145, Day Care 1332, step count 990, y 508, x 506 |
| Gold breed | Day Care 1332, frame 155, step count 150, tiles 150 |
| Gold funding | Day Care 1332, then party, items, pockets and money once or twice |
| Crystal phones | decisions 8225, phone_waits 7239 |
| Crystal training | PlayClock 7538, hatching 23, map 21, party 18 |
| Crystal hunt | party 18, stored 14, box counts 12, the training project 11 |

## 3. The questions

### a. Which rungs write during a build, what, and why

"Record" means the write keeps what the rung saw, such as a stand-down or a count. "Goal" means the write is part of the goal it offers, such as a target or a project, and matters only if that goal runs.

| Rung, build | Writes | Kind | Deep saves, wrote and landed |
|---|---|---|---|
| hunt, pokedex_hunt gen2/collection.py:1426 and hunt :1566 | target None :1450, a new target :1490, phase 'hunting' at every ask :1572, a stand-down and target None when no tile yields it :1579-1580, the same at :1619, forget LOADING for a postgame search :1630 | target and phase are goal. The stand-downs and the forget are record. | Gold 3460 and 3311, Crystal none |
| breed, gen2/breeding.py:159 | project :164 and :176, phase 'breeding' :181 whenever a project exists, also before the None returns at :194, :203 and :210, project None at those three, breed_withdraw :213. make_room: a stand-down and project None :83-84. nursery: nursery_end :90-92 | project and breed_withdraw are goal. phase is goal, written before the build knows it has one. nursery_end is record. | Gold 3466 and 3311, Crystal 1 and 1 |
| store, gen2/store_stock.py:282 | a stand-down and pop on timeout :286-289, a new errand stamped started=decisions :302, the amount edited in place :303 | goal. The started stamp makes every ask a write, since a new errand is made whenever the old one was rolled back. | Gold 3080 and 3, Crystal 2 and 2 |
| phones, gen2/item_sources.py:188 | forget :198, stand-downs :205, :208 and :215, _limited's item_sources dict cleared and refilled in place :111-118, _waited's phone_waits mark edited in place :131-134 and the wait budget it spends through exhausted :133 | record. Both count decisions. | Crystal 8226 and 7240, Gold none |
| training, gen2/training.py:218 | project None :227, :234, :248, :250, :273, :281, :295 and :304, a new project :268, species and target edited in place :276, site edited in place :283, take_slot :291 and :298, phase 'evolving' :302 | goal | Crystal 153 and 12, Gold none |
| hatching, gen2/breeding.py:281 | hatch_fill and hatch_ops popped :298-299, hatch_fill set :308 | goal, a fill trip under way | none |
| contest, gen2/contest.py:68 | new state stamped started=decisions :83, entered edited in place :86, pop :115, :121 and :126, the contest milestone :116 | goal. The milestone is record. | none |
| champion_shop, gen2/champion_shop.py:344 | pop :348 and :360, bought edited in place :355, a stand-down :359, champion_check = decisions plus CHECK_DECISIONS :361 and :368, a plan stamped started=decisions :372-373 | plan is goal. champion_check is record, when to look again. | Gold 4 and 4, Crystal 4 |
| legends, gen2/quests.py:116 | phase 'legendary' :126, legend_decision attribute :129, a stand-down :148 | goal | none |
| npc_trades, gen2/npc_trades.py:102 | the trade log appended in place by record() :97, npc_trade :119, phase 'trading' :120, pop :127 | the log is record. npc_trade and phase are goal. | none |
| tower, gen2/tower.py:166 | its state edited in place :203-215, :241, :245, :259 and :264, a stand-down :195, tower_result :222, the tower milestone :223, the training project put back :226 and :242 | goal | not asked |
| funding, start_funding gen2/collection.py:1080 | funding :1098, phase 'league' :1099 | goal | none |
| prizes, gen2/gamecorner.py:11 | prize :16, funding :28 | goal | none |
| lapras, gen2/collection.py:419 | a lapras stamp of decisions on the first ask :419, checked against 3000 at :420 | record | none |
| peer_store, gen2/collection.py:324 | peer_store_ops popped :327 | record | Crystal 1 |
| other quests, gen2/quests.py | roam_lead :288, roam_started :475, stone_show :590, nav.objects :611 | goal | none |

Other phase writers sit outside the rungs: gen2/kinds.py:122, :270 and :286, gen2/collection.py:642, :1042, :1099, :1224 and :1238.

Arrive writes run when a goal is reached, not in a build, so the draft never sees them: gen2/item_sources.py:240, gen2/quests.py:571, gen2/tower.py:277, gen2/breeding.py:358, :381 and :391, gen2/gamecorner.py:50, gen2/npc_trades.py:145 and :160-164, gen2/champion_shop.py:391, :394 and :398, gen2/collection.py:1715, :1722 and :1737, gen2/store_stock.py:318, and quests.pressed gen2/quests.py:74 from :545. consume (gen2/champion_shop.py:145) is a purchase callback from gen2/emulator.py:268.

Four builds write at nearly every ask on the deep saves, and each one costs a copy for the next rung under today's draft: breed's phase, hunt's phase and target, store's errand and phones' wait marks with the budget they spend. Only phones' writes are records the rung needs every ask. The other three are goal state written before the goal is picked.

**Recommendation.** Do not move these writes for speed alone. Under a shallow draft a write costs a few assignments, not a deep copy, so moving them saves little. Move them only if whole-rung keeping (PR 7) comes, since a rung that writes at every ask can never be kept.

### b. Can a build return its goal plus the writes it wants?

The plain form, a build that returns (goal, writes) and never touches the policy, breaks in four places.

1. **Reading its own writes.** The hunt's price and block read the target the build just chose (hunt_price :1392, hunt_blocked :1405, offer :931-937). Inside builds too: breed stores its project at :164 and then reads the state at :166 (brought_eggs). training makes its project at :268 and reads it to :302. tower reads its state across the whole function (gen2/tower.py:203-264). Each would need a layer that serves the build its own pending writes, which is hand-kept machinery.
2. **Goals and menu tasks hold objects.** The draft's docstring (:802-803) promises that a goal or menu task holding an object the build wrote holds the same object `write` lands. Returned writes keep that only if the goal is built from them.
3. **The milestones are cleared in place.** The emulator shares the `completed` dict, so a landed milestone write must clear and refill it (:732-735), never replace it.
4. **Stand-downs go through the monitor.** stand_down, forget and exhausted (gen2/standdown.py:36-58, :118) write the monitor tables inside shared code. Returning them means a second form of every monitor call.

**Recommendation.** Keep the builds writing into the live state, and change two things.

- **Copy-on-write in builds.** A build that changes a dict inside the collection replaces the top-level value with a new dict and never edits the old one. That covers store_stock.py:303, item_sources.py:111-118 and :131-134, contest.py:86, champion_shop.py:355, training.py:276 and :283, the tower state and the npc_trades log. Every other write is already top level.
- **A shallow draft.** Before the build, take `dict(policy.collection)`, a dict copy of each monitor table, `dict(policy.completed)` and the menu task reference. After it, a collection key is written when its value is not the same object, a table or the milestones when they compare unequal with `==`, and the menu task when it is not the same object. Put the old values back. Keep the milestone clear and refill, the landing rule, price and block inside the draft, and today's no roll back on an exception.

Together these give what returned writes would, without the overlay. The build reads its own writes because they are live. The old objects are never edited, so putting back the old top-level value is an exact roll back. A goal holding a new object holds the one `write` lands.

This removes the fingerprint code (:749-796), the held copy (:818-826 and :838-840), policy.draft_copy (gen2/policy/__init__.py:139), Rungs.token (:882) and the token argument. The survey keeps _save and _restore, since it runs a whole journey and is rare.

A copy-on-write rule needs a guard, or the next build that edits in place silently breaks the roll back. The guard is test-only: a fixture in tests/conftest.py wraps collection.draft, keeps a deep copy of each slot before the build, and after it fails when a slot holds the same object as before but no longer equals the copy. The tests and the stage_ladder gate both run under pytest, so the check covers both. A probe with the same check on the three deep saves goes under data/speed-probes/rungs/ and is not committed.

Where decisions could differ. Today a rejected build that edits a dict in place changes the object a goal or menu task may already hold, and the draft puts a copy back in the policy (:836-837). After copy-on-write the held object stays as it was. If any goal or menu task relies on seeing such an edit, decisions differ there, and the old behavior was the bug. The trace sha on the deep saves and the gate decide. I found no goal or menu task that holds a collection dict: store's Buy takes values at arrive (gen2/store_stock.py:322).

A second, harmless difference: a build that replaces a value with an equal new object counts as a write under an identity compare, where `!=` today sees none. It lands an equal value, so decisions do not change.

### c. What does each rung read, and can a rung declare its inputs?

The reads, measured by rung_trace.py (section 2):

| Rung | Reads | Changes every step? |
|---|---|---|
| hunt | Gold: position, PlayClock, decisions, monitor stand-down times, wUnownDex, party, stored, items, owned. Crystal gives no goal and reads no position. | Gold: yes, position and the clock |
| training | Day Care struct, wTimeOfDay, party, stored, owned, items, demand. Crystal also the map and the route. | the PlayClock, and the Day Care struct on Gold 1332 times |
| funding | Day Care, money, pockets, event flags | Day Care |
| store | nearly every snapshot field, decisions, frame, its own errand | yes, decisions and frame |
| breed | nearly every snapshot field | Day Care, position now and then |
| champion_shop | decisions against champion_check | yes, decisions |
| phones (Crystal) | phone_waits, wPhoneList, decisions, storage_pick, the route | yes, decisions and its own marks |
| contest | wCurDay, wStatusFlags2, wDailyFlags1 | no |
| pickups | wCurDay, wDailyFlags2, wTimeOfDay, wDailyPhoneItemFlags, wDailyRematchFlags | no |
| npc_trades | wTradeFlags, its trade log, policy.returned | no |
| super_rod, stones, ruins, tutors, gifts | event flags | no |
| prizes, legends, celebi | the owned set | no |
| tower, and phones on Gold | policy.data only | no |

Store reads nearly every snapshot field likely because `dataclasses.replace` at gen2/flight.py:43 and :84 copies the whole snapshot. I did not verify that.

What changes every step, and what would make each keepable:

- **The PlayClock.** Rungs read it to test stand-downs. L1 shows that reading a stand-down only as whether it has passed loses nothing. A kept answer would then hold until the earliest stand-down time it read.
- **policy.decisions.** Read as a stamp (store :302, contest :83, champion_shop :372, lapras :419) and against thresholds (store :286, contest :95 and :118, champion_shop :366, lapras :420, _limited). A kept answer would hold until the earliest threshold it compared with.
- **The Day Care struct.** It changed on 1332 of 3615 Gold asks. training, funding and breed would need to read only the fields they use, likely not the step counter. I did not check which field moves.
- **The Gold hunt's position.** pokedex_hunt picks species, map and method (:1426), and hunt then picks the nearest tile by distance and nav.local (:1582-1596). The choice could be kept and the walk point worked out each time. The position itself stays unkeepable.

Can a rung declare its inputs? Three ways, and the one I recommend:

1. **Hand-written input lists per rung.** Up to 26 lists that drift from the code they describe, each a source of a stale goal when it misses a read. This is the hand-kept machinery the speed rule turns away.
2. **A recording proxy**, as rung_trace.py does. It slows builds by 60% on Gold and 51% on Crystal while it records, and it must also know how to fold the clock, the progress frame and the stand-down times. It is general, but it is the largest piece of new machinery in any option.
3. **Facts on the costly pure helpers.** gen2/facts.py keeps one answer per question while its inputs compare equal, and stage 2 makes unchanged regions the same objects, so the compare is cheap. The inputs sit next to the function, as in the five callers today (gen2/policy/storage.py:52 and :54, gen2/collection.py:180, gen2/item_sources.py:68, gen2/release.py:295).

**Recommendation: 3.** The candidates, with their inputs:

- training.projects (gen2/training.py:173-216): party, stored, owned, items, the time of day, demand, and what prerequisites reads, since it works them out itself (:174-175). A build can call it twice, at :232 and :256.
- hunt_wanted's hunted and own_wanted (gen2/collection.py:359, :376), item_hunts (:194), supply_room (gen2/release.py:263) and encounter_points (gen2/collection.py:111, keyed on the map, the method, rare, and the collision object for the map).
- the PC pick in storage_goal (gen2/policy/storage.py:123), which phones and peer_store ask on every build.

Two traps for every Facts key. The prerequisites list is rebuilt every decision (:1129), so it compares equal but is never the same object, which costs a list compare. Any input edited in place, such as a dict on the policy, compares equal to itself after the edit, so a key must hold values that are replaced and never edited, or a copy of them. Each PR checks its keys for both.

### d. The counting side effects

| Counter | Where | What it counts | Changed if a rung is asked less? |
|---|---|---|---|
| _limited | gen2/item_sources.py:105-119 | decisions from start to now, started again after GAP (2000) decisions away | No. It reads policy.decisions. Its write lands only on a pick or a None. |
| _waited | :122-135 | spends the decisions since the last mark, capped at GAP, else 1 | No. The gap covers skipped asks. On Crystal 986 of 8226 marks were rolled back, and the next landed mark's gap already covered them. |
| stand_down and standing_down | gen2/standdown.py:118-126 | PlayClock frames | No |
| Monitor budgets (spend, exhausted) | gen2/standdown.py:36-54 | decisions in Gen II (planning/monitor.py:8-11) | No, as long as the caller passes decisions, as _waited does |
| Stamps checked against decisions | store :286, :302, contest :83, :118, champion_shop :361, :366, :368, lapras :419-420 | decisions since the stamp | No |
| goal_watch.expect | gen2/release.py:258-259 | called only from gen2/battle.py:95 and gen2/kinds.py:150 | Never reached from a build |
| hatch_ops and peer_store_ops | gen2/breeding.py:329, gen2/collection.py:337 | arrive steps at the PC | Arrive writes, never in a build |

Nothing counts asks. Every counter counts steps through policy.decisions, which observe raises once a step (gen2/policy/__init__.py:264), or PlayClock frames.

**Recommendation.** PRs 1 to 4 ask every rung exactly as today, so no counter can change. If whole-rung keeping comes later, one rule keeps the counters as they are by construction: reuse a kept answer only when its draft wrote nothing, and compute every write that lands in the decision it lands. phones writes at every ask, so it is never kept, and _limited and _waited run as today. A kept answer must also expire at the earliest stand-down time or decisions threshold it read, so the store timeout, the contest entry limit, champion_check and the Lapras limit still fire on the decision they do today.

Where decisions would differ, and only if PR 5 is built. Moving the phase write to the goal that runs changes the phase only where the last landed phase writer was not the goal that runs. Today breed lands 'breeding' through its None returns after :181, legends lands 'legendary' through its None return at gen2/quests.py:132, and a hunt pick writes 'hunting'. The phase steers play in one place only, gen2/ledger.py:581 and :585 (phase == 'legendary', the stocking and Ultra Ball rows), reached from gen2/errands.py:209. No rung reads it. legends never wrote the phase on the deep saves, so they stay identical. Elsewhere, a decision where legends landed 'legendary' and another goal then ran would keep or lose the Ultra Ball stocking differently. The ledger is meant to stock for a legendary that is the work now (the comment at gen2/ledger.py:591), so the goal that runs is the right source. The gate decides.

### e. The order to build it in

Each PR is proven alone by the full tests (data/operations/full-tests.sh), the stage_ladder gate, the trace sha on the deep Red, Gold and Crystal saves against its parent, and paired walls on deep Gold and Crystal. Red is a control, since Gen I has no draft. That adds about 45 minutes of runs to each PR.

| PR | What | Proof | Agent time |
|---|---|---|---|
| 1 | Copy-on-write for the in-place build edits listed in 3b, and the test-only purity check | identical sha, or a named difference from 3b | 2 to 3 h |
| 2 | Shallow draft. Delete the fingerprint, the held copy, draft_copy and the token. tests/test_gen2_draft.py keeps :63 and drops or rewrites :79, :135 and :181 | identical sha. Saves about 4.65 s on Gold and 6.81 s on Crystal | 2 h |
| 3 | Facts for training.projects | identical sha. Estimated 2.1 s on Gold and 4.1 s on Crystal | 2 h |
| 4 | Facts for hunted, own_wanted, item_hunts, supply_room, encounter_points and the PC pick | identical sha. Estimated 4.2 s on Crystal for hunted | 3 h |
| 5 | Phase set once from the goal that runs, only if PR 7 | sha identical on the deep saves, gate green | 1.5 h |
| 6 | Store errand and phone wait moved out of the build, only if PR 7 | identical sha | 2 h |
| 7 | Whole-rung keeping for rungs whose draft wrote nothing, with expiry, only if measured worth it after PR 4 | identical sha | to be sized after PR 4 |

PRs 1 and 2 could be one PR, but apart they prove different things: PR 1 that copy-on-write changes no decision under today's draft, and PR 2 that the shallow draft gives the same writes.

### f. What I would not do, and the simplest version

I would not:

- Write input lists by hand for any rung.
- Build a recording proxy into the policy.
- Change the landing rule in the same PR as the draft's shape.
- Key any kept answer on the position.
- Remove the survey's save and restore.
- Count asks anywhere.
- Turn every build into one that returns its writes.
- Move the phase and the decision stamps out of the builds for speed alone. That saves about 2.1 s on Gold and 2.2 s on Crystal and keeps all the fingerprint code.

The simplest version that removes the draft copy is PR 1 plus PR 2. It keeps asking every rung at every decision, keeps every write where it is, and replaces the deep copy, the fingerprint and the held copy with a one-level copy and an identity compare, about 4.65 s back on deep Gold and 6.81 s on deep Crystal.

### g. After PR 4

PRs 1 to 4 are merged (#667 to #670), and PRs 5 to 7 are not built. Measured at `d8444bbe` on the same saves, build fell from 16.6 s to 10.0 s on deep Gold (wall 43.0 s) and from 24.4 s to 15.5 s on deep Crystal (wall 56.4 s), and the draft costs 3.2 s and 6.1 s beyond its build. Keeping whole rungs would save at most 6.2 s on Gold and 15.0 s on Crystal, or 3.6 s and 10.8 s for the rungs whose draft writes nothing, before the cost of comparing reads, and it needs hand-named input lists or a recording proxy, so PR 7 is declined under the speed rule, and PRs 5 and 6 with it. Three corrections. PR 1 found in-place edits beyond 3b's list: the training project's goal run (GoalRun.replace now), postgame's record and its quality search counts, and the marathon's records. The snapshot copy behind store's wide reads is navigation.person at gen2/policy/navigation.py:69, which store's walk to the clerk calls (gen2/store_stock.py:305), not gen2/flight.py. Under the identity compare a build that puts back an equal new value counts as a write, so 3a's counts rise: Crystal training wrote 991 times where the fingerprint saw 152, Crystal store 115 against 2 and Gold store 3227 against 3080. Those writes land equal values, so no decision changed.

## 4. Raw output

Local only, under `data/speed-probes/rungs/`, which is ignored by git and survives a reboot. Nothing there is committed.

- `draft_cost.py`, `cost.sh`, `{gold,crystal}-deep-216000-cost.*`: the draft's cost.
- `shallow_cost.py`, `shallow.sh`, `{gold,crystal}-deep-216000-shallow2.*`: the shallow draft. The `-shallow.*` files are the first, key by key version.
- `rung_trace.py`, `stable.sh`, `{gold,crystal}-deep-216000-stable.*`: the reads, writes and repeats per rung.
- `build_profile.py`, `profile.sh`, `{gold,crystal}-deep-216000-profile.*`: the cProfile shares.
- `trace.sh`, `{gold,crystal}-deep-216000.*`: the first traced runs.
