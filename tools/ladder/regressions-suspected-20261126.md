# Ladder gate rungs suspected of regressing, 2026-11-26

One rung moves: blue/badges_4, from 10.79% wasted to 12.92%. Every other rung keeps its value from the
2026-11-25 baseline. The new value is the gate run of 352945f6, the change that keeps an errand as the goal
through the battles on its walk, on seeds 7, 8 and 9. That run failed the gate on this rung alone, by 2.13
points against a limit of 2.0.

## Why the rung moved

The change keeps the goal label through a battle on an errand's walk. The gate gives every goal start its
own random numbers, picked by the goal key (`GoalSeeds` in `pokesim/replay/rung.py`). On main a battle on
the way changed the goal key to the pick behind the errand and back, so each such battle started two goals
and reseeded the game's random bytes and the policy's random numbers twice. With the change the key stays,
so the run keeps the errand's numbers through the battle.

On seed 7 both versions play the same steps into a wild battle on Route 8 during a restock. At frame 5946
main changes the goal key to `poster_guard` and reseeds. The change keeps `restock` and does not. The runs
first differ at frame 7198, inside that battle, and play different trajectories after it. No decision
differs before the reseed. No battle step that resumed the errand replaced an offer that had writes: 0 of
279.

## Paired seeds

Both versions played blue/badges_4 for 108000 frames on goal seeds 7 to 29. Main is 086cd32e. Seeds 7, 8
and 9 come from the two gate runs, and main's run was 234668f8, which has the same tree as 086cd32e. Seeds
10 to 29 were played for this check alone.

| Seed | Main | Change | Difference |
| ---: | ---: | ---: | ---: |
| 7 | 5.54% | 11.90% | +6.36 |
| 8 | 13.71% | 13.74% | +0.03 |
| 9 | 13.11% | 13.11% | 0.00 |
| 10 | 17.51% | 17.51% | 0.00 |
| 11 | 17.57% | 17.57% | 0.00 |
| 12 | 24.56% | 24.56% | 0.00 |
| 13 | 5.63% | 1.19% | -4.44 |
| 14 | 20.75% | 20.75% | 0.00 |
| 15 | 12.46% | 12.46% | 0.00 |
| 16 | 14.63% | 14.63% | 0.00 |
| 17 | 9.58% | 9.58% | 0.00 |
| 18 | 7.16% | 7.84% | +0.68 |
| 19 | 10.60% | 13.38% | +2.78 |
| 20 | 9.14% | 20.97% | +11.83 |
| 21 | 17.74% | 7.74% | -10.00 |
| 22 | 10.96% | 10.96% | 0.00 |
| 23 | 17.82% | 17.82% | 0.00 |
| 24 | 5.99% | 5.34% | -0.65 |
| 25 | 9.67% | 9.67% | 0.00 |
| 26 | 11.92% | 11.92% | 0.00 |
| 27 | 13.33% | 13.33% | 0.00 |
| 28 | 7.24% | 13.47% | +6.23 |
| 29 | 9.03% | 9.03% | 0.00 |

Over the 23 seeds, the mean wasted share is 12.42% on main and 12.98% with the change. The paired difference
is +0.56 points with a standard error of 0.82. 14 seeds play the same run on both versions, 6 waste more
with the change and 3 waste less. No run stalls, raises an error or earns a story milestone.

On the seeds that differ, the wasted frames sit in the Rocket Hideout goals on both versions and move both
ways: `hideout_elevator`, `lift_rocket` and `poster_guard`, and on seeds 7 and 13 also `fuji`. On seed 21,
for one, main wastes 12166 frames over 7 `hideout_elevator` spans and the change wastes 1268 there.

The wasted share of one seed has a standard deviation of 5.1 points on main, so the mean of three seeds moves
about 2.9 points when a change shifts the trajectories. That is more than the gate's 2.0 point limit, which
is why a change that costs nothing on 23 seeds failed it on three.
