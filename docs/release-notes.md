# PokeSim 0.4.14 experimental beta

Follow your adventure's long-term progress in the new Journal Stats page.

- Journal has separate Entries and Stats pages with matching panel tabs.
- Track total collection power, strongest-six power, average DVs and level,
  Pokémon held and caught, steps, battles, marathons, game hours, and observed damage.
- Existing Pokédex, level 100, perfect-find, and League history remains available.
- Charts have labeled scales and a date range. Missing measurements stay unknown.
- Colored Pokémon type badges appear across the live team, Pokédex, and PC.

New activity tracking begins with this update. Existing verified capture receipts
and marathon journal records are included. Steps and damage are sampled totals.
See [adventure statistics](adventure-statistics.md) for counting and retention rules.

## Upgrading

Back up the complete library and select `ghcr.io/afk-sapien/pokesim:0.4.14` in Compose,
then run `docker compose pull` and `docker compose up -d --wait`. Keep your existing
data mount and project name. Native installations can rerun the installer.

Existing saves remain compatible. Startup adds a statistics history table and an
index to each adventure database. Core remains at 0.1.2. Docker images remain
Linux amd64. Use the native Python installer on supported ARM64 systems.
