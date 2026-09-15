# Current exchange awaiting approval

Red would send its spare DIRTNAP, a level-41 Machoke, and receive Blue's spare MOCHI,
a level-32 Vulpix. Blue would receive DIRTNAP as Machamp. Both gain a Pokédex entry.
The copied-save rehearsal preserved both parties and every unrelated stored partner.
The current live proposal still names these individuals, although their box slots can
move during play and must be checked again before execution.

The requested ongoing policy permits one useful spare exchange every 15 minutes,
protecting parties, projects, last copies, and best retained partners. Both live games
and the scoped coordinator are deployed. Execution remains disabled because automatic
approval review requires explicit approval of the first exchange and this policy.

# Historical first-trade review

The owner subsequently requested common trading. The rc16 implementation is ready,
but automatic approval review requires approval of the first trade and automatic policy. This older
last-copy proposal remains unexecuted because automatic trading protects last copies.
See [automatic trading](automatic-trading.md) for current behavior.

# First exchange ready for review

September 14, 2026. No live exchange has been executed.

The [read-only board](http://192.168.2.147:8950) polls both live games. Its first proposal
was tested against copied checkpoints:

| Run | Sends | Receives | Copied-save Pokédex change |
| --- | --- | --- | --- |
| Red | WAFFLES, Hitmonchan, level 30, box 5 slot 12 | SPAMWIZARD, Ditto, level 26 | 111 to 112 |
| Blue | SPAMWIZARD, Ditto, level 26, box 3 slot 17 | WAFFLES, Hitmonchan, level 30 | 113 to 114 |

These are each game's last boxed copy of the offered species. Their existing Pokédex
registrations remain. Both parties, their contents, and all eight badges remained
unchanged in the dry run. See [the verification record](validation/proposed-trade-20260914.json).

The rehearsal found and fixed a missing registration step in the save-based executor.
That correction is committed after the adventure release and is not active in either
live game. The board cannot write saves or execute trades.

Before a live exchange, obtain approval for these specific participants, re-read both
inventories, and reject a stale proposal. Stop and cold-backup both games, use the
corrected executor to stage both saves, then validate and install both outputs together.
Retain the pre-trade backups and record the exchange in both journals. Approval of this
one exchange must not enable automatic trading.
