# PokeSim 0.6.2 patch release

This patch brings the image to ARM servers and home server app stores, and fixes several
places where adventures walked back and forth instead of moving on.

- **ARM64 image ([#269](https://github.com/afk-sapien/PokeSim/issues/269)).** The container
  image now runs natively on linux/arm64 as well as linux/amd64, such as a Raspberry Pi 4 or 5,
  an ARM NAS or an Apple silicon Mac. The same tag serves both, so `docker compose pull`
  picks the right one.
- **App store templates ([#273](https://github.com/afk-sapien/PokeSim/issues/273)).**
  `deploy/stores/` has drafts for Unraid Community Applications, CasaOS, Umbrel and TrueNAS
  community apps. None has been submitted to its store yet.
- **A shorter start.** The README now opens with a three command quickstart, the ROM note and
  what the app needs to run. Every pinned version moves with one release command, so the
  quickstart always installs this release.
- **Rocket Hideout ([#263](https://github.com/afk-sapien/PokeSim/issues/263),
  [#267](https://github.com/afk-sapien/PokeSim/issues/267)).** Red, Blue and Yellow no longer
  try the B1F door to the elevator before its Rocket is beaten, and take the lift to B2F on
  the way out while the door is shut.
- **Healing and errands ([#254](https://github.com/afk-sapien/PokeSim/issues/254),
  [#258](https://github.com/afk-sapien/PokeSim/issues/258),
  [#261](https://github.com/afk-sapien/PokeSim/issues/261),
  [#265](https://github.com/afk-sapien/PokeSim/issues/265)).** A trip to a Pokémon Center or a
  shop stays the goal through battles, dialogue, warps and menus in all six games. Gold, Silver
  and Crystal no longer pick Blackthorn's center through Ice Path.
- **Safari Zone and dungeons ([#256](https://github.com/afk-sapien/PokeSim/issues/256)).** Red,
  Blue and Yellow keep bag room for the Safari prizes and dungeon story items instead of
  walking out to sell.

See the [changelog](../CHANGELOG.md#062) for every change.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.6.2`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). pokecore moves to 0.11.0 and PyBoy RS stays at 0.1.4.
Saves and checkpoints from 0.6.1 load unchanged, and rolling back to 0.6.1 is safe.

See the [0.6.1 release notes](release-0.6.1.md) for the 0.6.1 update, the
[0.5.0 release notes](release-0.5.0.md) for its known limitations, and
[release status](../RELEASE_STATUS.md) for remaining limits.
