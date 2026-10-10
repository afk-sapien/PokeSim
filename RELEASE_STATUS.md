# Release status: 0.5.0 DRAFT, not published

This is a draft note for the 0.5.0 release candidate. Nothing here claims that 0.5.0 has
been tagged, published or deployed, and there is no 0.5.0 publication receipt yet.
The last published release is [0.4.20](https://github.com/afk-sapien/PokeSim/releases/tag/v0.4.20);
its [receipt](docs/validation/release-0.4.20.json) is unchanged.

0.5.0 moves every adventure to the Rust emulator (PyBoy RS through Core 0.2) and adds
Gold, Silver and Crystal. See the [release notes](docs/release-notes.md). Core and PyBoy RS
are not on PyPI: PokeSim depends on their GitHub release wheels, named in `pyproject.toml` and
hashed in `uv.lock`. A release is not ready until those two releases exist, the lock matches them
and the publication workflow has produced a receipt.
Until then one commit marked TEMP points Core at a copy of its 0.6.0 wheel stored in this repository.

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
