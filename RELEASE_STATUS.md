# Release status: 0.4.13

This release adds consistent colored type badges to the live team, Pokédex, and PC.
The shared palette covers all 15 Generation I types, with a neutral unknown label.
Existing saves remain compatible. Core remains at 0.1.2.

See the [release notes](docs/release-notes.md) for installation details.

## Validation and publication

The relevant Pokédex and investment tests passed all 34 checks, and the JavaScript
checks passed. Chromium inspection covered all three pages and their detail windows
at 1280 and 320 pixels in light, dark, and automatic themes, for 18 combinations.
There were no browser script errors or horizontal overflow. All type labels have
at least 8.49:1 text contrast with their background.

Publication and deployment checks are pending for this candidate.

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
