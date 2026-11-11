# Ladder gate rungs suspected of regressing, 2026-11-09

The gate baseline in `gate-baseline.json` was taken at 171176e on 2026-11-08. Main went 135 commits
past it with no new baseline, so the gate failed on 26 of its 59 rungs. This list keeps those 26 before
the baseline moves, so accepting the current state does not hide them.

The new values come from one gate run on 2026-11-09 of 1be5e711, the main commit at the time, plus a
tooling-only change that touches no play code. Each rung plays 108000 frames (30 game minutes).
Wasted is the share of frames the replay audit counts as wasted. The list is sorted by how much it rose.

| Rung | Wasted at 171176e | Wasted on main | Change | Stall on main |
| --- | ---: | ---: | ---: | --- |
| crystal/post_game | 0.0% | 32.1% | +32.1 | |
| silver/badges_6 | 1.3% | 25.9% | +24.6 | a retry loop: route:red_gyarados:LAKE_OF_RAGE:18,23 stood down 4 times in a row |
| gold/new_game | 5.7% | 23.7% | +18.0 | |
| gold/badges_6 | 0.0% | 17.3% | +17.3 | |
| gold/red | 0.0% | 15.5% | +15.5 | |
| silver/new_game | 0.3% | 12.4% | +12.2 | |
| gold-randomized/new_game | 0.2% | 12.2% | +12.0 | |
| yellow/badges_4 | 11.8% | 23.6% | +11.8 | |
| crystal/new_game | 3.9% | 15.7% | +11.7 | |
| silver/post_game | 0.0% | 11.0% | +11.0 | |
| yellow/post_game | 15.0% | 24.3% | +9.3 | |
| blue/post_game | 6.1% | 15.0% | +8.8 | |
| red/post_game | 9.1% | 17.8% | +8.6 | |
| crystal/badges_2 | 0.0% | 8.5% | +8.5 | |
| gold/badges_2 | 0.0% | 8.5% | +8.5 | |
| crystal/red | 0.0% | 8.2% | +8.2 | |
| yellow/badges_6 | 13.4% | 21.5% | +8.1 | |
| silver/red | 12.6% | 17.3% | +4.8 | |
| crystal/kanto_entry | 0.0% | 4.5% | +4.5 | |
| blue/badges_6 | 7.3% | 11.8% | +4.4 | |
| gold-randomized/badges_8 | 0.0% | 3.4% | +3.4 | |
| blue/badges_2 | 13.0% | 16.2% | +3.2 | a retry loop: route:bill:88 stood down 4 times in a row |
| silver/kanto_entry | 6.0% | 8.8% | +2.8 | |
| gold/post_game | 0.0% | 2.7% | +2.7 | |
| yellow/badges_2 | 3.9% | 6.1% | +2.3 | a retry loop: route:bill:88 stood down 4 times in a row |
| red/badges_6 | 12.6% | 14.8% | +2.2 | |

No rung had a stall at 171176e, and no rung raised an error in either run. The three stalls above are new.

## Suspects

These merges between the two points change play:
#344, #346, #353, #354, #357, #358, #359, #373, #378, #379, #382, #383, #389 and #392.

#375 also keyed the replay audit's goal seeds by `--seed` as well as the save, so the two runs did not
meet the same goal rolls. Part of a rise can come from that change and not from play.

The worst ones are the first cases for the replay tooling in the phase 1 design note.

## Causes found

- #389, 2026-11-10: in a Gen II ledge jump the coordinates read the wall tile jumped over, which is in
  no map region, so the walk recorded a missing route and looked around for 150 decisions. With that
  fixed, gold/new_game, silver/badges_6, gold/badges_6, silver/new_game, gold-randomized/new_game,
  crystal/new_game, crystal/badges_2, gold/badges_2, crystal/kanto_entry, gold-randomized/badges_8,
  silver/red and silver/kanto_entry are back at or below their 171176e values, and the baseline moved
  for them. silver/post_game fell to 2.3% and crystal/red to 6.3%, still above 171176e.
- #376, 2026-11-10: the training site picker and the hunt judged reach from that same wall tile, found
  no route, and ended training. A Crystal postgame run outside the Silver Cave stood down one trainee
  after another. They now wait for the jump to land. crystal/post_game, gold/post_game and
  silver/post_game are back at 0.0%, and the baseline moved for them.
