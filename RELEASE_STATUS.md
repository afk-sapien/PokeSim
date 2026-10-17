# Release status: 0.5.1 prepared for publication

PokeSim 0.5.1 is a patch on 0.5.0 that fixes the Gen II League count past 200 Hall of Fame
entries and trades into Yellow with a traded Pikachu. See the [release notes](docs/release-notes.md).
The publication workflow must verify the exact tagged commit, build the packages and container,
and verify the uploaded assets before making the release public. The publication receipt is
recorded after that succeeds. The [0.5.0 receipt](docs/validation/release-0.5.0.json) remains
available for rollback.

0.5.0 moves every adventure to the Rust emulator (PyBoy RS 0.1.2 through Core 0.7.0) and adds
Gold, Silver and Crystal. See the [0.5.0 release notes](docs/release-0.5.0.md). Core and PyBoy RS
are not on PyPI: PokeSim depends on their GitHub release wheels, named in `pyproject.toml` and
hashed in `uv.lock`. Both dependency releases exist, their published assets match the lock,
and the publication receipt records the completed release checks.

The [beta 3 gameplay receipt](docs/validation/gen2-rust-beta3.json) records fresh Rust campaigns
through Red in Gold, Silver and Crystal, 100-encounter postgame checks with a mid-battle restart,
all three native Gen II cable pairings and all six Red/Blue Time Capsule pairings. Each fresh
campaign uses Cyndaquil and seed 1. These checks close the fresh-campaign and private cable
evidence gaps for that configuration, without claiming every starter, seed or platform.

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

Gameplay validation is bounded. Synthetic tests, copied-save marathon and purchase replays, and
demonstration-ROM worker checks do not establish uninterrupted multi-day cartridge gameplay on
all platforms. Existing private gameplay and cable-trading receipts retain their original scope.
Back up the complete library before upgrading. Import legacy adventures into a new application
folder with the old application stopped.

[Historical release and deployment records](docs/history/releases-through-rc31.md) remain
available for earlier version receipts and their limitations.
