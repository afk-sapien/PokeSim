# Release status: 0.4.17 published

[PokeSim 0.4.17](https://github.com/afk-sapien/PokeSim/releases/tag/v0.4.17)
is published with verified Python packages, the Linux amd64 Docker image and
versioned Compose downloads. Core remains pinned at 0.1.4.

The release adds named notification integrations, live audio and speed controls,
creation names, nickname editing, backup restore and deletion, optional community
artwork, responsive layouts and recovery fixes. See the
[release notes](docs/release-notes.md).

[Release PR #35](https://github.com/afk-sapien/PokeSim/pull/35) and
[dependency PR #32](https://github.com/afk-sapien/PokeSim/pull/32) are merged.
Issues [#33](https://github.com/afk-sapien/PokeSim/issues/33) and
[#34](https://github.com/afk-sapien/PokeSim/issues/34) are closed as resolved.
The annotated release tag points to `c3fc0c95f9286f2725adc3fd0a9c02e1b93db69f`.

CI passed on Python 3.11, 3.12 and 3.14. Native installation checks passed on
Windows, Intel and Apple Silicon macOS, and x86-64 and ARM Linux. The publishing
workflow reran validation, verified uploaded checksums and required an anonymous
pull of the tested image before publishing. A fresh Docker volume also passed
real cartridge upload, automatic setup, save export, artwork installation,
backup restoration and container recreation with progress preserved.

The [publication receipt](docs/validation/release-0.4.17.json) records the immutable
source revision and image digest. The
[combined review report](docs/validation/release-candidate-0417-20261003.md)
contains local evidence, candidate deployment history and the test-collection
correction found by CI. Its earlier pending-publication statements are historical.
The original DV-byte mutation cause remains unresolved. The healing recovery
addresses the reproduced rewind loop without rewriting DVs.

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
