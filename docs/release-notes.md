# PokeSim 0.4.8 experimental beta

PokeSim now uses [PokeSim Core](https://github.com/afk-sapien/pokesim-core), the
shared package also used by PokeAgent Bench.

## Shared game data decoding

Core 0.1.1 supplies ROM identities, Red and Blue memory addresses, text and numeric
decoding, individual Pokémon fields, and party and bag reads. Shared decoding
fixes can now be maintained in one package and adopted by both applications.

PokeSim keeps its UI, automation, trading, emulator lifecycle, and save management.
Native installers and Docker install the pinned Core package automatically.
No additional setup, save-format change, or database migration is required.

See the [shared-core guide](shared-core.md) for ownership and coordinated updates.

## Upgrading

Back up the library and select `ghcr.io/afk-sapien/pokesim:0.4.8` in your Compose file,
then run `docker compose pull` and `docker compose up -d --wait`. Keep your existing
data mount and project name. Native installations can rerun the installer.

This release includes the first-upload setup fix from 0.4.6 and the Porygon,
Power ranking, and compact Pokémon details improvements from 0.4.7.

Docker images remain Linux amd64. Use the native Python installer on supported ARM64 systems.
