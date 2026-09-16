# PokeSim 0.2.0rc31 experimental beta

This release adds desktop setup, game-local trading and partner locks, a
separate one-time Champion Mew reward, and shared desktop/server lifecycle handling.

Server shutdown now reports final-save failures. An adventure directory lock prevents
two updated runtimes from opening the same game. Shopping and PC interactions have
separate state owners, and runtime status includes source build identity.

Validation includes synthetic Python scenarios, real Chromium flows, private ROM
opening tests, and copied-save comparisons. These checks do not establish uninterrupted
multi-day gameplay or native bundle qualification on every operating system.

Validation passed 614 Python tests including five Chromium scenarios, 20 JavaScript
tests, and five private ROM tests. Two copied checkpoints each matched the baseline
over two game hours. Existing recovery churn remains.

Downloads include a Linux amd64 Docker image archive, Python packages, Compose
configuration, checksums, and a manifest identifying the exact source revision.
See [installation instructions](https://github.com/afk-sapien/PokeSim/blob/v0.2.0rc31/docs/self-hosting.md).
Native desktop bundles are built and checked separately in the Desktop builds workflow.

Supply your own supported ROM and back up the complete data directory before upgrading.
Publishing this release does not upgrade existing deployments.
