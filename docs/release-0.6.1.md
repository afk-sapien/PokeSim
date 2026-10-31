# PokeSim 0.6.1 patch release

This patch fixes two places where Gold, Silver and Crystal adventures stopped making progress
on 0.6.0, and makes randomized headless runs play the randomized cartridge.

- **Mahogany Town ([#240](https://github.com/afk-sapien/PokeSim/issues/240)).** Once the player
  agrees to help Lance, the Mahogany Mart pharmacist only talks about Lance and sells nothing.
  The bot no longer goes back to his counter to restock, so it finds the hideout passwords and
  goes on to Pryce.
- **Olivine Port ([#241](https://github.com/afk-sapien/PokeSim/issues/241)).** A carpet tile on
  the S.S. Aqua gangway has no warp on it, but the bot treated it as one, so the pier looked
  cut off and the bot walked in and out of the port entrance. It now boards the ship.
- **Randomized headless runs.** Headless runs and the replay audit now boot the patched
  cartridge when a share code is set, as live adventures already did.

Red, Blue and Yellow play as before. See the [changelog](../CHANGELOG.md#061) for every change.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.6.1`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). pokecore stays at 0.10.2 and PyBoy RS at 0.1.4.
Saves and checkpoints from 0.6.0 load unchanged, and rolling back to 0.6.0 is safe.

See the [0.6.0 release notes](release-0.6.0.md) for the 0.6.0 update, the
[0.5.0 release notes](release-0.5.0.md) for its known limitations, and
[release status](../RELEASE_STATUS.md) for remaining limits.
