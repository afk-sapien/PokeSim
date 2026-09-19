# PokeSim 0.2.0rc32 experimental beta

This candidate brings the latest development work together on main.

- Manage multiple independent Red and Blue adventures in one Adventure Library.
- Trade automatically through the in-game Cable Club, with protected partners,
  verified trade evolutions, and recovery for interrupted exchanges.
- Browse PC Pokémon by DV rating. One to three stars show quality at a glance,
  and four stars identify perfect DVs. The Pokédex tracks species with three-star
  or better partners alongside persistent level 100 and perfect-DV milestones.
- Track captures, current ownership, and each partner's League victories.
- Apply simulation pace from Library Settings and inspect party moves and stats.
- Include newer collection, training, healing, shopping, and storage safeguards.
- Update Python container, runtime, build, and GitHub Actions dependencies.

Install the Python package with `pokesim-desktop`, or run one Docker container.
Prepared adventures work offline. Supply your own supported ROM. Packages exclude
Pokémon ROMs, saves, generated game datasets, and portrait packs.

Downloads for this candidate are Python packages, a Linux amd64 Docker image,
Compose configuration, checksums, and a source manifest. Standalone executable
bundles are outside this release scope. Native package checks use PyBoy's demo
ROM and do not establish full cartridge gameplay reliability on every platform.

Back up existing adventures before upgrading. Import older single-game data into
a new library while both applications are stopped. Publishing does not upgrade
existing installations. See [installation and migration](desktop.md) and
[server setup](self-hosting.md).

The automatic player can get stuck. This remains an experimental beta without
a new uninterrupted multi-day gameplay claim.
