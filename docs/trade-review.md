# Historical first-trade review

The owner subsequently requested common trading. The rc15 trusted automatic policy
supersedes per-exchange approval for eligible spare trades on this pair. This older
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
