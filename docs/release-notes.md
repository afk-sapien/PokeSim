# PokeSim 0.4.7 experimental beta

Fix Game Corner prize confirmation and make Pokémon collection rankings clearer.

## Porygon purchases

Recognize the active Yes/No popup when the Game Corner leaves an older prize-menu
cursor on screen. The player can confirm the purchase instead of repeatedly moving
the wrong cursor and abandoning the expedition. Existing adventures can retry their
Porygon project without starting over.

## Pokémon collection

All Pokémon defaults to Power, highest first. Power now estimates offensive strength,
durability, and speed instead of adding every stat equally. The original sum remains
available as Stat total. Scores reflect each individual's level, DVs, and training.

Pokémon details show the stats and counts without the long explanatory paragraphs.
The Stats guide link opens the repository documentation. Separate guides cover
Pokémon stats, PC storage, and trading.

## Upgrading

Back up the library and select `ghcr.io/afk-sapien/pokesim:0.4.7` in your Compose file,
then run `docker compose pull` and `docker compose up -d --wait`. Keep your existing
data mount and project name. Native installations can rerun the installer.

This release includes the first-upload setup fix from 0.4.6. No save-format or database
migration is introduced. The inventory API's `power` field contains the new weighted
score, and `stat_total` contains the former unweighted sum.

Docker images remain Linux amd64. Use the native Python installer on supported ARM64 systems.
