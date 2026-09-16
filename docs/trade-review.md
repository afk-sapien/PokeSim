# First-trade review history

Historical proposals and approvals from September 14 and 15, 2026. For current
installation and eligibility rules, see [automatic trading](automatic-trading.md)
and [PC offers and locks](pc-trading.md). Version and live-status statements below
describe the original review, not a fresh observation.

# Live automatic trading authorized

The owner explicitly approved the first exchange and ongoing automatic trading on
September 15, 2026 UTC. The scoped live coordinator is now enabled for useful spare
exchanges every 15 minutes. Individual trades need no further approval. The earlier
approval requirements below are historical and superseded by this authorization.

The first automatic exchange completed at 06:32 UTC: Red received MOCHI the Vulpix
and Blue received DIRTNAP as Machamp. Red subsequently evolved MOCHI into Ninetales.
Both games journaled the exchange once and resumed without retained holds. See
[the live verification](validation/monitor-20260915-0659.json).

# Previously proposed first exchange

Red would send its spare DIRTNAP, a level-41 Machoke, and receive Blue's spare MOCHI,
a level-32 Vulpix. Blue would receive DIRTNAP as Machamp. Both gain a Pokédex entry.
The copied-save rehearsal preserved both parties and every unrelated stored partner.
The current live proposal still names these individuals, although their box slots can
move during play and must be checked again before execution.

The requested ongoing policy permits one useful spare exchange every 15 minutes,
protecting parties, projects, last copies, and best retained partners. Both live games
and the scoped coordinator were deployed before activation. Automatic approval review
initially blocked activation. The owner has now explicitly approved automatic trading.

# Historical first-trade review

The owner subsequently requested and explicitly authorized automatic trading. This older
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

That earlier plan required specific participant approval and cold backups before a
manual exchange. The owner later explicitly authorized automatic exchanges. The rc16
coordinator now uses fresh held checkpoints, staged verification, durable recovery,
and journals in both games. The earlier one-exchange approval limit no longer applies.
