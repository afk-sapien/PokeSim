# Individual Elite Four wins

The PC now displays and sorts individual Hall of Fame participation. One completed Elite Four and Champion run credits every Pokémon present in the final party, including fainted partners. Boxed partners do not receive credit.

The durable SQLite ledger is written in the same transaction as its victory event. Victory ordinals deduplicate replayed records. Trainer and DV identity survives evolution, training, renaming, and PC movement. Ambiguous identities display Unavailable. Counts do not depend on event retention or checkpoint metadata.

Managed cable preparation exports the outgoing partner's record. Staging checks it against the incoming cartridge identity. Commit and recovery merge per-origin counts by maximum, preserving history across return trades without counting recovery twice. Historical library import also merges by origin to recover victories earned before earlier trades.

Validation:

- 977 Python tests passed, 40 skipped. One existing Starlette deprecation warning remains.
- All 10 PC interface tests passed, including sorting across party and boxes, unknown counts last in either direction, and details display.
- Targeted checks cover repeat victory ordinals, restart, evolution, renaming, boxed exclusion, fainted participation, ambiguous identity, transaction rollback, committed trade recovery, and return trades.
- Historical preview decoded more than 750 saved Hall of Fame states. No historical state was missing or invalid in the three current games. Indistinguishable individuals are marked unavailable rather than credited speculatively.

Runtime wheel SHA-256: `0d8ee7b6d5930cc4aac79102b90bdf0793c8245f28c48406a9135831395abfe6`.

The deployment replaces only the eight package files for this feature, retaining the running build's existing fixes. Exact counts and live checks are recorded in the private observation artifacts.

Deployment verification confirmed all three original campaigns running, with no reloads or trade holds. All 754 historical victory snapshots were decoded successfully: Sprout 275, Ripple 213, and Ember 266. Live PC cards and the detail dialog showed BONKJOVI with 275 wins. Browser inspection confirmed descending sorting and the two by two metric layout.

Full backup: `/home/ty/.local/share/pokesim/backups/elite-four-wins-20260918`.

Private evidence: `/home/ty/.local/share/pokesim/smoke-20260915/observations/elite-four-wins-20260918`.
