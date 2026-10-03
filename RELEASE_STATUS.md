# Release status: 0.4.17 release validation

The complete unpublished candidate includes named notification integrations,
nickname editing, backup loading and deletion, custom intro and adventure names,
live audio and speed controls, responsive layouts, portrait backgrounds, an optional
community sprite installer, and the
poison-faint and excess-HP recovery corrections. Core remains pinned at 0.1.4.
See the [release notes](docs/release-notes.md) and the
[combined review and validation report](docs/validation/release-candidate-0417-20261003.md).

The latest October 3 combined sweep passed 1,648 non-browser regression tests
with 50 skipped and 104 real-browser tests. After fixing a newly found backup
issue, 29 focused checks passed, including a new regression and all five cartridge
tests. The 82 browser-script checks also passed. Ruff and documentation links passed. Both distribution archives passed
resource checks. Fresh Python installation and repeat installer checks passed on
Linux. The full image passed legacy save/resume, Library restart, fresh-volume
first-run setup, and authenticated HTTPS proxy checks. A separate fresh-volume
Docker test with a real Red cartridge also passed browser setup, automatic data
preparation, save export, artwork installation, backup restore and container
recreation with persisted progress.

Earlier totals below the scope of this sweep are superseded by the linked report.
The 50 skipped checks retain their environment and optional-fixture limits.
Windows, macOS and the full Python-version installation matrix still require CI
before public publication. The original DV-byte mutation cause remains unresolved.
The healing recovery addresses the reproduced rewind loop without rewriting DVs.

The complete candidate is deployed on the home server. All four previously running
adventures resumed, and the stopped adventure stayed stopped. Desktop and mobile
visual checks passed on the deployed pages. The owner approved publication after the home-server acceptance test and fresh
Docker installation check. Public publication is gated on the release PR's CI and
the publishing workflow. The validation report records the candidate deployments.

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
- **League rotation has limited endurance coverage.** A private copied-save replay verified
  the reserve swap through PC menus. Repeated complete rematches with rotating teams still
  need an extended gameplay run.
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
