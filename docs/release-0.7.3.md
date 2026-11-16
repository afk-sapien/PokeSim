# PokeSim 0.7.3 release

Postgame adventures keep collecting. A full PC can release again, a shiny met with a full party
finds a box slot, a Crystal run breeding at the Day Care gets its Odd Egg, and a finished Gold,
Silver or Crystal run that is still catching and hatching no longer raises the stall alert.

See the [changelog](../CHANGELOG.md#073) for every change.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.7.3`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). pokecore stays at 0.12.2 and PyBoy RS at 0.1.6.

0.7.3 does not change the Library database or the save format, so adventures continue from
their saves.
