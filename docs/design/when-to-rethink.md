# When to rethink the goal

Status: proposal, nothing built. Every line number was read from main at `e13bed4d` (#660).

The owner's question: why does the bot rerun its decision logic all the time, and should it?

**Postgame is the workload.** About 99% of simulation time comes after the Champion, and long-running adventures pass 10,000 game hours. This note weighs every option on the deepest saves on hand. The November profiles in [Runtime map](../architecture.md#measured) used saves about 110 game hours in, and the first version of this note followed them.

## 1. Today's model

At every decision each generation asks every source what it would do now, given the whole game state, and the decide pipeline picks one. The pipeline, its call sites and the state that survives between decisions are in [Runtime map](../architecture.md#the-decide-pipeline) and [Decide pipeline](decide-pipeline.md).

The stored goal is not a plan that the bot follows. It is one more input to the next ballot.

- A goal under way wins again only because its source offers it again, marked under way. `decide` then weighs it only against goals of its own kind (`planning/decide.py:117-126`, `:161-166`).
- The mark comes from each source's own latch. In Gen I these are the collection project, the pickup, the PC swap, the release and box visits, and the heal latch (`policies/strategic.py:560-628`).
- An errand picked earlier is offered again as it was picked (`planning/errand.py:54-58`, `policies/pipeline.py:150-156`, `gen2/pipeline.py:141-144`). Gen II rungs pay `INTERRUPT_FRAMES` to cut into the rung that ran last (`gen2/collection.py:699`, `:967`).

So the bot derives everything again and then rebuilds commitment out of latches.

Where it runs:

- **Gen I.** Every step that passes the early returns builds a ballot (`policies/strategic.py:490-536`, `:546-630`), about half of all decisions. Battles, menus and dialogue are handled next (`:708-874`). On the overworld the decision records the pick (`:1079-1094`).
- **Gen I collection already commits.** A project runs until it ends (`policies/collection.py:1171-1173`). With no project, the plan is not drawn again while `plan_token` is unchanged (`:1117-1125`, `:1174-1176`, `:1200-1203`).
- **Gen II.** Every step builds a ballot and calls the journey (`gen2/policy/__init__.py:339-343`). That walks every story check, then `kanto_journey`, then `collection.journey` (`gen2/policy/story.py:29-47`, `gen2/kanto.py:66-69`).
- **Gen II collection.** `collection.journey` builds new `Rungs` on each call (`gen2/collection.py:1145`), asks them, decides (`:1237`) and lands the pick's writes (`:1254`). Each asked rung builds inside `draft`, which copies the collection state when it cannot reuse the copy it holds (`:807-850`, `:835`). That is how only the pick's writes land. No result is reused across calls. The code says why: "The plan is rebuilt every step, so clock-gated work starts as soon as its window opens" (`:1248-1249`).

## 2. Measured at depth

Each run played one game hour, 216000 frames, from a copied save. Runs were niced, one at a time, with seed 7 and the Gen II clock pinned. They used the profile tool's timers (see [Runtime map](../architecture.md#measured)) and two scratch probes: timers around each Gen II rung, and wall timers around the functions a cProfile run pointed at. The probes add 1 to 6% of wall, so their shares run a little high. Shares are of the run's wall. Each figure is one run on one machine. The local environment has no numba, which the image uses for Gen I route searches, so Gen I routing here is an upper bound.

The deepest saves on hand are local copies of long-running adventures:

| Game | Game hours in | Save used before |
| --- | --- | --- |
| Red | 17,133 | 111 |
| Blue | 12,195 | none |
| Gold | 6,874 | 107 |
| Crystal | 6,680 | 152 |
| Silver | 6,104 | none |
| Yellow | 5,520 | none |

The deep Red save came with a backlog of League reward claims. Its first three hours retried them every 60 frames. Each try cloned the machine and rated the whole PC, then declined (339, 416 and 177 declines, taking 12.7, 20.3 and 10.4 seconds). The fourth hour had none, and new claims then arrive about 1.4 times per game hour. So the drain is a one-off, and the Red figures below come from the save once it ended.

| One game hour | Red, 17,133 h | Red, 111 h | Gold, 6,874 h | Gold, 107 h |
| --- | --- | --- | --- | --- |
| Wall | 38.2 s | 29.3 s | 68.3 s | 38.5 s |
| Frames per second | 5655 | 7372 | 3164 | 5603 |
| Memory (RSS) | 147 MiB | 116 MiB | 172 MiB | 162 MiB |
| Emulator | 23.2% | 29.0% | 14.5% | 26.9% |
| Policy | 27.7% | 19.9% | 67.8% | 42.6% |
| Observe | 25.0% | 25.8% | 9.2% | 16.7% |
| Autosave | 6.3% | 4.6% | 1.1% | 1.9% |
| Goal work | `decide` 0.5% of a cProfile run | ballot about 1% | `collection.journey` 50% | 32% |
| Journey result equal to the last one | not measured | not measured | 67% | 79% |
| Observes that find no change | 49% | 70% | not measured | 33 to 36% |

Deep Gold takes 30 more seconds per game hour than Gold at 107 hours, and nearly all of it is policy. Its emulator, observe and autosave seconds are the same at both depths. Deep Red takes 9 more seconds than Red at 111 hours: about 5 in policy, 2 of them in route searches, 2 in observe and 1 in autosave.

### What the bot does at depth

Neither bot is idle.

- **Red** has all 151 entries. Its hour went to four goals: a training goal to level 20 (24% of frames), the Kanto Marathon (23%), catching Zapdos (22%) and the Hitmonchan gift (17%). Restocking, box visits and healing took the rest. It walks. Following the objective took 40% of frames, choosing a move 22% and dialogue 15%. The hour at 111 hours was one training goal in battle for 84% of frames.
- **Gold** spent its hour on two hunts, fishing for Magikarp on Route 34 (53% of frames) and a Psyduck hunt in Ilex Forest (43%), and on buying a Thunderstone (3%). Battles took 36% of frames and item use 33%.

So the "nothing left to do" cost is per rung, not per bot. In the deep Gold hour, 22 of the 25 rungs asked offered nothing on any of the 3,615 journey calls, and they took 15.9 of the probe's 72.3 seconds.

### Where the deep Gold time goes

| Rung | Seconds | Offers in 3,615 calls |
| --- | --- | --- |
| hunt | 9.03 | 3,615 |
| training | 7.80 | 0 |
| hatching | 5.41 | 0 |
| store | 1.30 | 3,226 |
| funding | 1.19 | 0 |
| breed | 0.64 | 155 |
| contest | 0.62 | 0 |
| npc_trades | 0.27 | 0 |
| 17 others | 0.65 together | 0 |

The journey took 36.2 seconds, half the probe's wall. The rung builds took 26.9 of them, the `draft` copies and fingerprints outside the builds 6.1 (10,165 copies), and ranking, deciding and the checks before the rungs the rest.

Wall timers on the parts that grow with the PC. They nest, so they do not add up.

| Work | Gold, 6,874 h | Per call | Gold, 107 h | Per call |
| --- | --- | --- | --- | --- |
| Egg scan in `hatching`, twice per journey | 17.0% | 1.65 ms | 2.7% | 0.20 ms |
| `rating_key` | 12.9% | 155,445 calls | 1.1% | 5,350 calls |
| `pokedex_hunt` | 12.8% | 2.47 ms | 5.6% | 0.82 ms |
| `training.journey`, one egg scan inside | 12.3% | 2.38 ms | 6.2% | 0.91 ms |
| Full PC rate in battle | 10.4% | 6.63 ms, 1,095 rates | 1.3% | 106 rates |
| `training.projects` | 3.4% | 0.66 ms | 0.1% | 148 calls |

The egg scan is most of the training and hatching rungs. `hatching` asks whether any boxed egg is worth hatching (`gen2/breeding.py:290-291`). `keeps_hatch` keeps those answers until `rating_key` changes (`gen2/release.py:282-301`), but it builds `rating_key` again for every egg to look the answer up (`:293`). The key holds the party and the boxes and reads several stored settings (`gen2/policy/storage.py:29-41`). The deep save boxes 21 eggs, none worth hatching, so each scan builds the same key 21 times. The scan runs in the hatching rung and again at the start of `training.journey` (`gen2/training.py:222`). At 107 hours each scan sees one egg.

The full PC rate in battle comes from the catch rule. On an owned species met in an upgrade hunt, the battle asks whether the PC would keep the copy (`gen2/policy/battle.py:95`), and that rates the whole PC with the new copy added. `training.projects` asks `requested` for each project, and `requested` walks the party and the boxes again (`gen2/training.py:137`, `:173`), so its cost grows with the square of the PC.

### Where the deep Red time goes

| Work | Red, 17,133 h | Per call | Red, 111 h | Per call |
| --- | --- | --- | --- | --- |
| Snapshot decode | 13.6% | 0.36 ms, 14,671 calls | 16.0% | 0.34 ms, 14,018 calls |
| The 12 boxes inside the decode | 5.6% | 0.15 ms | 6.1% | 0.13 ms |
| Route search | 5.9% | 0.52 ms, 4,405 calls | 0.7% | 0.28 ms, 802 calls |
| `Store.get` | 5.8% | 159,874 calls | 4.9% | 155,795 calls |
| Reward poll every 60 frames | 3.6% | 0.42 ms | 4.2% | 0.38 ms |
| Step events in observe | 3.6% | 0.19 ms | 2.5% | 0.10 ms |
| Milestones in observe | 3.2% | 0.17 ms | 3.3% | 0.14 ms |
| Autosave | 6.3% | about 185 ms, 13 saves | 4.6% | about 112 ms, 12 saves |

Most Red costs are flat per call. The decode reads all 12 boxes at any depth. What grows is the autosave, as the stored state grew from 2.7 MB to 14.6 MB, and the step events. The route searches follow the walking mix, not the depth.

The top ten functions by own time in a cProfile run of the deep Red hour (74.9 s with the profiler) were `run_frame` 10.2%, `dict.get` 2.8%, sqlite commits 2.7% (16,341 of them), `milestones._goal_row` 2.7% (240 calls per observe), `navigation._neighbors` 2.7%, `deepcopy` 2.5% (8.2 million calls, mostly under `Store.get`), thread join 2.4%, `_deepcopy_list` 2.1%, sqlite execute 2.0% and `navigation.route` 1.7%. cProfile inflates code that makes many small calls, so the timers above give the real shares.

## 3. The alternative: commit and follow

Pick a goal, then follow it until one of these happens:

1. It ends, by its own done test.
2. It fails: no route, stuck, stood down or parked.
3. An event from the table below makes a new pick worth it.
4. A slow timer fires, say every 3600 frames (one minute of play), as a safety net for an input the table misses.

Between those, a step runs only the goal's own next step, such as where to walk or what to press. That step still reads the position and the walk memory every time.

| Event | What reacts to it today | Does observe see it today |
| --- | --- | --- |
| Party or box change | Gen I swap end and boss readiness (`policies/strategic.py:570-579`, `planning/league.py:181-203`), HM teaching (`policies/strategic.py:1606-1612`). Gen II breeding pairs and NPC trades (`gen2/breeding.py:105-111`, `gen2/npc_trades.py:102-128`) | Partly. Evolutions, levels and releases in the Gen I journal (`events.py:99-115`, `:145-151`, `:163`). The Gen II party token, hatch, evolve and level (`gen2/emulator.py:540`, `:620-635`) |
| Catch or Pokédex | Gen I `plan_token` reads `owned` (`policies/collection.py:1123`). Gen II hunt and Lapras (`gen2/collection.py:1435-1505`, `:420-461`) | Yes, a new owned entry (`events.py:117-132`, `gen2/emulator.py:577-579`) |
| Map change | Gen I passages and the pickup end (`policies/strategic.py:1047-1078`, `policies/pickups.py:60-70`). Gen II travel cost from the map (`gen2/collection.py:908-916`) | First visits only (`events.py:220-223`, `gen2/emulator.py:574-576`). Any change is one comparison of two snapshots |
| Badge or event flag | Gen I story goal (`policies/progression.py:107-124`). Gen II story checks and flag rungs (`gen2/policy/story.py:91-315`, `gen2/collection.py:1150-1157`) | Yes, badges (`events.py:137-139`, `gen2/emulator.py:590-593`) and story flags (`emulator.py:509-510`, `gen2/emulator.py:594-595`) |
| Money past a threshold | Gen I supplies (`policies/shopping.py:117-186`). Gen II funding, breeding, store and prizes (`gen2/collection.py:1089-1109`, `gen2/breeding.py:174`, `gen2/store_stock.py:282-305`, `gen2/gamecorner.py:25`) | No. The journal marks fixed money milestones, not these thresholds (`gen2/journal.py:94-96`) |
| Time of day or weekday | Gen II only: pickups, Lapras, contest, training, hunt and the clock wait (`gen2/item_sources.py:137-183`, `gen2/contest.py:68-128`, `gen2/training.py:241`, `gen2/collection.py:1453`, `:62-74`) | No. Observe reads the clock for status only (`gen2/emulator.py:539`) |
| Stand-down expiry | Every Gen II rung checks it (`gen2/collection.py:929`, `gen2/standdown.py:124-126`). Gen I `plan_token` holds the keys still waiting (`policies/collection.py:1124`) | No. It is a time, so the timer or the earliest expiry decides |
| Pin set or dropped | Gen I resets `idle_token` (`policies/collection.py:1639`). Gen II rungs read the pin (`gen2/collection.py:879-880`, `:988-1014`) | No. It comes from the manager |
| Stall climb or park | Gen I `recover_stall` (`emulator.py:806-814`, `policies/strategic.py:1937-1961`). Gen II `_park` and `_give_up` clear the goal (`gen2/emulator.py:808-813`, `:762-768`) | No. The guards do it, and they already end the goal |
| Reload | Gen I `on_restore` (`policies/strategic.py:245-324`). Gen II `load_state_dict` (`gen2/policy/__init__.py:150-190`) | No. The emulator knows, since it loads |
| Lost battle or black out | Gen I `note_boss_loss` (`policies/strategic.py:877-890`). Gen II the same (`gen2/policy/__init__.py:273-274`) | Yes (`events.py:157-158`, `gen2/journal.py:76`) |

On Gold at 107 hours, 74% of journey calls saw inputs that differed from the last call. The inputs that change on nearly every call are mostly not on this list:

- position and the walk memory
- the decision counter `policy.decisions`
- the policy clock and the frame
- the hunt budget, which `observe_search` spends on every step (`gen2/collection.py:245-286`, `gen2/policy/__init__.py:267-268`)

Most of these choose where the running goal walks next, not which goal runs. The hunt, for example, picks its tile from the position and the visits on every call (`gen2/collection.py:1591-1605`). Under commit and follow they stay in the goal's own step.

The rungs that poll a decision counter need the timer instead: Lapras, the contest and the champion shop check (`gen2/collection.py:428-429`, `gen2/contest.py:95`, `gen2/champion_shop.py:367-370`).

## 4. What breaks

This changes behaviour. Today a new pick needs nothing but a new state. These are the cases where that is what keeps the bot going.

1. **Interrupted walk.** Gen I searches again when the next step no longer fits (`policies/navigation.py:761-769`) and blocks a failed direction (`policies/strategic.py:1986-1988`). Gen II routes again on every call (`gen2/navigation.py:377-405`). Handling: this is the follow step, not the pick, so it stays as it is.
2. **A battle or text on the way.** Gen II returns before the journey in battle and keeps the goal while a battle starts (`gen2/policy/__init__.py:326-328`, `:335`, `:340-341`). Gen I skips the overworld decision in battles and menus (`policies/strategic.py:708-874`). Both already hold the goal here. After the battle, the heal latch reads HP on every step (`policies/errands.py:48-64`). Handling: healing, forced moves and the boss check stay on every step, as interrupts above the goal.
3. **A lost battle or black out.** The loss is recorded and the next ballot trains for the boss (`policies/strategic.py:557`, `gen2/policy/story.py:44-46`). Handling: a loss is an event, and the warp after a black out is a map change.
4. **A rung that becomes ready mid-walk.** Today a better rung wins on the next decision and pays only `INTERRUPT_FRAMES` (`gen2/collection.py:967`). Clock work starts on the first decision after its window opens (`:1248-1249`), and the contest walk stops once it is no longer a contest day or the contest is done (`gen2/contest.py:123-127`). Handling: a change of time of day or weekday is an event. What is lost: a rung whose value rises only because the player walked near it waits for the timer. This is the main behaviour change. A third of the deep Gold journey calls did not repeat the last result, and 21% at 107 hours. Nobody has counted how many of those an event would catch.
5. **Stall recovery.** Gen I sets the last pick aside and restores (`policies/strategic.py:1937-1961`). Gen II parks or gives up and clears the goal (`gen2/emulator.py:808-813`, `:762-768`). Handling: these already end a goal, which is rule 2. The supervision ladder (`runtime/supervision.py:257`) does not change.
6. **A reload.** Handling: a reload is an event. The committed goal is not saved, so the first decision after a load picks fresh, as it does today.

There is also a cost that is easy to miss. The event table is a hand-kept list. A rung that reads an input missing from the list does not get a new pick on it until the timer fires. The journey cache that was turned down carried the same kind of risk. The timer bounds the risk, and the shadow in section 6 measures it.

Rungs that offer nothing still land writes today (`gen2/collection.py:958-964`, `:972-975`). In the deep probe, breeding offered on 155 of 3,615 calls and wrote its phase on 3,466. Each such write must be shown to be safe to skip, or kept.

## 5. Observe

These parts of observe need the 30-frame cadence:

- Screenshot retakes, which wait for a fade to end (`emulator.py:466`, `:631-646`).
- Statistics, which count active frames, steps and damage between two observes and match gauges twice (`statistics.py:80-127`, `gen2/statistics.py:38-70`).
- Goal time, which adds the frames between calls (`goal_time.py:54-58`).
- Checks that must match on two observes in a row: tentative journal events (`emulator.py:526-531`), milestones (`milestones.py:133-136`) and the Gen II party token (`gen2/tracking.py:174-206`).
- Flushes driven by time, such as step counts every 30 seconds of wall time (`legendary_returns.py:68-72`, `gen2/steps.py:25-29`).

The stall watch stamps `stuck_frame`, `invalid_frame`, `battle_frame` and the Gen II screen key (`emulator.py:583-594`, `gen2/emulator.py:640-644`). They keep the first frame a condition was seen. If observe skipped a call, they would be late, not wrong.

The rest only needs to run when the state changed:

- the journal diff (`events.py:90`, `gen2/journal.py:57-97`)
- the map, Pokédex, badge and flag entries (`gen2/emulator.py:574-603`)
- the boss watch and progress highs (`emulator.py:504-510`)
- the release and PC notes, and hatch, evolve and level (`gen2/emulator.py:609-635`)

A trial on Gen I ran only the clock parts of observe when nothing changed. It saved 7.5% and 6.1% of wall on two Red saves about 110 hours in, where about 70% of observes found no change. It was dropped before a PR because it made the code worse. It needed a hand-kept list of the reads it skipped and a second path in `_observe` beside the full one. On the deep Red save only 49% of observes find no change, because the deep hour walks: the position changed on at least a quarter of observes. Scaled from the trial, the same skip would save about 4 to 5% there. That is an estimate, not a run.

On Gen II only 33 to 36% of observes find no change at 107 hours, because NPC objects and the step count move (`packages/pokecore/src/pokecore/gen2/ram.py:453-457`, `:492`). Observe never reads the objects. The step count feeds only `progress_key` (`gen2/emulator.py:148`). A change test that ignores them needs its own list of ignored fields. On the deep Gold save observe is 9.2% of wall, so a Gen II skip is worth little there.

**One state read for decide and observe.**

- Staleness already needs no field list. Every memory write and every call outside a short read-only list, such as a tick, a press or a load, bumps the machine's generation counter (`packages/pokecore/src/pokecore/memory_snapshot.py:31-37`, `:72-78`, `:189-199`). The Gen I `read_snapshot` memo keys on it (`ram.py:369-379`), and so does the Gen II one (`packages/pokecore/src/pokecore/gen2/ram.py:416-426`).
- The two reads rarely see the same machine, though. Observe reads inside a press at a multiple of 30 frames (`runtime/emulator.py:232-233`, `:251-252`). Decide reads where the action ends, after more ticks, the release, the autosave and the guards (`runtime/game_loop.py:37-54`, `:115-127`).
- Sharing one read would mean deciding on a stale read, or moving observe to decision points. Moving it changes the cadence that the list above depends on.
- Both generations share the read when nothing ran in between. The Gen II memo is the same few lines as Gen I's, with no field list. In one game hour it serves 1,499 of 14,930 snapshot reads on Gold at 107 hours and 1,655 of 14,648 at four badges. Most are a second `_read` in the same step or a read right after the reward check. It cuts about 0.4% of wall on both saves, with the same decisions and final state.

## 6. Options

For any option that changes behaviour, the old decision streams stop being a proof, because the picks differ by design. These checks replace them:

- a shadow first
- the ladder gate (59 rungs, stalls and time per rung against the baseline)
- stall counts on the stuck replays
- the stage results on the long saves

Any ladder baseline an option moves goes to the lead before the merge. The owner's speed rule applies to every option: a speed change ships if it leaves the code simpler or no harder to follow, and does not if it adds hand-kept machinery.

**Option 1: do nothing.**

- What: keep deriving the goal again at every decision.
- Ceiling: none. Deep Gold keeps half its wall in the journey.
- Code: the same.
- Risk: none.
- Proof: not needed.

**Option 2: the Gen II collection rungs pick again only on events and a timer. The rest stays as it is.**

- What: between events, `collection.journey` asks only the rung that ran last (`policy.ladder_rung`, `gen2/collection.py:1255`) and the holds (`:1026`). On an event, or every 3600 frames, it asks every rung as it does today. The event test is a token like Gen I's `plan_token` (`policies/collection.py:1117-1125`). It covers party and box species, owned entries, event flags, the map, a money band, the time of day and weekday, the stand-downs still waiting, and the pin.
- Ceiling: between events only the hunt (9.0 seconds) and the holds would run. The 22 rungs that offered nothing took 15.9 seconds, store and breed 1.9, and the copies outside the builds 6.1. That is up to about 24 of the probe's 72.3 seconds, a third of deep Gold wall, minus the decisions where an event picks again. After option 4 takes out the egg scans, about 14 seconds are left, about a fifth of the shorter wall. The share of event decisions is not measured, and the shadow would measure it.
- Code: worse. About 40 to 60 new lines in `gen2/collection.py` plus tests, nothing removed, and the token's field list is kept by hand. Under the owner's speed rule it does not ship.
- Risk: medium, and only after the Champion, which is where the sims spend their time. It is case 4 above, plus the passive writes. An input the token misses waits up to 3600 frames.
- Proof: first a shadow on the deep Gold and Crystal saves. It changes no behaviour and logs each decision where today's pick differs from the held one with no event. Then the switch, with the checks above on the Gen II rungs.

**Option 3: a shared commit-and-follow layer in `planning/` for both generations.**

- What: the layer holds the running offer, its end and failure tests, the event set and the timer. The ballot is built only when a new pick is due. Healing, forced moves and the boss check stay as interrupts on every step.
- It removes the commitment that is rebuilt today:
  - the trip resume (`planning/errand.py:54-58`, `policies/strategic.py:451-462`, `gen2/policy/__init__.py:237-246`)
  - the carry of the under-way mark in `latest` (`planning/decide.py:117-126`)
  - the errand filter (`policies/pipeline.py:142-144`)
  - `INTERRUPT_FRAMES` and `ladder_rung` (`gen2/collection.py:699`, `:875-876`, `:967`)
  - Gen I's `idle_token` (`policies/collection.py:1174-1176`)
- It adds the layer, and it splits every site and rung into a pick part and a follow part. Today one call does both. The hunt picks its tile while it makes its offer (`gen2/collection.py:1591-1605`). That is 26 Gen II rungs and about 20 Gen I sites.
- Ceiling: most of the journey except the running rung's own step. In the deep probe that is up to about 27 of the 36.2 journey seconds, about 37% of deep Gold wall, and about 17 seconds once option 4 is in. Gen I's `decide` is 0.5% of the deep Red cProfile run, so the Gen I share stays small.
- Code: mixed. It removes the five kinds of rebuilt commitment above, but it adds the layer, the same hand-kept event set as option 2, and a pick and follow split in about 46 places.
- Risk: high. Every decision stream in both generations changes, the story included.
- Proof: the same checks as option 2, on every ladder rung in both generations, with the shadow first. Every decision-stream baseline retires at once.

**Option 4: ask each whole-PC question once per PC change.** This option came out of the deep probe. It changes no decision.

- What: at depth the cost is whole-PC questions asked again on every decision, mostly by rungs that offer nothing. Their answers depend only on what `rating_key` covers, and two caches already keep answers per key (`gen2/release.py:294-301`, `gen2/policy/storage.py:43-52`). Start with the egg scan. Build the key once per scan instead of once per egg, or keep the scan's answer beside the answers it already keeps.
- Ceiling: the egg scans took 17.0% of deep Gold wall, 7,230 scans of 21 eggs. Once per scan leaves 7,230 key builds at about 0.06 ms, under 1%, so the ceiling is about 15% of deep Gold wall. At 107 hours each scan sees one egg, so the gain there is near zero.
- Code: the same or simpler. The cache is there already, and the key moves out of the loop. No new list.
- Risk: low. The key already decides when an answer is reused, so the same decisions come out.
- Proof: the same decisions and final state on the deep and the 107-hour Gold and Crystal saves, and the ladder gate.
- After it, measure again, then look at `pokedex_hunt` (12.8% of deep Gold wall, three times its cost per call at 107 hours) and `training.projects` (3.4%, quadratic in the PC) the same way. Neither is traced yet. The full PC rate in battle (10.4%) rates a different copy each time, so it has no cheap answer to keep.

**Red.** None of the four options moves Red. Gen I's collection already commits, and `decide` is 0.5% of the deep cProfile run. Red's costs at depth are the emulator, the snapshot decode, the autosave and the walking mix. Two items are worth tracing, each as its own change if it holds up:

- The autosave takes about 185 ms a save against 112 ms at 111 hours, as the stored state grew from 2.7 MB to 14.6 MB. The cause is not traced.
- The reward poll is 3.6% of wall. It decodes a snapshot every 60 frames and only then asks whether a claim waits (`runtime/reward_delivery.py:127-137`, `:279-284`). Asking first would need the unlock record it keeps (`:136`) to move to observe.

The parked observe skip would save about 4 to 5% at depth and still needs its read list, so it stays parked.

## 7. Recommendation

Option 4, starting with the egg scan, and nothing else yet.

At depth the bot is busy, not idle. But most of the Gen II ladder has nothing to offer and still works out whole-PC answers on every decision to say so. The largest piece is the egg scan, which builds the same key 21 times where once is enough. Building it once removes about 15% of deep Gold wall, changes no decision and leaves the code the same or simpler. Then measure again, and take `pokedex_hunt` and `training.projects` the same way.

Option 2 has the largest ceiling left after that, about a fifth of deep Gold wall. Its token is a hand-kept list, so under the owner's speed rule it does not ship. Its shadow changes no behaviour and would measure how many picks an event misses. Build the shadow only if the owner wants to weigh the token against that number. Option 3 needs the same list and a split in about 46 places, for about 4 to 5 more points than option 2.

For Red, no goal option applies. The autosave and the reward poll are the items to trace.

The answer to the owner: the bot derives its goal again at every decision because that lets it recover from battles, black outs, reloads and stalls with no plan to repair. The rederiving itself is cheap. What costs at depth is the work each Gen II rung does to find it has nothing to offer, and that work grows with the PC. It can get cheaper without changing how the bot decides.
