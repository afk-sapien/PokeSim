# PokeSim 0.5.1 patch release

This patch fixes two gameplay issues found on finished adventures running 0.5.0.

- **Gold, Silver and Crystal League wins past 200.** The cartridge stops recording Hall of
  Fame entries at 200. A finished run kept challenging the League for a win that never
  counted, earned no rewards and showed "Stuck? N game hours without progress" every six
  hours. A win from Lance's Room into the Hall of Fame now counts after the cartridge stops,
  and each League win counts as progress.
- **Traded Pikachu in Yellow.** Only the starter, a Pikachu with the player's own trainer ID,
  stays in the party. A party of field-move holders with a traded Pikachu had no one to
  deposit, so every trade into Yellow failed with "could not safely make room in its party".

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.5.1`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). Core stays at 0.7.0 and PyBoy RS at 0.1.2.
Saves and checkpoints from 0.5.0 load unchanged. Rolling back to 0.5.0 is safe.

The local suite passed 2,418 tests with private-ROM checks. Regression tests cover the
capped Hall of Fame count, a checkpoint saved before this version, and the live Yellow
party that failed every trade.

See the [0.5.0 release notes](release-0.5.0.md) for the full 0.5.0 update and its known
limitations, and [release status](../RELEASE_STATUS.md) for remaining limits.
