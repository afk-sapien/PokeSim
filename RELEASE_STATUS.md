# Release preparation: 0.2.0rc32

The current source consolidates the Adventure Library, independent Red and Blue
adventures, automatic Cable Club trades, updated gameplay policies, and DV ratings.
The eight outstanding dependency PRs have been squash merged into main.

The release targets are a Python wheel and source archive, plus a Linux amd64
Docker image and Compose configuration. The `pokesim-desktop` Python command opens
the Library in your browser. Standalone executable bundles are experimental and
are not required or advertised for this release.

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
