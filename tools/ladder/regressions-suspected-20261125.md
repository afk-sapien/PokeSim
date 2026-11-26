# Ladder gate rungs suspected of regressing, 2026-11-25

The gate baseline in `gate-baseline.json` was taken at d8996787 on 2026-11-20 under pyboy-rs 0.1.9.
pyboy-rs 0.2.0 follows real hardware timing, so every rung's three seeds play other trajectories, and
the gate failed on 8 of its 59 rungs. The new baseline is one gate run on 2026-11-25 of 5db7dacc, the
pin branch, on seeds 7, 8 and 9. An earlier run of the branch's first commit, 1869a5f2, gave the same
numbers on all 59 rungs.

The move gives 22 rungs a looser limit: a higher wasted share, which raises the gate's limit, or fewer
story milestones. This list keeps those 22 before the baseline moves, so accepting the new timing does
not hide them. 11 rungs get only a tighter limit, and 26 keep the same one.

Each rung plays 108000 frames (30 game minutes) on each seed. Wasted is the share of frames the replay
audit counts as wasted. Milestones are the mean story milestones over the seeds. The two columns on the
right are the independent check: both versions played goal seeds 10 to 19, which no baseline used, with
no baseline to compare against. The list is sorted by how much the wasted share rose.

| Rung | Wasted before | Wasted after | Change | Milestones before | Milestones after | Failed the old baseline | Seeds 10 to 19 wasted, 0.1.9 | Seeds 10 to 19 wasted, 0.2.0 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| gold-randomized/badges_4 | 1.50% | 9.04% | +7.54 | 0.00 | 0.00 | yes | 3.14% | 3.11% |
| red/badges_6 | 4.87% | 8.91% | +4.04 | 0.00 | 0.00 | yes | 7.29% | 8.10% |
| silver/badges_4 | 0.00% | 3.57% | +3.57 | 0.00 | 0.00 | yes | 1.89% | 3.44% |
| blue/badges_4 | 8.20% | 10.79% | +2.59 | 0.00 | 0.00 | yes | 14.83% | 14.04% |
| crystal/new_game | 1.55% | 3.39% | +1.84 | 3.00 | 2.67 | yes | 4.58% | 2.23% |
| red-randomized/badges_4 | 12.32% | 13.74% | +1.42 | 0.00 | 0.00 | | 11.38% | 12.16% |
| blue/badges_6 | 7.70% | 8.77% | +1.07 | 0.00 | 0.00 | | 11.04% | 10.40% |
| crystal/badges_4 | 4.29% | 5.18% | +0.89 | 0.00 | 0.00 | | 2.95% | 0.00% |
| yellow/badges_4 | 12.45% | 13.07% | +0.62 | 0.00 | 0.00 | | 13.18% | 13.41% |
| blue/post_game | 3.62% | 3.97% | +0.35 | 0.00 | 0.00 | | 3.37% | 3.34% |
| crystal/league_first | 0.00% | 0.35% | +0.35 | 0.00 | 0.00 | | 0.00% | 0.00% |
| yellow/badges_2 | 4.75% | 4.99% | +0.24 | 0.00 | 0.00 | | 6.04% | 6.24% |
| blue/new_game | 2.41% | 2.60% | +0.19 | 3.00 | 3.00 | | 2.53% | 2.36% |
| red/new_game | 2.41% | 2.60% | +0.19 | 3.00 | 3.00 | | 2.53% | 2.36% |
| red/badges_4 | 13.36% | 13.53% | +0.17 | 0.00 | 0.00 | | 16.77% | 10.08% |
| yellow/post_game | 1.76% | 1.86% | +0.10 | 0.00 | 0.00 | | 1.70% | 1.99% |
| crystal/badges_2 | 0.77% | 0.86% | +0.09 | 0.67 | 0.67 | | 0.23% | 1.10% |
| red/post_game | 2.21% | 2.28% | +0.07 | 0.00 | 0.00 | | 2.52% | 2.86% |
| red-randomized/new_game | 1.25% | 1.28% | +0.03 | 3.00 | 3.00 | | 1.58% | 1.53% |
| crystal/red | 0.66% | 0.66% | +0.00 | 1.00 | 0.33 | yes | 0.78% | 0.51% |
| silver/badges_2 | 0.00% | 0.00% | +0.00 | 0.67 | 0.33 | yes | 0.00% | 0.00% |
| silver/new_game | 7.31% | 3.58% | -3.73 | 3.00 | 2.67 | yes | 1.31% | 2.34% |

On seeds 10 to 19, across all 59 rungs, the mean wasted share moves by -0.18 points a rung (p 0.32) and
the mean milestones by +0.015 a rung (p 0.20), in a test that shuffles the version labels within each
rung. Of these 22, only red/badges_4 differs at p < 0.05, and it is better on 0.2.0 (p 0.03).

On seeds 10 to 19, the four rungs with fewer milestones after the move earn: crystal/new_game 2.90 on
0.1.9 and 3.00 on 0.2.0, silver/badges_2 0.50 and 0.70, silver/new_game 3.00 and 3.00, crystal/red 0.60
and 0.30. So crystal/red earns fewer milestones on the fresh seeds too, though not at p < 0.05. It is
the rung to watch.

No rung stalls or raises an error in either baseline.
