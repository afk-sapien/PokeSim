# Release status: 0.4.16 published and deployed

[PokeSim 0.4.16](https://github.com/afk-sapien/PokeSim/releases/tag/v0.4.16)
and [PokeSim Core 0.1.4](https://github.com/afk-sapien/pokesim-core/releases/tag/v0.1.4)
were published on September 30, 2026. This release adds global nickname vocabulary,
League rematch party rotation, and shared Core mechanics. See the
[release notes](docs/release-notes.md). PRs
[30](https://github.com/afk-sapien/PokeSim/pull/30) and
[31](https://github.com/afk-sapien/PokeSim/pull/31) are merged.

## Validation

Core passed 67 synthetic tests and Python 3.11, 3.12 and 3.13 CI. The benchmark
passed 282 tests with 2 skipped. Fifteen private real-cartridge controller cases
passed with exact input replays and a forced frame-budget cutoff. PokeSim passed
1,541 tests with 98 skipped against the new Core wheel, including first-install
worker startup. All 48 browser tests passed.

The [release workflow](https://github.com/afk-sapien/PokeSim/actions/runs/36738803478)
passed its Python, browser, package, fresh Docker install, proxy and native install
gates. Native checks covered Linux amd64 and arm64, Windows, Intel Mac and Apple
Silicon Mac. Anonymous public downloads, checksums, and wheel source identity
were independently verified.

## Deployment

The home server runs the official `ghcr.io/afk-sapien/pokesim:0.4.16` image,
revision `5dc2e622cb02e6ad7bc1baeadaf83ecc7d077e5c`, with Core 0.1.4.
Image digest: `sha256:08086a8179193bf672481867cdaacb99a920fc98e3627cc6420b756989560c0e`.

A complete cold backup was verified before upgrading. Post-deployment checks
confirmed readiness, the exact release identity, shared Core adapters, valid
collection statistics, and advancing frames in Red and Blue at their selected
16× speed. Other adventures remained stopped. Settings, archive state, capture
totals and gift histories were preserved. A browser review confirmed the new
version and healthy library cards. Private backup and rollback details are
recorded in the homelab deployment log.

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
