# Automatic trading between trusted adventures

The owner explicitly authorized live automatic trading on September 15, 2026 UTC.
The Red and Blue coordinator is enabled. Individual exchanges do not require further
approval. Other installations default to disabled until configured by their owner.

The coordinator checks each minute and permits one useful exchange every 15 minutes.
It waits for both games to reach unpaused, healthy overworld states. Authenticated
trade controls place durable holds on both games and create fresh checkpoints. Trading
briefly pauses the adventures and preserves their speed. It does not restart containers.

Only spare boxed partners are eligible. Active parties, current collection and training
subjects, last copies, and the best retained copy of each species are protected. Owners
can protect additional internal species IDs in `protected_species`.

New Pokédex entries and trade evolutions come first. Already registered species can
provide upgrades of at least five levels, four total DVs at a comparable level, or
20,000 stat experience without a lower level. A run may help its peer with a spare.
There is no level-90 price requirement and no quota forcing useless swaps.

The worker rechecks the held checkpoints and backs up their states, manifests, and
SQLite databases. It stages both outputs and verifies parties, badges, box counts,
unrelated slots, incoming individual data, and Pokédex registration before publication.
A durable decision controls recovery. Before commitment, recovery discards staged
outputs and releases both games from their original checkpoints. After commitment,
it finishes journaling, loads both exchanged inventories, and then releases the holds.
A retry after release never reloads the same trade and rewinds subsequent progress.

Holds survive game restarts. Shutdown cannot autosave old memory over a prepared trade.
The latest trade marker must match restored checkpoints, so a later recovery cannot
undo one side of an exchange. Unversioned event rewinds become unavailable after trading.
New autosaves preserve the marker. Starting an entirely new adventure clears it.

## Installation and access

Use `deploy/compose.trading.yaml` with the same tagged release as both games. The
coordinator runs as UID 10001 with capabilities dropped and a read-only container
filesystem. It has read/write access to the two configured game data directories and
its recovery directory, plus read-only ROM and game-data mounts. It has no host Docker
socket, Docker client, or root identity.

Put private configuration in `/docker/pokesim-trading/state/policy.json` using
`deploy/trading-policy.json.example`. Set a different random token for each peer and
supply that token as `TRADE_TOKEN` in the corresponding game container. Keep the private
configuration readable only by UID 10001. An empty token disables the game's trade API.
Tokens authorize only prepare, load, release, and abort for a numeric transaction ID.
The ordinary resume and rewind controls cannot bypass a held exchange.

The board mounts only `/docker/pokesim-trading/state/public` as `/trading:ro`, with
`BROKER_TRADING_DIR=/trading`. That directory contains a redacted `policy.json` with
only `enabled` and `interval_seconds`, and the completed exchange status. It never
receives peer tokens, ROMs, saves, or transaction backups.

Set `enabled` to true in both private and public policy files after configuring the
peers. Start the compose service with the exact release image. It continues independently
of the desktop session. Set private `enabled` to false to stop new exchanges, but leave
the coordinator running until any `active.json` transaction has recovered.

A process lock prevents concurrent coordinators. The latest 20 recovery directories
and 50 visible exchange records are retained. Small transaction markers remain in each
game's database to prevent duplicate journal delivery. Trade preparation expeditions
for missing peer requests remain future work.
