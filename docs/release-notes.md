# PokeSim 0.4.13 experimental beta

Recognize Pokémon types at a glance with consistent colored badges.

- Grass is green, Poison is purple, and every Generation I type has its own color.
- Badges appear on live team cards and details, Pokédex cards and details,
  Pokédex move types, and PC cards and details.
- Type names remain visible, with high text contrast in light and dark themes.
  The layout also fits 320-pixel phone screens.

## Upgrading

Back up the library and select `ghcr.io/afk-sapien/pokesim:0.4.13` in your Compose file,
then run `docker compose pull` and `docker compose up -d --wait`. Keep your existing
data mount and project name. Native installations can rerun the installer.

Existing saves remain compatible. There is no database migration. Core remains at 0.1.2.
Docker images remain Linux amd64. Use the native Python installer on supported ARM64 systems.
