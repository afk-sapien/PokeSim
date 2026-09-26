# PokeSim 0.4.6 experimental beta

Fix first ROM uploads on fresh Docker and native installations.

## Automatic first-run setup

Versions 0.4.4 and 0.4.5 could reject a valid ROM with a misleading message asking for
a manual prepare-data command. Portrait generation tried to load reference data before
automatic setup and read from the legacy data directory.

ROM upload now saves and registers the cartridge without requiring reference data.
Starting the adventure automatically prepares the reference data, then generates portraits
from that library's verified data before launching the game. Existing custom portraits
are preserved. New installations need no extra setup command.

## Release checks

A new regression check starts in a fresh process and an empty library with no legacy
data. It uploads a cartridge through the Library API, prepares reference data, generates
portraits, starts a worker, saves, and restarts. The Docker quick-start check runs this
scenario in the built image before publication.

## Upgrading

Back up the library and select `ghcr.io/afk-sapien/pokesim:0.4.6` in your Compose file,
then run `docker compose pull` and `docker compose up -d --wait`. Keep your existing
data mount and project name. Retry the ROM upload if it previously failed.

Native installations can rerun the installer to select 0.4.6. No game-data or save-format
migration is introduced by this release. First adventure setup still needs internet
access unless a local reference archive or prepared reference directory is supplied.

Docker images remain Linux amd64. Use the native Python installer on supported ARM64 systems.
