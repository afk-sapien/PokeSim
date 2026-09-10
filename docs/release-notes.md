Experimental self-hosting beta for Linux amd64.

pokesim plays a locally supplied Pokémon Red ROM, streams the adventure to your browser, and records catches and milestones in a journal and Atom feed. Optional ntfy notifications are supported. Game decisions run locally without a model API or account.

Download image-linux-amd64.tar.gz and SHA256SUMS, verify the checksum, then load the archive with Docker. The README provides the full anonymous download, local game-data preparation, and Docker Compose setup. Source packages, Compose settings, dependency inventory, and an image manifest are attached too.

The release excludes Pokémon ROMs, sprites, and generated game datasets. PyBoy includes its own small demo ROM, which is not a Pokémon game. Supply your own supported ROM and prepare the data locally. Original code is MIT licensed. Other content has separate rights.

This is an early beta. The policy may get stuck, ARM and Blue are not validated release targets, and the first endurance run stopped after about 96 minutes following a campaign health failure. The campaign log recorded Hall of Fame entry, but the 48-hour reliability check remains incomplete. See [current validation results](https://github.com/afk-sapien/PokeSim/blob/main/RELEASE_STATUS.md). Installation and gameplay feedback are welcome through GitHub issues. Use the repository's private vulnerability reporting form for security problems.
