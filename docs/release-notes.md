# PokeSim 0.7.5 release

Deep postgame adventures play faster with the same decisions, the emulator moves to PyBoy RS
0.1.9, and Flash lights the dark caves in all six games.

## Faster on deep saves

Gold, Silver and Crystal keep each answer they derive from the game, such as the PC rating,
training projects, hunt helpers and in-game trade counts, until the memory it reads changes.
Their rung builds copy and replace only what they change. Red, Blue and Yellow decode only the
party, box and Pokédex regions that changed since the last step, as Gen II already did.

Wall time for one game hour, seed 7, on PyBoy RS 0.1.7 with the compiled route search the image
installs, the mean of two runs each, before this work and after it:

| Save | Played | Before | After |
|---|---|---|---|
| Red | 17,136 hours | 37.9 s | 32.8 s |
| Gold | 6,873 hours | 54.5 s | 39.7 s |
| Crystal | 6,680 hours | 65.9 s | 46.9 s |

Each replay made the same decisions on the same frames before and after.

## PyBoy RS 0.1.9

On the same three deep saves, one game hour each, PyBoy RS 0.1.9 made the same decisions on
the same frames as 0.1.7. With this release's code on both, a game hour took:

| Save | 0.1.7 | 0.1.9 |
|---|---|---|
| Red | 32.9 s | 31.0 s |
| Gold | 39.7 s | 38.5 s |
| Crystal | 46.8 s | 45.5 s |

## Gameplay

- Flash lights Rock Tunnel in Red, Blue and Yellow and the dark caves of Gold, Silver and
  Crystal, so viewers see them.
- A lost first rival fight in Oak's Lab no longer holds a fresh Red, Blue or Yellow game in
  Viridian City, and Pikachu walking up to Bill no longer blocks his door in Yellow.
- A Gold, Silver or Crystal wild battle that a map script started is fought, not run from.
- Gold, Silver and Crystal walk a straight run of plain tiles as one held press.
- Twin Pokémon, two with the same trainer, DVs and family, can be traded, told apart by
  nickname.

See the [changelog](../CHANGELOG.md#075) for every change.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.7.5`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). pokecore moves to 0.12.4 and PyBoy RS to 0.1.9.

0.7.5 does not change the Library database tables or the save format, so adventures continue
from their saves. A twin's trade setting is stored beside its family's setting, so a return to
0.7.4 still keeps both twins.
