# Release preparation: 0.3.0

The current source changes how an adventure spends its time and what the pages that
watch it show. Training climbs in ten level steps instead of aiming straight at level
100 and no longer monopolises the planner, trades that cause an evolution are worth
taking, a completed Cable Club trade records what crossed, nicknames come from paired
word lists rather than a list of a hundred, and the live page, top bar and Pokédex
overview were rebuilt around what they are actually for. Frames are encoded only for a
viewer, which takes Max speed from roughly 74x to 314x real time.

This release adds one database column, `events.detail`, applied by the migration the
store already performs when an adventure opens. Policy state is unchanged and existing
checkpoints resume untouched.

The release targets are a Python wheel and source archive, plus a Linux amd64
Docker image and Compose configuration. The `pokesim-desktop` Python command opens
the Library in your browser. Standalone executable bundles are no longer built.

The [consolidation validation record](docs/validation/repository-cleanup-20260918.md)
records the local checks and their scope.

Publication is gated on Python and browser regression checks, clean package
identities, Docker lifecycle checks, and isolated native Python installations on
Windows x86-64, Intel macOS, Apple Silicon, and Linux x86-64 and ARM64. The workflow
uploads a draft, verifies every uploaded checksum, and only then publishes it.

This source consolidation does not publish a release or upgrade existing running
adventures. Older downloadable releases contain the previous single-game app.
See [candidate release notes](docs/release-notes.md), [desktop installation](docs/desktop.md),
and [self-hosting](docs/self-hosting.md).

Gameplay remains an experimental beta. Synthetic tests and demonstration-ROM
worker checks do not establish uninterrupted multi-day cartridge gameplay on all
platforms. Existing private gameplay and cable-trading receipts retain their
original scope. Back up the complete library before upgrading. Import legacy
adventures into a new application folder with the old application stopped.

[Historical release and deployment records](docs/history/releases-through-rc31.md)
remain available for earlier version receipts and their limitations.