- #389, Gen I, 2026-11-10: a trainer who spots the player holds them still until the battle starts. Each
  step tried then counted as a wall, so on Route 25 every side got blocked while a trainer walked up,
  and the walk to Bill found no route four times in a row. A step tried while a trainer engages no
  longer counts. The blue/badges_2 and yellow/badges_2 stalls are gone, and the baseline moved for
  blue/badges_2, yellow/badges_2, blue/post_game, red/post_game, yellow/badges_4, yellow/post_game and
  red-randomized/badges_4. red/badges_4 moved up to 20.8%, although it plays better. It reaches Mr.
  Fuji at frame 96970 of the rung, not 102510. Its whole rise is one 8422-frame trip back to the
  hideout for the Silph Scope. Before the fix that trip took 18066 frames, with a missing route and a
  trainer blocking every side again. That trainer's battle gave experience, so the audit counted the
  detour as progress.
- The Silph Scope trip back, 2026-11-10: Giovanni's battle ends one step from the Scope, and the heal
  it latched went first. A goal that picks up an item ball at most four steps away on the same map now
  goes before a latched heal. The Scope takes 84 frames, and red/badges_4 fell to 12.3%. The baseline
  moved for it.
- #346, gold/red and crystal/red, 2026-11-10: the boss check heals before Red, and with that heal both
  runs beat Red inside the window. Their rise is postgame play the 171176e runs never reached. Part of
  it was the replay audit's: a Pokémon Center visit that makes another box the current one moved no
  held count, so the whole visit counted as waste. A box change now counts as progress. crystal/red
  fell to 0.3% and gold/red to 9.7%, and the baseline moved for both.
- gold/red, still open as a catch strategy item and not a regression: 10424 frames of buying balls. The
  run throws at a full-HP Tangela that its lead cannot weaken, runs out of balls and buys more.
- yellow/badges_4 and red/badges_6, 2026-11-10: the rest of their rise was the replay audit's. Both runs
  fill the bag to 20 entries, and a restock sells one item. A sale gains no item, so the trip counted as
  waste. In Yellow the run picks up one more item ball in the Rocket Hideout than at 171176e, the Silph
  Scope made 20 entries, and the sale at the Lavender Mart was on the way to the tower. In Red the Surf HM
  and the Gold Teeth each filled the bag in the Safari Zone, and the sales were at the Fuchsia Mart. A restock that sells now counts as progress. yellow/badges_4
  fell to 13.1% and red/badges_6 to 11.5%. blue/badges_8, red/badges_8, red-randomized/badges_8 and
  yellow/badges_8 fell to 0.1%. The baseline moved for all six. yellow/badges_4 keeps 1520 frames of two
  restock spans that a battle and the hideout elevator cut short before the sale.
- #358, red/post_game, blue/badges_6 and yellow/badges_6, 2026-11-10: a bisect names #358 for all three. In red/post_game
  the run now catches a better Dugtrio copy in Diglett's Cave, so the party is full when the Eevee gift
  comes, and a deposit at the Vermilion Pokémon Center makes room. A deposit keeps the held count, so
  the audit counted the whole visit as waste. A deposit under the party space goal now counts as
  progress. red/post_game fell to 6.0%, yellow/post_game to 3.7% and blue/post_game to 5.2%, and the
  baseline moved for all three.
- blue/badges_6 and yellow/badges_6, still open as a strategy item and not a regression: with #358 each
  run throws a ball where its parent fought, and from there both reach Route 15 with a bag of 19 or 20
  entries and no cure. Any status leaves the walk no HP budget, so a poison at 164 of 169 HP sends the
  run back to a Pokémon Center, and the heal cuts a long walk short before any event. Yellow makes four
  such trips to Fuchsia under the lapras goal, 16072 frames. Outside the League the run uses no cure in
  the field, and the shop skips a new item kind at 18 entries or more. Both rules are older than 171176e.
- The field cure, 2026-11-10: a status a cure in the bag can treat no longer latches a heal, and the run
  cures it where it stands. A mart with no Antidote sells a first Full Heal into a bag of 18 or 19
  entries while a finite TM could still be sold for a story item. The four Fuchsia trips are gone.
  yellow/badges_6 fell to 14.2% and red/badges_6 to 9.0%, and the baseline moved for both. blue/badges_6
  did not move. Both runs now train a partner on Route 11 for about 55000 frames and reach the Safari
  Zone too late to get Surf inside the window. Training ends only on a level or 2400 frames without
  experience, and a level 41 partner on level 15 grass gains a little in every battle. That stall is
  older than 171176e and is still open.
