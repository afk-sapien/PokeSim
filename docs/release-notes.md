# PokeSim 0.4.9 experimental beta

Use DV rarity and long-term potential to choose which Pokémon deserve training.

## Smarter investment

- Show estimated DV quality, chance of a higher roll, and potential Power in
  compact Pokémon details. Full explanations stay in the repository stats guide.
- Favor exceptional DV candidates, even at low levels. Require at least 2% more
  potential Power before training a replacement for a level-100 partner, with
  perfect finds kept as the collection exception.
- Search for better ordinary candidates for at most three expeditions before
  proceeding with training. The budget survives restarts, and difficult-to-replace
  partners and already developed partners can train without this delay.
- Keep both future potential and current strength. A veteran can be released only
  once another copy catches up in current Power. Protect top-0.5% finds from
  automatic release and trading. Explicit offers can override investment protection,
  while locks and perfect-Pokémon protections remain in force.

The shared DV math lives in PokeSim Core 0.1.2. Probabilities use a uniform reference
model, not measured cartridge encounter odds. Potential Power compares the same
species at level 100 with maximum training. See [Pokémon stats](pokemon-stats.md).

## Upgrading

Back up the library and select `ghcr.io/afk-sapien/pokesim:0.4.9` in your Compose file,
then run `docker compose pull` and `docker compose up -d --wait`. Keep your existing
data mount and project name. Native installations can rerun the installer.

Existing adventures and checkpoints remain compatible. The optional search-budget
field starts empty in older checkpoints. No database migration is introduced.
Docker images remain Linux amd64. Use the native Python installer on supported ARM64 systems.
