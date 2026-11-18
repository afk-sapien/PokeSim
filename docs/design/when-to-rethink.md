# When to rethink the goal

Status: proposal, nothing built. Every line number was read from main at `645b2b26` (#658). The numbers come from the November speed profiles in [Runtime map](../architecture.md#measured) and from a probe of the Gen II collection rungs on a late Gold save over one game hour. No new runs were made for this note.

The owner's question: why does the bot rerun its decision logic all the time, and should it?

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

| Measured | Gen I | Late Gen II |
| --- | --- | --- |
| Goal work, share of wall | ballot about 1% | `collection.journey` 32% |
| Pick equal to the previous pick | 99.4 to 99.9% | 79% |
| Inputs that differ from the previous call | not measured | 74% |
| Observe, share of wall | 25.6% | 16.6% (23.0% at four badges) |
| Observes that find no change | 69% | 33 to 36% |
| Decide's and observe's state reads | 3 to 8% of wall each | 3 to 8% of wall each |

The rung probe split 13.1 seconds of journey time over 2,675 calls, with its timers on:

- Training (2.4 s) and the hunt (2.2 s) were the only rungs that offered on every call.
- The other 24 rungs took 3.4 s, and most offered nothing.
- The `draft` copies and fingerprints outside the rung builds took 3.0 s. Ranking, deciding and the checks before the rungs took the rest.

## 2. The alternative: commit and follow

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

The inputs that change on nearly every call, and so explain the 74%, are mostly not on this list:

- position and the walk memory
- the decision counter `policy.decisions`
- the policy clock and the frame
- the hunt budget, which `observe_search` spends on every step (`gen2/collection.py:245-286`, `gen2/policy/__init__.py:267-268`)

Most of these choose where the running goal walks next, not which goal runs. The hunt, for example, picks its tile from the position and the visits on every call (`gen2/collection.py:1591-1605`). Under commit and follow they stay in the goal's own step.

The rungs that poll a decision counter need the timer instead: Lapras, the contest and the champion shop check (`gen2/collection.py:428-429`, `gen2/contest.py:95`, `gen2/champion_shop.py:367-370`).

## 3. What breaks

This changes behaviour. Today a new pick needs nothing but a new state. These are the cases where that is what keeps the bot going.

1. **Interrupted walk.** Gen I searches again when the next step no longer fits (`policies/navigation.py:761-769`) and blocks a failed direction (`policies/strategic.py:1986-1988`). Gen II routes again on every call (`gen2/navigation.py:377-405`). Handling: this is the follow step, not the pick, so it stays as it is.
2. **A battle or text on the way.** Gen II returns before the journey in battle and keeps the goal while a battle starts (`gen2/policy/__init__.py:326-328`, `:335`, `:340-341`). Gen I skips the overworld decision in battles and menus (`policies/strategic.py:708-874`). Both already hold the goal here. After the battle, the heal latch reads HP on every step (`policies/errands.py:48-64`). Handling: healing, forced moves and the boss check stay on every step, as interrupts above the goal. In Gen I they are the step ballot, about 1% of wall.
3. **A lost battle or black out.** The loss is recorded and the next ballot trains for the boss (`policies/strategic.py:557`, `gen2/policy/story.py:44-46`). Handling: a loss is an event, and the warp after a black out is a map change.
4. **A rung that becomes ready mid-walk.** Today a better rung wins on the next decision and pays only `INTERRUPT_FRAMES` (`gen2/collection.py:967`). Clock work starts on the first decision after its window opens (`:1248-1249`), and the contest walk stops once it is no longer a contest day or the contest is done (`gen2/contest.py:123-127`). Handling: a change of time of day or weekday is an event. What is lost: a rung whose value rises only because the player walked near it waits for the timer. This is the main behaviour change. Up to 21% of Gen II picks change today, and nobody has counted how many of those an event would catch.
5. **Stall recovery.** Gen I sets the last pick aside and restores (`policies/strategic.py:1937-1961`). Gen II parks or gives up and clears the goal (`gen2/emulator.py:808-813`, `:762-768`). Handling: these already end a goal, which is rule 2. The supervision ladder (`runtime/supervision.py:257`) does not change.
6. **A reload.** Handling: a reload is an event. The committed goal is not saved, so the first decision after a load picks fresh, as it does today.

There is also a cost that is easy to miss. The event table is a hand-kept list. A rung that reads an input missing from the list does not get a new pick on it until the timer fires. The journey cache that was turned down carried the same kind of risk. The timer bounds the risk, and the shadow in section 5 measures it.

Rungs that offer nothing still land writes today (`gen2/collection.py:958-964`, `:972-975`). In the probe, breeding wrote its phase on 2,351 of 2,675 calls while offering nothing. Each such write must be shown to be safe to skip, or kept.

## 4. Observe

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

A trial on Gen I ran only the clock parts of observe when nothing changed. It saved 7.5% and 6.1% of wall on two Red saves, under the 8% bar, and it needed a hand-kept list of the reads it skipped. It was dropped before a PR.

On Gen II only 33 to 36% of observes find no change, because NPC objects and the step count move (`packages/pokecore/src/pokecore/gen2/ram.py:441-445`, `:480`). Observe never reads the objects. The step count feeds only `progress_key` (`gen2/emulator.py:148`). A change test that ignores them needs its own list of ignored fields.

**One state read for decide and observe.**

- Staleness already needs no field list. Every memory write and every call outside a short read-only list, such as a tick, a press or a load, bumps the machine's generation counter (`packages/pokecore/src/pokecore/memory_snapshot.py:31-37`, `:72-78`, `:189-199`). The Gen I `read_snapshot` memo keys on it (`ram.py:369-379`). Gen II has no whole-snapshot memo.
- The two reads rarely see the same machine, though. Observe reads inside a press at a multiple of 30 frames (`runtime/emulator.py:232-233`, `:251-252`). Decide reads where the action ends, after more ticks, the release, the autosave and the guards (`runtime/game_loop.py:37-54`, `:115-127`).
- Sharing one read would mean deciding on a stale read, or moving observe to decision points. Moving it changes the cadence that the list above depends on.
- Gen I already shares the read when nothing ran in between. A Gen II memo like Gen I's would be a few lines with no field list. How many reads it would save is not measured.

## 5. Options

The options run from smallest to largest. For any option that changes behaviour, the old decision streams stop being a proof, because the picks differ by design. These checks replace them:

- a shadow first
- the ladder gate (59 rungs, stalls and time per rung against the baseline)
- stall counts on the stuck replays
- the stage results on the long saves

Any ladder baseline an option moves goes to the lead before the merge.

**Option 1: do nothing.**

- What: keep deriving the goal again at every decision.
- Ceiling: none. Late Gold keeps its 32%, and Gen I keeps its 1%.
- Code: nothing added or removed.
- Risk: none.
- Proof: not needed.

**Option 2: the Gen II collection rungs pick again only on events and a timer. The rest stays as it is.**

- What: between events, `collection.journey` asks only the rung that ran last (`policy.ladder_rung`, `gen2/collection.py:1255`) and the holds (`:1026`). On an event, or every 3600 frames, it asks every rung as it does today. The event test is a token like Gen I's `plan_token` (`policies/collection.py:1117-1125`). It covers party and box species, owned entries, event flags, the map, a money band, the time of day and weekday, the stand-downs still waiting, and the pin.
- Ceiling: in the probe, the 24 rungs that rarely offer took 3.4 of the 13.1 journey seconds. Most of the 3.0 seconds of copies outside the builds would go too. That is roughly 40 to 50% of journey, or about 13 to 16% of late Gold wall, minus the decisions where an event picks again. The share of event decisions is not measured, and the shadow would measure it.
- Code: about 40 to 60 new lines in `gen2/collection.py` plus tests. Nothing is removed. The token's field list is kept by hand.
- Risk: medium, and only after the Champion. It is case 4 above, plus the passive writes. An input the token misses waits up to 3600 frames.
- Proof: first a shadow on the long Gold and Crystal saves. It changes no behaviour and logs each decision where today's pick differs from the held one with no event. Then the switch, with the checks above on the Gen II rungs.

**Option 3: a shared commit-and-follow layer in `planning/` for both generations.**

- What: the layer holds the running offer, its end and failure tests, the event set and the timer. The ballot is built only when a new pick is due. Healing, forced moves and the boss check stay as interrupts on every step.
- It removes the commitment that is rebuilt today:
  - the trip resume (`planning/errand.py:54-58`, `policies/strategic.py:451-462`, `gen2/policy/__init__.py:237-246`)
  - the carry of the under-way mark in `latest` (`planning/decide.py:117-126`)
  - the errand filter (`policies/pipeline.py:142-144`)
  - `INTERRUPT_FRAMES` and `ladder_rung` (`gen2/collection.py:699`, `:875-876`, `:967`)
  - Gen I's `idle_token` (`policies/collection.py:1174-1176`)
- It adds the layer, and it splits every site and rung into a pick part and a follow part. Today one call does both. The hunt picks its tile while it makes its offer (`gen2/collection.py:1591-1605`). That is 26 Gen II rungs and about 20 Gen I sites.
- Ceiling: most of the 32% on late Gold, up to about 25%. The running goal's own step stays, and in the probe that was training or the hunt at 2.2 to 2.4 of the 13.1 seconds. Up to 1% on Gen I.
- Risk: high. Every decision stream in both generations changes, the story included.
- Proof: the same checks as option 2, on every ladder rung in both generations, with the shadow first. Every decision-stream baseline retires at once.

## 6. Recommendation

Option 1, do nothing.

The answer to the owner: the bot derives its goal again at every decision because that lets it recover from battles, black outs, reloads and stalls with no plan to repair. The next decision sees the new state and picks from it. Where commitment matters, latches already hold the goal, and Gen I's collection already commits and follows. The cost is about 1% on Gen I. Observe is mostly needed at its cadence, and its cheap split was tried and dropped under the bar.

The one real cost is the late Gen II postgame, at 32% of wall. Option 2 could recover about half of it. But it adds a hand-kept token of the kind the owner turned down twice, and it changes what the bot does after the Champion. Option 3 removes the rebuilt commitment, but it adds a split in about 46 places and changes every decision stream, for about 9 to 12 more points than option 2.

If postgame Gen II speed ever becomes worth a hand-kept list, build option 2 as a shadow first. Switch it on only if the shadow shows few missed picks.