- The training skip, 2026-11-10: a partner whose next level would take more than ten wild battles on the
  map is not trained there. Training waste fell from 9420 to 880 frames in yellow/badges_6 and from 9260
  to 3480 in red/badges_6. Both runs now get Surf, the Gold Teeth and Strength and teach both HMs, and
  Yellow starts on the Secret Key. yellow/badges_6 rose to 26.6% on goals the old window never reached.
  teach_surf is wasted in full in both runs, 2502 frames in Yellow and 3480 in Red, and the restock after
  Surf wastes 5688 in Yellow. The lead accepted the rise for this rung alone and its baseline moved up.
  red/badges_6 is 9.5%, inside the gate. The teach_surf and restock waste are open, and each fix brings
  the baseline back down.
- The taught move, 2026-11-10: an HM or TM taught to a party member stays in the bag in Red, Blue and
  Yellow, so a lesson changed no count the audit read, and every teach span was wasted. teach_strength
  was credited only because the HM04 pickup fell in its span. The audit now counts a move a party
  member learned as progress. teach_surf waste fell from 2502 to 0 frames in yellow/badges_6 and from
  3480 to 1332 in red/badges_6, and teach_battle waste fell to 0 in the three post_game rungs. The
  baseline moved down for yellow/badges_6 to 24.2%, red/badges_6 to 7.5%, red/post_game to 3.6%,
  yellow/post_game to 1.8% and blue/post_game to 4.0%. The run itself did not change.
- The restock after Surf, 2026-11-10: the audit ended a goal's span at every battle, and a wild battle
  on the way to the mart ended the restock span before the purchase. The audit counted the walk to the
  battle as waste and the rest of the trip as a new span. A battle on an errand's way now pauses the
  span, and the errand resumes it after. Restock waste fell to 0 in yellow/badges_6 from 5688 frames,
  in blue/badges_4 from 5856, in red/badges_4 from 3252, in blue/badges_6 from 2760 and in red/badges_6
  from 2430, and to 420 in yellow/badges_4 from 1520. The baseline moved down for yellow/badges_6 to
  19.0%, blue/badges_4 to 20.2%, red/badges_4 to 9.3%, blue/badges_6 to 9.2%, red/badges_6 to 5.3%,
  yellow/badges_4 to 12.1%, yellow/new_game to 1.1%, red-randomized/new_game to 1.3% and
  blue/badges_2 to 7.5%. The run itself did not change.
- The Gen II field cure, 2026-11-10: Gold, Silver and Crystal had the same three gaps in their own code.
  A status a cure in the bag can treat no longer latches a heal, the run cures it where it stands, and a
  mart that sells an Antidote or a Full Heal stocks two for a bag without a cure. gold/red fell to 0.0%,
  and the baseline moved for it. The run now makes one ball restock inside the window, not two. Main's
  second restock was the Tangela throws, and they no longer fall inside the window, so that catch item
  is still open.
- The long-odds catch, #463, 2026-11-10: a throw under 1 in 10 now weakens its target first, with a
  switch to a member that outlasts the target's best hit. A target nobody can weaken is left until a new
  move, member or ball. Gold, Silver and Crystal had the bigger gap, and this closes the Tangela item.
  No rung moved down. gold/badges_4, silver/badges_6 and silver/badges_8 rose inside the tolerance and
  each plays its window differently, so the baseline stays.
- The gate's story milestones, 2026-11-10: each rung in the baseline now lists the story milestones its
  run earned inside the window, taken from a gate run at d918a2d1 on top of #463. No waste, stall or
  error value moved. 16 rungs earn at least one milestone: every new_game rung, the champion_first and
  kanto_entry rungs of Gold, Silver and Crystal, and gold/red and crystal/red. A rung that later earns more passes with a flag while its waste
  stays within 10.0 points of this baseline, and one that earns fewer fails.
- The ledge-hop restock, #469, 2026-11-10: in a ledge hop the player stands on the wall tile, which is
  in no region, and the Gen II shop dropped the chosen mart for that decision. The walk to Olivine Mart
  drops three ledges on Route 39, so gold/badges_4 cut its restock into four spans. The shop already
  chosen now stays the goal until the player lands. gold/badges_4 is back at its 0.0% baseline, and
  silver/badges_6 and crystal/red fell to 0.0%, so the baseline moved for those two.

## Where each rung ended

Now is the gate baseline after #469. The cause names the merge that brought the rise, where one did.

