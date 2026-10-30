# PokeSim 0.5.3 patch release

This patch finishes the worker memory fix, steadies browser sound, fixes three stalls and
trade failures found on adventures running 0.5.2, and adds floating image tags.

- **Worker memory ([#111](https://github.com/afk-sapien/PokeSim/issues/111)).** Red, Blue and
  Yellow workers kept a copy of the Gen II data for every Time Capsule trade. Those copies are
  now freed after each trade.
- **Sound.** Browser audio follows the speed setting instead of the measured pace, so it no
  longer jumps in pitch or cuts out after a short stall.
- **Stalls and trade failures.** A Gold, Silver or Crystal game whose cartridge reset now
  continues its save instead of finding no route to anything. Red, Blue and Yellow no longer
  offer a Pokémon they are about to release. A game whose party cannot make room now pauses
  automatic trades instead of failing with a different Pokémon each time.
- **Floating tags ([#115](https://github.com/afk-sapien/PokeSim/issues/115)).** The image is
  also tagged `latest` and `0.5`.

See the [changelog](../CHANGELOG.md#053) for every change.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.5.3`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). Core stays at 0.7.1 and PyBoy RS at 0.1.2.
Saves and checkpoints from 0.5.2 load unchanged, and rolling back to 0.5.2 is safe.

The local suite passed 4,189 tests with private-ROM checks, including a replay of the stuck
Battle Tower save after a cartridge reset.

See the [0.5.2 release notes](release-0.5.2.md) for the previous patch, the
[0.5.0 release notes](release-0.5.0.md) for the full 0.5.0 update and its known
limitations, and [release status](../RELEASE_STATUS.md) for remaining limits.
