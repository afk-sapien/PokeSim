PokeSim 0.2.0rc10 fixes false training completion during PC withdrawals. The game briefly exposes the previous party slot's level while copying a stored Pokémon. The director now waits for battle or overworld observations before accepting training progress.

The reproduced withdrawal previously credited a level-43 Graveler with reaching level 100. With the fix, the same copied save gained 8088 experience and reached level 44 through battle while keeping its level-50 project active. Blue's current-save regression also continued gaining levels.

All 383 tests passed, with one optional checkpoint test skipped. Both live adventures run the tagged revision with fresh cold backups and verified save compatibility. All 12 public endpoint checks passed. Existing Pokémon and save histories are preserved.

The rc9 live interval showed level gains in both games, a confirmed ground-item pickup in Red, and no observed save reloads. Collection efficiency and multi-day endurance remain open. Historical training counters may include earlier false completions and remain preserved.

See [release status](../RELEASE_STATUS.md), [the roadmap](roadmap.md), and [deployment details](homeserver.md).
