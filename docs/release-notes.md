# PokeSim 0.4.16 experimental beta

Custom nicknames, more varied League teams, and a shared Core for game mechanics.

- Add your own nickname prefixes and suffixes in global Settings. They extend
  the clean default vocabulary and apply to future names, including League gifts.
  Existing Pokémon keep their names. Restore defaults at any time.
- League rematches can bring one eligible reserve into the team. Rotation favors
  Pokémon with fewer recorded appearances, while protecting the strongest member,
  required field moves, trade locks and a minimum strength threshold. First-time
  League runs and rematches already underway keep their existing teams.
- Adopt PokeSim Core 0.1.4 for name entry, cached screen and box decoding, menu
  selection and event flag updates. The benchmark shares Core's item-use and
  party-switching mechanics. Adventure strategy, reward timing and trade policy
  remain in their respective applications.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.4.16`
in Compose, then run `docker compose pull` and `docker compose up -d --wait`.
Keep your existing data mount and project name. Follow the
[desktop installation guide](desktop.md) for a package-based installation.

Custom nickname lists start empty. Existing names, game speeds, walking rewards
and adventure progress are preserved. League rotation applies when selecting
new rematches. This release does not introduce DV training or change battle DVs.

Core's reset helpers are explicit trusted operations. They do not create new
rewards or change existing step thresholds, and benchmark agents cannot call them.
See [shared Core](shared-core.md) and [Pokémon stats](pokemon-stats.md) for details.

Docker images target Linux amd64. Native Python installation supports the
documented desktop and ARM64 platforms. Gameplay remains an experimental beta.
