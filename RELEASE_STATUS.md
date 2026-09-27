# Release status: 0.4.12

This release adds the Kanto Marathon, an occasional postgame race with ordered
checkpoints, measured progress, saved records, and short journal reports.
Existing saves remain compatible. Core remains at 0.1.2.

See the [marathon guide](docs/marathon.md) and
[release notes](docs/release-notes.md) for details.

## Validation and publication

The local suite passed 1,393 tests with 69 optional tests skipped. All 11 marathon
regressions, JavaScript checks, lint, and documentation links passed.

Copied Red and Blue saves completed the entire course using normal button inputs.
Red finished in 17:47 with 1,228 recorded steps and 17 battles. Blue finished in
13:38 with 1,243 recorded steps and 13 battles. These times exclude travel to the
starting line. See the [sanitized replay receipt](docs/validation/marathon-replays.json).

The unpublished 0.4.11 candidate was canceled during native installation checks
to correct the live checkpoint display. It was never published or deployed.
Publication and deployment checks are pending for 0.4.12.

## Known limits, deliberately not addressed here

- **Recovery never gives up.** An exchange that cannot be finished is retried forever, now slowly.
  A ceiling would mean abandoning an exchange already committed on one side, which is the one
  path that can actually lose a Pokémon. It needs a design and a test, not a constant. Until
  then, a permanently stuck exchange still freezes stop, archive, edit and backup for that pair,
  and the only exit is to resolve whatever the recovery is failing on.
- **The commit path still holds `self.guard` across the two stage calls**, up to 55 seconds each,
  so a cancel that arrives during staging waits for them. That ordering is deliberate: a cancel
  must not race a commit.
- **The scheduler's candidate search is still quadratic** in offers, and re-runs from scratch every
  ten seconds, though each combination is now cheap: about 0.2 s per pair of full libraries.
- **The bundled broker Compose file serves an unauthenticated endpoint on 0.0.0.0** and returns
  full inventories, and that endpoint is expensive to compute. The broker is optional and is not
  part of the Library deployment; do not expose it beyond a trusted network.
- **Journal screenshots already stored blank are not repaired**, including the one in the shipped
  Journal image. Only new entries are retaken.
- **Seen counts, level 100 species and perfect finds have no backfill.** Journal entries never
  recorded them, so their history starts with 0.4.0 (seen) and 0.4.2 (the other two).
- **Hall of Fame teams still do not rotate.** A rematch fights with whichever six remain in the
  party. Choosing a varied team is a gameplay change that needs its own endurance run.
- **Legacy per-entry rewind states are kept** (about 24 MB for the busiest adventure). They stopped
  growing in an earlier release and are what lets an old Journal entry rewind.
- **No formatter or type checker.** Ruff runs the Pyflakes rules only, and 15% of functions carry
  return annotations.

Gameplay remains an experimental beta. Synthetic tests, copied-save marathon and purchase replays, and
demonstration-ROM worker checks do not establish uninterrupted multi-day cartridge gameplay on
all platforms. Existing private gameplay and cable-trading receipts retain their original scope.
Back up the complete library before upgrading. Import legacy adventures into a new application
folder with the old application stopped.

[Historical release and deployment records](docs/history/releases-through-rc31.md) remain
available for earlier version receipts and their limitations.
