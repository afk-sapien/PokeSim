# Ladder gate rungs suspected of regressing, 2026-11-14

One rung moves in `gate-baseline.json` by hand, with no new baseline run. This list keeps it on record
before the move.

| Rung | Wasted at 0.7.2 | Wasted on main | Baseline before | Baseline after |
| --- | ---: | ---: | ---: | ---: |
| crystal/red | 0.0% | 2.2% | 0.0% | 2.2% |

Each figure is one replay of the rung for 108000 frames (30 game minutes). Wasted is the share of frames
the replay audit counts as wasted.

The rise comes from #620, which picks the roomiest box for a box change. On this rung it opens a box
that holds no Pokémon where 0.7.2 opened one that held one. That moves every later wild encounter.

At 0.7.2 the super rod errand walks into two wild battles and catches one of the Pokémon. On main it
meets none. Both versions break off the errand at the same spot to restock balls, since a legendary is
still wanted. At 0.7.2 the catch falls inside the errand's stint, so the audit counts the
stint as progress. On main nothing is caught in it, so its 2340 frames count as wasted.

The waste is real in both versions: buying a restock that sits on the errand's walk before setting off
would save the walk. That is on the follow-up list, not in this change.
