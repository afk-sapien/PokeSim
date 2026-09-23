# Release preparation: 0.3.2

A repair release over 0.3.1, from a review of the parts that had never been read: the trade
coordinator, the broker, and the per-adventure runtime. All four fixes concern an application
that has been running for weeks rather than minutes.

The most consequential one is that the backup an operator is told to take before upgrading could
not complete. `create_backup` staged the whole library in an unqualified temporary directory,
which lands in `/tmp`, and the shipped Compose file mounts `/tmp` as a 256 MB tmpfs on a
read-only root. The live server's library is 1.6 GB. Worse, the backup stops every running
adventure first and restarts them in its `finally`, so the operation existed only to fail on the
deployments that needed it. Both legacy import paths shared the defect. All three now stage
inside the application folder.

Finished Cable Club attempt directories are now pruned to the newest twenty, and an adventure can
finally set `event_retention_days`, which existed and was validated in the runtime but was
missing from the Library's whitelist, leaving its pruning call dead. The live server was carrying
174 MB of resolved interactions across 377 directories and 560 MB of event save states, and
every backup copied all of it into the archive.

A recovery that cannot finish now backs off from 30 seconds to a ten-minute ceiling instead of
re-driving every 30 seconds forever, and a participant operation that times out answers with a
retryable status rather than a 500 and a traceback.

There is no database change, no policy state change, and no migration. Existing checkpoints
resume untouched.

## What was verified

A mature save — eight badges, all 151 registered, 1,600 game hours, 240 partners — was replayed
900,014 frames on this build with no rewinds, no errors and 18 achievements, ending with the
Pokédex unchanged at 151. The Pokédex masking introduced in 0.3.1 was checked against 54 real
checkpoints across 27 adventures, with no case where it would hide a legitimate entry. The live
deployment's own worker logs were read for the classes of error these fixes address.

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
