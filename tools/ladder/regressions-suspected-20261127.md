# Ladder gate rungs suspected of regressing, 2026-11-27

Two rungs move in `gate-baseline.json` by hand, with no new baseline run. Every other rung keeps its value.

| Rung | Baseline before | Baseline after |
| --- | ---: | ---: |
| gold/badges_6 | 0.00% | 3.99% |
| yellow/badges_2 | 4.99% | 8.49% |

The new values are the gate run of 1421dcc5 on seeds 7, 8 and 9. That head is the battle press change
(a battle press goes as soon as the game waits for a button, read from game state) with main at dcdeca7f
merged in. That run failed the gate on these two rungs alone, on wasted share, with 0 stalls and 0 errors.

## Why the rungs moved

The change shortens the gap after a battle press, so every battle after the first ends on another frame.
The game's random numbers follow the frame, so a seed can play another trajectory after its first battle.
Over 43 paired seeds each rung is within 1.5 standard errors of no change (gold/badges_6 1.3, yellow/badges_2
1.5), so the 3-seed baseline moved with the new frame timing and the rungs did not regress.

The 10 rungs that passed past their baseline on story milestones in the same run keep their baselines.
Those gains are the same 3-seed noise in the other direction.

## Paired seeds

Each rung played 108000 frames on goal seeds 7 to 49. Wasted is the share of frames the replay audit counts
as wasted.

1. yellow/badges_2, the change at 1421dcc5 against main at dcdeca7f. Seeds 7 to 29 come from the gate's
   paired check, and seeds 30 to 49 were played for this note alone.
2. gold/badges_6, seeds 7 to 29 the same way. Seeds 30 to 49 were played before main took #763 and #764,
   with the change at a05eaab6 against main at b652b80a. Those two merges change no Gen II code, and the
   gate's seeds 7 to 29 gave the same 23 pairs on both bases.

| Rung | Seeds | Mean difference | Standard error | Median |
| --- | --- | ---: | ---: | ---: |
| gold/badges_6 | 7 to 29 | +3.38 | 1.69 | +0.00 |
| gold/badges_6 | 30 to 49 | -1.00 | 0.92 | +0.00 |
| gold/badges_6 | 7 to 49 | +1.34 | 1.04 | +0.00 |
| yellow/badges_2 | 7 to 29 | +2.09 | 1.60 | +0.41 |
| yellow/badges_2 | 30 to 49 | +0.63 | 1.02 | +0.99 |
| yellow/badges_2 | 7 to 49 | +1.41 | 0.97 | +0.66 |

In gold/badges_6 main wastes nothing on 40 of 43 seeds, and the change wastes something on 7. Most of
the change's waste is under `red_gyarados`, the Lake of Rage Gyarados (5 seeds), and the rest under
`lance` (1) and `buy_balls` (2). Main's 3 seeds waste under `red_gyarados` (2) and `lance` (1).

### gold/badges_6, wasted share by seed, main then change

| Seed | Main | Change | Seed | Main | Change | Seed | Main | Change |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 7 | 0.00 | 0.00 | 22 | 0.00 | 8.97 | 37 | 0.00 | 0.00 |
| 8 | 0.00 | 0.00 | 23 | 0.00 | 0.00 | 38 | 0.00 | 0.00 |
| 9 | 0.00 | 11.96 | 24 | 0.00 | 10.62 | 39 | 0.00 | 0.00 |
| 10 | 0.00 | 0.00 | 25 | 0.00 | 26.46 | 40 | 0.00 | 0.00 |
| 11 | 0.00 | 22.72 | 26 | 0.00 | 0.00 | 41 | 11.21 | 0.00 |
| 12 | 0.00 | 0.00 | 27 | 0.00 | 0.00 | 42 | 0.00 | 0.00 |
| 13 | 0.00 | 0.00 | 28 | 0.00 | 0.00 | 43 | 0.00 | 0.00 |
| 14 | 0.00 | 0.00 | 29 | 0.00 | 0.00 | 44 | 0.00 | 0.00 |
| 15 | 0.00 | 0.00 | 30 | 0.00 | 0.00 | 45 | 0.00 | 0.00 |
| 16 | 0.00 | 0.00 | 31 | 0.00 | 0.00 | 46 | 0.00 | 0.00 |
| 17 | 0.00 | 0.00 | 32 | 0.00 | 0.00 | 47 | 13.76 | 0.00 |
| 18 | 0.00 | 0.00 | 33 | 0.00 | 4.97 | 48 | 0.00 | 0.00 |
| 19 | 0.00 | 0.00 | 34 | 0.00 | 0.00 | 49 | 0.00 | 0.00 |
| 20 | 0.00 | 7.00 | 35 | 0.00 | 0.00 | | | |
| 21 | 9.99 | 0.00 | 36 | 0.00 | 0.00 | | | |

### yellow/badges_2, wasted share by seed, main then change

| Seed | Main | Change | Seed | Main | Change | Seed | Main | Change |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 7 | 8.43 | 6.55 | 22 | 6.53 | 7.19 | 37 | 2.48 | 8.74 |
| 8 | 2.84 | 10.97 | 23 | 2.85 | 8.17 | 38 | 9.37 | 11.90 |
| 9 | 7.79 | 7.95 | 24 | 4.38 | 8.43 | 39 | 5.81 | 8.99 |
| 10 | 4.31 | 4.46 | 25 | 8.76 | 9.58 | 40 | 12.67 | 6.45 |
| 11 | 5.90 | 5.95 | 26 | 6.26 | 5.50 | 41 | 3.71 | 3.95 |
| 12 | 8.55 | 6.59 | 27 | 11.87 | 9.97 | 42 | 8.68 | 9.47 |
| 13 | 4.27 | 10.25 | 28 | 4.86 | 17.66 | 43 | 4.11 | 13.03 |
| 14 | 6.64 | 33.44 | 29 | 7.19 | 7.04 | 44 | 2.69 | 6.66 |
| 15 | 21.56 | 3.77 | 30 | 5.34 | 8.06 | 45 | 6.49 | 6.26 |
| 16 | 2.17 | 2.26 | 31 | 8.43 | 3.48 | 46 | 5.41 | 8.48 |
| 17 | 4.90 | 9.80 | 32 | 4.24 | 4.68 | 47 | 16.19 | 3.92 |
| 18 | 7.61 | 10.13 | 33 | 4.08 | 4.03 | 48 | 4.51 | 3.62 |
| 19 | 5.63 | 6.04 | 34 | 5.10 | 7.79 | 49 | 0.41 | 1.59 |
| 20 | 12.85 | 10.56 | 35 | 6.05 | 8.57 | | | |
| 21 | 2.76 | 4.71 | 36 | 4.20 | 2.96 | | | |
