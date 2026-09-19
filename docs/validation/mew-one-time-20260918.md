# One-time Mew reward correction

The repeating League reward pool incorrectly included Mew's internal species ID, 21. This was separate from the custom event's one-time receipt, so a correctly enforced event limit did not prevent extra League gifts. Sprout's journal records repeated `Received MEW for League reward` entries. At inspection Sprout held seven Mew, Ripple seven, and Ember six. Existing partners are preserved.

The repeatable base pool now contains only the three starters. None of the unlock groups contains Mew. Observing an existing Mew registration records a durable one-time receipt when one is missing, covering earlier League gifts and trades. Existing event transaction receipts are preserved. This prevents a checkpoint rewind from reopening the event claim.

Validation: 980 tests passed, 40 skipped, one existing Starlette deprecation warning. Regression tests exhaust every unlock-group combination, verify repeated draws exclude Mew, verify acquisition persists across restart and an older snapshot, preserve existing receipts, and retain normal League rewards after the Mew claim is closed.

The change replaces only `pokesim/rewards.py` in the running wheel. Wheel SHA-256: `e1b18a802107c9194c056c153e47c3fd665fce81696085e543430787c0f7760d`.

Deployment preserved all three campaigns and their 151-entry Pokédexes. All resumed healthy with zero reloads. Read-only checks confirmed each adventure has a durable Mew event claim. The existing extra Pokémon were not removed.

Full backup: `/home/ty/.local/share/pokesim/backups/mew-one-time-20260918`.

Private validation evidence: `/home/ty/.local/share/pokesim/smoke-20260915/observations/mew-one-time-20260918`.
