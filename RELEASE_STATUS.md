# Release preparation: 0.3.6

An interface release. Every page now loads `tokens.css`, the shared `panel.css` and `panel.js`,
and one page sheet, in place of six stylesheets that had drifted apart. The layouts were then
checked for boxes that should line up and did not: the live screen against the party, the plan
across the page, settings panels, library cards, journal entries and the PC's box list.

There is no database change, no policy state change, and no migration. The stopped-adventure
page's static whitelist now serves `panel.css`, `panel.js` and `panel-trading.css` in place of
the deleted sheets.

## What was verified

The suite is 1,311 tests, plus 18 browser tests. The live-page browser test asserts, at 1280,
900, 390 and 320px, that the screen and the last bay end on the same pixel side by side, and
that the plan spans the full width under both. A Playwright sweep of twelve pages at
1440/390/320 in both themes found no horizontal overflow, console errors or failed requests,
and an alignment audit at 1440/1024/390 found no uneven rows or truncated text.

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
- **`self.guard` is held across worker HTTP calls** of up to 55 seconds in `propose` and the
  commit path, and every browser read of the trading page needs the same lock, so one
  unresponsive worker can blank that page and block lifecycle operations while it waits.
- **The scheduler's candidate search is quadratic** in offers and re-runs from scratch every ten
  seconds — about 1.3 s per adventure pair for a full 240-slot library, in the manager process.
- **The bundled broker Compose file serves an unauthenticated endpoint on 0.0.0.0** and returns
  full inventories, and that endpoint is expensive to compute. The broker is optional and is not
  part of the Library deployment; do not expose it beyond a trusted network.
- **Event screenshots are captured without checking the frame is not blank**, so a milestone
  caught during a fade stores a solid white or black card. One is visible in the shipped Journal
  image.
- **No linter, formatter or type checker**, and 15% of functions carry return annotations.

Gameplay remains an experimental beta. Synthetic tests, a single mature-save replay and
demonstration-ROM worker checks do not establish uninterrupted multi-day cartridge gameplay on
all platforms. Existing private gameplay and cable-trading receipts retain their original scope.
Back up the complete library before upgrading. Import legacy adventures into a new application
folder with the old application stopped.

[Historical release and deployment records](docs/history/releases-through-rc31.md) remain
available for earlier version receipts and their limitations.
