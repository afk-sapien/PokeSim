# PokeSim 0.7.2 release

Long-running adventures resume again. An adventure that played long enough at high speed could
stop resuming after a restart, and its saves now load with nothing lost. This closes the known
issue from 0.7.1.

See the [changelog](../CHANGELOG.md#072) for every change.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.7.2`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). pokecore moves to 0.12.2 and PyBoy RS to 0.1.6.

0.7.2 does not change the Library database or the save format, so adventures continue from
their saves.
