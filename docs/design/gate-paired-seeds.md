# Gate: paired seeds on a failing rung

Status: approved by the lead on 2026-11-26 with the answers in section 7. The paired stage is built (PR 1). The restock, heal and PC shares are built, with restock judged (PR 2).

The ladder gate (`tools/stage_ladder.py gate`, `pokesim/replay/rung.py`) plays 30 game minutes from each of 59 rungs on goal seeds 7, 8 and 9. It fails a rung whose mean wasted share rises more than 2.0 points over `tools/ladder/gate-baseline.json`. This note proposes two changes: judge a rung that fails on waste on paired extra seeds, and charge the time a restock takes.

## 1. Why three seeds fail on changes that cost nothing

1. `GoalSeeds` reseeds the policy and the game's random bytes at every goal start, keyed by the goal key and its count. A change that adds, drops or renames a goal start gives the run other numbers from that point on, with no play change.
2. On blue/badges_4 the wasted share has a per-seed standard deviation of 5.1 points. A 3-seed mean then moves about 2.9 points on any such shift, more than the 2.0 limit.
3. The battle goal fix, 2026-11-26: blue/badges_4 failed by 2.13 points on seeds 7 to 9. On 23 paired seeds the difference was +0.56 points, standard error 0.82.
4. The Mt. Moon fix, 916bba2a: blue/post_game failed by 3.2 points and red/badges_6 by 2.6. On 23 paired seeds they gave +0.44 (standard error 0.57) and +1.65 (0.98).

Each case took a hand run and a lead decision before a baseline moved.

## 2. Proposal: a paired stage

1. The 3-seed gate stays the first screen, unchanged. It took 228 s for 59 rungs at 10 jobs on the last preflight.
2. A rung that fails only on its wasted share goes to a paired stage. A new stall, more errors or fewer milestones fail as now.
3. The paired stage checks out the merge base with origin/main in a temporary worktree. It plays the rung there on seeds 7 to 29, and on the head on seeds 10 to 29, since the screen already played 7 to 9. Both trees use `gate-rung`, so each seed meets the same rolls on both until the first goal start they do not share. On main the merge base is the head itself, so there the screen's verdict stands.
4. It judges the mean paired difference over the 23 seeds against a 1.0-point limit. The gate report lists the 23 pairs, the mean, the standard error and the median, pass or fail. A paired failure also prints the per-goal frame sums on both trees, so the reviewer sees where the frames went.
5. A rung that passes this way keeps its baseline. A baseline move stays a reviewed change.

On the three rungs measured, the two harmless shifts pass at 1.0 (+0.56 and +0.44). The first Mt. Moon version fails red/badges_6 at +1.65, which was a real cost of 17 story throws. A 2.0 limit would have passed it.

## 3. Restock time

1. A span counts as wasted only when no progress event lands in it (`close` in `run_one`). Any item the bag gains is a progress event (`events` in `pokesim/planning/progress.py`). So a restock that walks for 50 minutes and then buys one Poké Ball counts as all progress.
2. On the Mt. Moon branch 916bba2a, blue/post_game, 23 paired seeds: main spent 8596 frames under the restock goal on 6 seeds, the branch 165090 frames on 20 seeds, 6.6% of all its frames. The gate saw +0.44 points of waste.
3. Proposal: the gate keeps a restock share for each rung, the frames under the restock goal over all frames, next to the wasted share. It is judged the same way. A rise of more than 2.0 points fails the screen and goes to the paired stage, which judges it at 1.0.
4. On the Mt. Moon branch this gives +4.9 points on seeds 7 to 9 (0.0 on main, 4.9 on the branch) and +6.3 points paired (standard error 1.14), so it fails. On red/badges_6 the same branch gives -0.32 paired (1.12), so it passes. That rung spends about 18% of its frames on restock on both trees.
5. Every baseline rung gains a restock field. That is a baseline rewrite, so its PR names it and the lead reads it first. No waste value changes.

A heal that restores anything also counts as progress (`_goal_events`), so a long walk to a far Pokémon Center has the same shape. That was not measured. PR 2 records a share for restock, heal and PC visits on each rung in the gate report, and judges only restock. Heal or PC is judged only after its per-seed spread on main is measured on a few rungs and the lead has the numbers. A judged metric that is noisier than the limit is not added.

## 4. Cost

Measured on 2026-11-26 from file times:

1. A base tree: the worktree in under 1 s, `uv sync --locked` in 3 s with a warm cache.
2. 80 `gate-rung` runs (two rungs, two trees, 20 seeds) took 227 s at 4 at a time, a median of 11 s a run, on blue/post_game and red/badges_6.
3. So one failing rung costs 43 runs, about 2 minutes at 4 at a time. Gen II rungs were not timed.
4. Paired seeds on every rung would be 2537 runs, about 2 hours at that rate if the other rungs cost the same. So the pairs run only on a failing rung.
5. A cap: when more than 5 rungs fail the screen, the gate skips the paired stage and fails. Five rungs cost about 10 minutes, which fits with the 4-minute screen under the 30-minute gate timeout in `tools/preflight.py`.

## 5. What it leaves open

1. The screen can still pass a real rise. With a per-seed standard deviation of 5.1, a 3-seed mean has one of 2.9 points, so a real 3-point rise lands under the limit about a third of the time. This stays open on purpose. A full paired pass over all rungs is about 2 hours and fits the local nightly later, not in these PRs.
2. Stalls, errors and milestones keep the 3-seed rule.

## 6. Build, if approved

1. PR 1: the paired stage in `stage_ladder.py gate`, with a test of the judgment on fixed pairs.
2. PR 2: the restock, heal and PC shares, with restock judged and its baseline field. It waits for the lead to read the new baseline before merge.

Each is about 1 to 2 hours of agent work plus one preflight.

## 7. Decisions, 2026-11-26

1. Limit: 1.0 point on the paired mean over 23 seeds. A paired failure prints the 23 pairs and the per-goal sums.
2. Support goals: PR 2 records restock, heal and PC shares and judges restock only. Heal and PC wait for a measured per-seed spread on main.
3. Cap: 5 rungs.
4. Section 5 item 1 stays open, with the full paired pass left for the local nightly.
