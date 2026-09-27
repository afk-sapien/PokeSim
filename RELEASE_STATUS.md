# Release status: 0.4.8

PokeSim now uses PokeSim Core 0.1.1 for shared ROM identities and game memory
decoding. PokeAgent Bench pins the same Core release. PokeSim retains its existing
application types, gameplay policies, emulator lifecycle, saves, trading, and UI.
No save-format or database migration is introduced.

See [shared core](docs/shared-core.md) for ownership and coordinated upgrades,
and [release notes](docs/release-notes.md) for installation details.

## Validation and publication

The Core integration in [PR #27](https://github.com/afk-sapien/PokeSim/pull/27)
passed all CI checks, including Python 3.11, 3.12, and 3.14, container lifecycle,
and native installation on Linux, Windows, Intel Mac, and Apple Silicon Mac.
Local Core compatibility and screen regression checks passed all 16 tests.
The wheel and source package resource checks passed.

[PokeSim 0.4.8](https://github.com/afk-sapien/PokeSim/releases/tag/v0.4.8) is published.
The exact tagged source passed 1,356 Python tests with 60 optional tests skipped,
and all 20 browser tests. Native installation, package, Docker lifecycle, and
anonymous image access checks all passed.

The home server was cold-backed up and upgraded from 0.4.7. The healthy container
reports PokeSim 0.4.8 and Core 0.1.1, with shared decoder imports verified directly.
Red and Blue resumed without errors, both retaining 151 of 151 registrations and
Porygon ownership records. The archived adventure remained stopped.
See the [sanitized validation receipt](docs/validation/release-0.4.8.json).

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
