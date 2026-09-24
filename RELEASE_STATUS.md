# Release preparation: 0.4.0

A visible-progress and storage release. Each journal entry now writes a `progress` row (badges,
Pokédex owned and seen, League wins) in the same transaction and from the same snapshot, whenever
one of those numbers changes; `/api/progress` serves the history and the Journal charts it as step
lines against real time. Databases that predate the table are backfilled once from the counts
their entries spelled out. At start, `recover_storage` strips staged snapshots from aborted as well
as released exchanges, removes all but the newest twenty finished exchange folders, and vacuums
the adventure database when more than 32 MB of it is free pages.

There is one additive table (`progress`), created on open. There is no policy state change and no
migration to run; an older release ignores the table.

## What was verified

The suite is 1,327 tests, plus 76 JavaScript tests and 18 browser tests. New tests cover a row
written only when a number changes, a League victory replayed after a rewind counting once, a title
screen never recorded, a journal backfilled from its entries and not twice, the route through the
Library's proxy, the chart's step geometry, and pruning, compaction and aborted-snapshot stripping.
Red's live journal (about 9,700 entries) backfills to 211 rows and renders without horizontal scroll at
390 px in light and dark.

The release targets are a Python wheel and source archive, plus a Linux amd64 Docker image and
Compose configuration. The `pokesim-desktop` Python command opens the Library in your browser.

Publication is gated on Python and browser regression checks, clean package identities, Docker
lifecycle checks, and isolated native Python installations on Windows x86-64, Intel macOS, Apple
Silicon, and Linux x86-64 and ARM64. The workflow uploads a draft, verifies every uploaded
checksum, and only then publishes it.

Publishing this release does not upgrade a running application: change the image or package where
it is deployed. See [release notes](docs/release-notes.md),
[desktop installation](docs/desktop.md), and [self-hosting](docs/self-hosting.md).

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
- **Seen counts start with this release.** Journal entries never recorded them, so backfilled
  history has badges, Pokédex owned and League wins only.
- **Hall of Fame teams still do not rotate.** A rematch fights with whichever six remain in the
  party. Choosing a varied team is a gameplay change that needs its own endurance run.
- **Legacy per-entry rewind states are kept** (about 24 MB for the busiest adventure). They stopped
  growing in an earlier release and are what lets an old Journal entry rewind.
- **No formatter or type checker.** Ruff runs the Pyflakes rules only, and 15% of functions carry
  return annotations.

Gameplay remains an experimental beta. Synthetic tests, a single mature-save replay and
demonstration-ROM worker checks do not establish uninterrupted multi-day cartridge gameplay on
all platforms. Existing private gameplay and cable-trading receipts retain their original scope.
Back up the complete library before upgrading. Import legacy adventures into a new application
folder with the old application stopped.

[Historical release and deployment records](docs/history/releases-through-rc31.md) remain
available for earlier version receipts and their limitations.
