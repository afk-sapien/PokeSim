# Release status: 0.4.15 published

This release combines per-adventure speed, resource readings, performance and
memory improvements, standard save export, fullscreen fixes, repeat walking
rewards, Journal Stats, and type colors. See the [release notes](docs/release-notes.md).

## Review and validation

An independent subagent reviewed speed migration and runtime propagation,
training and evolution caches, navigation invalidation, Victory Road routing,
mixed-speed trades, and resource telemetry. No actionable defects were confirmed.
Its focused suite passed 177 tests with 5 skipped. The broader Python suite passed
1,533 tests with 96 skipped. All 200 Red/Blue evolution-training destination
sequences matched the original implementation exactly.

Release review found two stale security checks targeting the removed global
running limit. They now exercise backup creation while retaining authentication,
CSRF, origin, and browser content-policy assertions. All 46 real-browser tests
and the disposable authenticated HTTPS proxy check passed. Lint, web checks,
and documentation checks passed.

A fresh live Blue adventure passed the opening story and earned the Boulder Badge.
After the evolution cache fix, observed Mt. Moon throughput ranged from 63× to
133× across different game moments. These readings are not a controlled speedup
benchmark. Full-story and long-duration observation remains in progress.

Published [PokeSim 0.4.15](https://github.com/afk-sapien/PokeSim/releases/tag/v0.4.15)
from `e843c7b4769958fb7633718bf2394d77739f4610` after all release workflow checks passed.
[PR #28](https://github.com/afk-sapien/PokeSim/pull/28) is merged. All five native
platforms, optional acceleration, Python and browser tests, package installation,
and fresh Docker installation checks passed in the publishing workflow.

Anonymous release downloads, checksums, installer files, and clean wheel identity
were independently verified. The published image is
`ghcr.io/afk-sapien/pokesim:0.4.15`, with digest
`sha256:68d44c6b3544d6d93f8e59aecdba77429b6337c7bf120edfc8330936fa634308`.
The owner explicitly authorized the standard GitHub release bot for this release.
Direct authenticated operations and authored Git history used `afk-sapien`.

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
