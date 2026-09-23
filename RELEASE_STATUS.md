# Release preparation: 0.3.4

Two changes over 0.3.2, both about how much an adventure writes to disk just by existing.
Together they reduce the journal's storage on a long-running adventure by about 98%.

Every notable journal entry stores a full PyBoy save state so the entry can be rewound to. That
state is 167 KB of mostly zeroed RAM and it was written raw, and they are only ever added to. On
the server this was found on, two adventures held 2,836 of them totalling 456 MB — against 68 MB
of screenshots and 108 MB of autosaves, which are bounded at twenty. That was essentially all of
the roughly 40 MB an hour an adventure wrote.

A save state was kept for every *notable* journal entry, which conflated three questions: notable
also decides what reaches the feed and what sends a notification. Across two live adventures,
levelling up accounted for 840 of 2,840 states and entering a map for 421; 82% belonged to types
nobody would rewind to. States are now kept only for badges, Hall of Fame runs, new partners,
evolutions, blackouts, stalls and legendary retries. Entries written earlier keep the states they
already have.

States are now gzipped, about ten to one. Reading detects the gzip magic, so states written
before this release still load: an existing library keeps resuming and every journal entry keeps
its rewind.

There is no database change, no policy state change, and no migration. Existing checkpoints
resume untouched.

## What was verified

Measured on a real 167,677-byte state from the live server: 15,826 bytes compressed, and PyBoy
loaded it back to the correct game state (map, party and Pokédex all intact). Compacting that
server's existing states took the library from 1.6 GB to 961 MB with the application running and
no errors. The full suite is 1,302 tests, including a round trip through the compressed format
and a check that a state written before this release still reads.

Carried over from 0.3.2: a mature save was replayed 900,014 frames with no rewinds, no errors and
18 achievements, and the Pokédex masking from 0.3.1 was checked against 54 real checkpoints
across 27 adventures.

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
