# PokeSim 0.6.0

This release rebuilds how the bot picks what to do next, adds randomized adventures,
and stops the library growing without bound. It also gives Gold, Silver and Crystal
the journal, stats and Pokédex that Red, Blue and Yellow already had.

- **A new planner in all six games.** One shared arbiter now weighs every goal, from the
  story and errands to hunts, training and the postgame, by what it is worth and how long
  it takes. The fixed timers, retry loops and special-case rules it replaces were behind
  most stalls, such as walking in and out of Victory Road, pacing a gate or a Pokémon Center,
  or running the League again while other work was left. Hunts and training trips now get
  a time allowance that grows back while they make progress. The goal under way also decides
  whether to fight, run from or catch a wild Pokémon.
- **Randomized adventures ([#107](https://github.com/afk-sapien/PokeSim/issues/107)).** New
  adventure can shuffle wild Pokémon, starters and optionally trainer parties from a seed, in
  all six games. Each run gets a share code such as `PSR1-RED-WS-12345` that recreates the
  same world. Red, Blue and Yellow can also turn on Fair wild DVs.
- **Smaller libraries ([#227](https://github.com/afk-sapien/PokeSim/issues/227)).** Gold,
  Silver and Crystal journal saves are now compressed, about thirteen to one. Journal
  screenshots and saves for routine entries are kept only for the newest 500 per adventure,
  set with the new `EVENT_ATTACHMENT_KEEP` setting (0 keeps all). Milestones keep theirs
  forever, and every journal entry's text is kept. Delivered custom rewards and Champion
  counter purchases no longer keep a save each.
- **Gold, Silver and Crystal catch up.** They now write the same journal entries, count
  battles, catches, trades, purchases and money, and show the same Stats and Pokédex pages
  as Red, Blue and Yellow. They gain the Johto Marathon, keep running after an unexpected
  error, and free box space when every box is full.
- **New stats.** A panel shows what the bot is working on and where its time goes, plus
  money earned and spent, catch pace, and lifetime battle tallies.
- **Viewing.** A stopped adventure opens read only from its newest save. The sound buffer
  is picked automatically: watching keeps audio and video smooth and in sync, and Take
  Control drops the delay for the lowest input lag.

See the [changelog](../CHANGELOG.md#060) for every change.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.6.0`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md).

- **First start takes a little longer.** Existing Gold, Silver and Crystal journal saves are
  compressed in the background on first start, which can take a few minutes for a large
  library. Adventures run normally meanwhile.
- **Older attachments are trimmed.** Once the update runs, routine journal entries beyond the
  newest 500 per adventure lose their screenshot and save. Set `EVENT_ATTACHMENT_KEEP=0`
  before upgrading to keep them all.
- **Core is now `pokecore`.** This release needs pokecore 0.10.2 and PyBoy RS 0.1.4. The
  installers and `uv sync` remove the old `pokesim-core` package. With pip, run
  `pip uninstall pokesim-core` before upgrading.
- **Saves.** Saves and checkpoints from 0.5.3 load unchanged. Older releases cannot read a
  compressed Gold, Silver or Crystal journal save, so after rolling back to 0.5.3 those journal
  entries cannot be rewound to. Restore the backup taken before the upgrade to keep them.

See the [0.5.3 release notes](release-0.5.3.md) for the previous patch, the
[0.5.0 release notes](release-0.5.0.md) for the 0.5.0 update and its known
limitations, and [release status](../RELEASE_STATUS.md) for remaining limits.