| Rung | 171176e | 2026-11-09 | Now | Cause | Fixed by |
| --- | ---: | ---: | ---: | --- | --- |
| crystal/post_game | 0.0% | 32.1% | 0.0% | training judged reach from a ledge's wall tile (#376) | #441 |
| silver/badges_6 | 1.3% | 25.9% | 0.0% | a Gen II ledge jump read the wall tile (#389) | #439, #469 |
| gold/new_game | 5.7% | 23.7% | 5.7% | the ledge wall tile (#389) | #439 |
| gold/badges_6 | 0.0% | 17.3% | 0.0% | the ledge wall tile (#389) | #439 |
| gold/red | 0.0% | 15.5% | 0.0% | postgame play past Red (#346), a box change the audit missed, no field cure | #447, #453 |
| silver/new_game | 0.3% | 12.4% | 0.3% | the ledge wall tile (#389) | #439 |
| gold-randomized/new_game | 0.2% | 12.2% | 0.2% | the ledge wall tile (#389) | #439 |
| yellow/badges_4 | 11.8% | 23.6% | 12.1%, open | a step tried while a trainer engages counted as a wall (#389), a sale and a split restock the audit missed | #445, #449, #459 |
| crystal/new_game | 3.9% | 15.7% | 3.9% | the ledge wall tile (#389) | #439 |
| silver/post_game | 0.0% | 11.0% | 0.0% | the ledge wall tile (#389, #376) | #439, #441 |
| yellow/post_game | 15.0% | 24.3% | 1.8% | the trainer step (#389), a deposit and a taught move the audit missed | #445, #450, #457 |
| blue/post_game | 6.1% | 15.0% | 4.0% | the trainer step (#389), a deposit and a taught move the audit missed | #445, #450, #457 |
| red/post_game | 9.1% | 17.8% | 3.6% | the trainer step (#389), a deposit for the Eevee gift (#358), a taught move | #445, #450, #457 |
| crystal/badges_2 | 0.0% | 8.5% | 0.0% | the ledge wall tile (#389) | #439 |
| gold/badges_2 | 0.0% | 8.5% | 0.0% | the ledge wall tile (#389) | #439 |
| crystal/red | 0.0% | 8.2% | 0.0% | the ledge wall tile (#389), postgame play past Red (#346), a box change | #439, #447, #469 |
| yellow/badges_6 | 13.4% | 21.5% | 19.0%, open | heal trips for a status with no field cure (#358), long partner training, a taught move and a split restock | #451, #454, #457, #459 |
| silver/red | 12.6% | 17.3% | 0.0% | the ledge wall tile (#389) | #439 |
| crystal/kanto_entry | 0.0% | 4.5% | 0.0% | the ledge wall tile (#389) | #439 |
| blue/badges_6 | 7.3% | 11.8% | 9.2%, open | heal trips (#358), a split restock | #459 |
| gold-randomized/badges_8 | 0.0% | 3.4% | 0.0% | the ledge wall tile (#389) | #439 |
| blue/badges_2 | 13.0% | 16.2% | 7.5% | the trainer step (#389), a split restock | #445, #459 |
| silver/kanto_entry | 6.0% | 8.8% | 0.0% | the ledge wall tile (#389) | #439 |
| gold/post_game | 0.0% | 2.7% | 0.0% | training reach from the wall tile (#376) | #441 |
| yellow/badges_2 | 3.9% | 6.1% | 2.6% | the trainer step (#389) | #445 |
| red/badges_6 | 12.6% | 14.8% | 5.3% | a sale the audit missed, no field cure, a taught move, a split restock | #449, #451, #457, #459 |

## Open strategy items

None of these is a regression. Each is play the 171176e runs did not reach, or did the same way.

1. yellow/badges_6, 19.0%: the run now reaches the Secret Key. Its waste is the Safari Zone and Surf
   goals: surf 10270 frames, party_surf 3688, teeth 2344 and party_upgrade 1676.
2. blue/badges_6, 9.2%: surf 7220 frames and lapras 2024.
3. The Rocket Hideout elevator: 19984 frames in blue/badges_4 and 5612 in yellow/badges_4.
4. red/badges_6: train_partner 3480 frames and teach_surf 1332. red/badges_2 is at 4.0% against a 3.5%
   baseline on main, with bill 2404 and surge_switches 1804, inside the gate.
5. Gen II ball restocks: closed by #469. Each restock span that gained nothing was cut by a ledge hop,
   and gold/badges_4, silver/badges_6 and crystal/red now count no restock waste.
