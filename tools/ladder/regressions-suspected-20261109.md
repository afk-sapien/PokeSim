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

None of these rungs has been investigated yet. The worst ones are the first cases for the replay tooling
in the phase 1 design note.
