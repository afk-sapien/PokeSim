# Release preparation: 0.3.5

Two changes. Portraits are now read out of the owner's own cartridge, and journal entries stop
keeping a save state.

Adding a ROM decodes all 151 front sprites from it into `assets/sprites`. Nothing is shipped and
nothing is downloaded: the artwork was always in the supplied ROM. A file already in that folder
is never replaced, so a hand-installed pack still wins. The decoder is a port of pret/pokered's
`home/uncompress.asm`; Mew is read from its own header at `0x0425B`, outside the base-stats table.

0.3.4 narrowed per-entry save states to eight event types; this removes them. The rewind they
powered is refused on any adventure that has completed a trade, because the button requires no
trade barrier and every earlier checkpoint predates it — so two live adventures were holding
456 MB of states for a button that could not appear. Recovery is already covered by twenty
rotating autosaves, the League entry checkpoint and the before-stall checkpoint, all bounded.

There is no database change, no policy state change, and no migration. Existing checkpoints
resume untouched, and journal entries written earlier keep the states they have.

## What was verified

All 151 portraits decoded from a real Red cartridge match pret/pokered's reference art **pixel
for pixel** at the pinned revision, Mew included; the suite asserts this wherever a ROM and a
reference checkout are both present, and skips otherwise. Installing a ROM over an existing
hand-placed portrait leaves that file untouched. The suite is 1,306 tests.

Carried over: a mature save replayed 900,014 frames with no rewinds and no errors, and the
Pokédex masking from 0.3.1 checked against 54 real checkpoints across 27 adventures.

The release targets are a Python wheel and source archive, plus a Linux amd64 Docker image and
Compose configuration. The `pokesim-desktop` Python command opens the Library in your browser.
Standalone executable bundles are no longer built.

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
