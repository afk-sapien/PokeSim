# Release status: 0.4.18 candidate

The 0.4.18 candidate combines [repository cleanup #46](https://github.com/afk-sapien/PokeSim/pull/46)
and [feature and release work #47](https://github.com/afk-sapien/PokeSim/pull/47).
The latest published release remains [0.4.17](https://github.com/afk-sapien/PokeSim/releases/tag/v0.4.17).
No 0.4.18 tag or public downloads have been published yet.

See the [release notes](docs/release-notes.md) for the combined changes and
[implementation details](docs/next-release.md) for their limits. Core remains at 0.1.4.

The Tynet preview includes live palettes and the complete feature set. Its latest
local regression run passed 1,781 tests with 50 skips, and all five saved adventures
passed checkpoint validation before deployment. Live palette checks preserved
emulator state, paused frame counts, and worker continuity.

Release validation is in progress. The feature PR's initial GitHub checks exposed
an eager import of optional Playwright in normal test collection. That import now
follows the existing lazy browser assertion pattern. The cleanup PR's prior jobs
mostly failed to acquire hosted runners and have been restarted. A green local
run does not substitute for the full cross-platform and browser checks.

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
