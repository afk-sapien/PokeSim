PokeSim 0.2.0rc3 is an experimental self-hosting beta for Linux amd64.

This update fixes repeated route searches during collection planning, which could stall emulation for more than 30 seconds and delay shutdown. Candidate selection now shares one bounded search. The health threshold is unchanged.

The source archive now includes its Docker, Compose, proxy, and validation files. The endurance harness preserves failing health responses, marks stopped runs accurately, and recognizes campaign completion from the saved Hall of Fame count.

Supply your own supported Pokémon Red ROM and prepare game data locally using the README. Pokémon ROMs, sprites, and generated game datasets are excluded. PyBoy includes its own small demo ROM, which is not a Pokémon game. Public downloads require no GitHub account or registry login.

This is still an early beta. The first endurance run failed after about 96 minutes, despite its campaign log recording Hall of Fame entry. Replacement long-term validation remains incomplete. The policy can get stuck or make poor choices. ARM, Blue, and ROM hacks are not validated release targets.

See [installation instructions](https://github.com/afk-sapien/PokeSim/blob/main/README.md) and [current validation results](https://github.com/afk-sapien/PokeSim/blob/main/RELEASE_STATUS.md). Installation and gameplay feedback are welcome through GitHub issues. Use private vulnerability reporting for security problems.
