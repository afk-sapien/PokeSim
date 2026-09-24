# Release preparation: 0.3.8

A reliability release. Journal entries recorded during a fade or a warp now retake their screenshot
once the screen shows something, for up to 600 frames, and hold their ntfy push until then; a screen
that stays dark, such as an unlit cave, keeps what it has at the deadline. The trading coordinator
reads worker inventories for a proposal with no lock held and re-checks every admission condition
under the locks before recording the exchange; its display caches have their own lock, so the
trading page no longer waits on a worker. The scheduler scores each offer once per adventure pair
instead of once per combination. Ruff runs the Pyflakes rules in CI.

There is no database change, no policy state change, and no migration.

## What was verified

The suite is 1,323 tests, plus the JavaScript and browser tests. New tests cover a blank screenshot
retaken when the fade ends, a screen that stays blank kept at the deadline, a clear screen pushed at
once, the trading page and adventure starts answering while a worker's inventory is slow, and a
proposal refused when another exchange or a stopped adventure arrives meanwhile. The scheduler's
candidate search for two 246-slot libraries fell from 2.06 s to 0.19 s.

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
- **No formatter or type checker.** Ruff runs the Pyflakes rules only, and 15% of functions carry
  return annotations.

Gameplay remains an experimental beta. Synthetic tests, a single mature-save replay and
demonstration-ROM worker checks do not establish uninterrupted multi-day cartridge gameplay on
all platforms. Existing private gameplay and cable-trading receipts retain their original scope.
Back up the complete library before upgrading. Import legacy adventures into a new application
folder with the old application stopped.

[Historical release and deployment records](docs/history/releases-through-rc31.md) remain
available for earlier version receipts and their limitations.
