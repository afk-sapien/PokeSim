# PokeSim 0.2.0rc31 experimental beta

This release adds desktop setup, game-local trading and partner locks, a
separate one-time Champion Mew reward, and shared desktop/server lifecycle handling.

Server shutdown now reports final-save failures. An adventure directory lock prevents
two updated runtimes from opening the same game. Shopping and PC interactions have
separate state owners, and runtime status includes source build identity.

Validation includes synthetic Python scenarios, real Chromium flows, private ROM
opening tests, and copied-save comparisons. These checks do not establish uninterrupted
multi-day gameplay or Pokémon cartridge playback on every supported target.

Validation passed 614 Python tests including five Chromium scenarios, 20 JavaScript
tests, and five private ROM tests. Two copied checkpoints each matched the baseline
over two game hours. Existing recovery churn remains.

Downloads include a Linux amd64 Docker image archive, Python packages, Compose
configuration, checksums, and a manifest identifying the exact source revision.
See [installation instructions](https://github.com/afk-sapien/PokeSim/blob/v0.2.0rc31/docs/self-hosting.md).
Native desktop bundles are also attached. All five targets passed their native build, launcher, and bundled-runtime checks in the [Desktop builds workflow](https://github.com/afk-sapien/PokeSim/actions/runs/35045201890).

Supply your own supported ROM and back up the complete data directory before upgrading.
Publishing this release does not upgrade existing deployments.

## Desktop downloads

Extract the complete archive, then open the application inside it:

| Platform | Archive | Application |
| --- | --- | --- |
| Windows x86-64 | `PokeSim-windows-amd64.zip` | `PokeSim/PokeSim.exe` |
| Apple Silicon Mac | `PokeSim-darwin-arm64.zip` | `PokeSim.app` |
| Intel Mac | `PokeSim-darwin-x86_64.zip` | `PokeSim.app` |
| Linux x86-64 | `PokeSim-linux-x86_64.tar.gz` | `PokeSim/PokeSim` |
| Linux ARM64 | `PokeSim-linux-aarch64.tar.gz` | `PokeSim/PokeSim` |

Each desktop archive has a SHA-256 checksum. `desktop-manifest.json` records its source
revision and validation run. Windows and macOS bundles are unsigned and are not
notarized. Native checks use PyBoy's demonstration ROM. Private Pokémon gameplay
checks were performed on Linux and do not establish multi-day or cross-platform
cartridge reliability.
