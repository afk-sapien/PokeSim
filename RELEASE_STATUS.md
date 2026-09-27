# Release preparation: 0.4.7

This release fixes Game Corner prize confirmation, replaces the raw stat-sum ranking
with a weighted Power score, and defaults All Pokémon to highest Power first.
Long stat explanations move from Pokémon details into separate repository guides for
Pokémon stats, PC storage, and trading. No save-format or schema change is introduced.

## Validation

The Game Corner can leave two visible cursors when its Yes/No confirmation opens.
The fix selects the visible cursor identified by the active menu state. Regression
cases cover both Red and Blue prize lists, both confirmation choices, and fallback
behavior for other menu layouts.

Private replays of both existing home-server saves completed Porygon purchases,
reached 151 of 151 registrations, deducted the correct coins, and returned to the
overworld. The live saves were not edited for these checks. Targeted screen,
controller, and navigation tests passed 323 checks.

The stats checks cover all 151 species at equal training, the actual reported Blue
individuals, unavailable data, and consistent party and box values. Browser checks
cover default sorting and compact details at desktop and mobile widths.

The isolated release source passed 1,352 Python tests with 60 optional tests skipped,
plus all 20 browser tests. JavaScript, documentation, Ruff lint, wheel, and source
package checks also passed. Unrelated shared-core work was excluded from this source.

The release workflow gates publication on Python and browser tests, native installation
checks, and Docker first-upload, save, and restart checks.

See [release notes](docs/release-notes.md), [Pokémon stats](docs/pokemon-stats.md), and
[self-hosting](docs/self-hosting.md).

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

Gameplay remains an experimental beta. Synthetic tests, two copied-save purchase replays, and
demonstration-ROM worker checks do not establish uninterrupted multi-day cartridge gameplay on
all platforms. Existing private gameplay and cable-trading receipts retain their original scope.
Back up the complete library before upgrading. Import legacy adventures into a new application
folder with the old application stopped.

[Historical release and deployment records](docs/history/releases-through-rc31.md) remain
available for earlier version receipts and their limitations.
