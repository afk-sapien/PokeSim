# Automatic trading between trusted adventures

The owner explicitly authorized live automatic trading on September 15, 2026 UTC.
The Red and Blue coordinator is enabled. Individual exchanges do not require further
approval. Other installations default to disabled until configured by their owner.

The coordinator checks each minute and permits one useful exchange every 15 minutes.
It waits for both games to reach unpaused, healthy overworld states. Authenticated
trade controls place durable holds on both games and create fresh checkpoints. Trading
briefly pauses the adventures and preserves their speed. It does not restart containers.

Spare boxed partners are eligible by default. Set `allow_last_copies` to true in the
private policy and its redacted public copy to let a final boxed partner travel when
it gives the recipient a new Pokédex registration. This does not erase the sender's
registration. It does give up that physical copy. Unique partners are never spent for
collection restoration or quality upgrades alone, preventing repeated return trades.
Active parties, current collection and training subjects, explicitly protected species,
and the best copy when several are held remain protected. Owners can protect additional
internal species IDs in `protected_species`.

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
only `enabled`, `interval_seconds`, `allow_last_copies`, `mew_event`, and `league_rewards`, and the completed exchange status. It never
receives peer tokens, ROMs, saves, or transaction backups.

Set `enabled` to true in both private and public policy files after configuring the
peers. Start the compose service with the exact release image. It continues independently
of the desktop session. Set private `enabled` to false to stop new exchanges, but leave
the coordinator running until any `active.json` transaction has recovered.

A process lock prevents concurrent coordinators. The latest 20 recovery directories
and 50 visible exchange records are retained. Small transaction markers remain in each
game's database to prevent duplicate journal delivery. Trade preparation expeditions
for missing peer requests remain future work.


## Optional Mew distribution

Set `mew_event` to true in the private policy and redacted public policy to enable a
one-time postgame gift for each configured instance. The normal coordinator must be
enabled. At a safe point after Champion, with a free box slot, it can deliver a level-5
Mew with Pound, ordinary random DVs, no stat experience, and original trainer POKESIM.
This is a custom PokeSim event, not an official Nintendo distribution or a hidden
cartridge quest. Original Red and Blue have no event switch to activate.

Delivery uses fresh held checkpoints, backups, staged verification, and the same durable
publication and recovery path as exchanges. Both games retain every existing Pokémon,
party member, item, and badge. The gift occupies a free slot. A persistent database
marker and existing Pokédex registration prevent another gift after a reload or trade.
The board lists gifts separately from completed exchanges. This initial event service
uses the existing two-peer coordinator. It is not a general event scheduling interface.

Current adventures keep their existing starter, fossil, and evolved Eevee. No resets,
extra Eevee supply, or starter farming are part of this feature.


## Championship rewards

Set `league_rewards` to true in private and public policy files, with the coordinator
enabled. Every newly observed Hall of Fame entry earns one random level-5 Pokémon from
Bulbasaur, Charmander, Squirtle, Eevee, Omanyte, Kabuto, Aerodactyl, and Mew. Each species
has equal probability. Gifts have ordinary DVs, zero stat experience, correct starting
moves and experience, and original trainer POKESIM. Duplicates are allowed.

Claims begin with victories observed after this upgrade. Existing historical victories
are not backfilled. The counter persists beyond the cartridge Hall of Fame counter's
limit. A database high-water mark prevents an older checkpoint replay from earning the
same claim again. Selection stays fixed across delivery retries. A full PC leaves the
claim pending, with no overwrite or loss. The coordinator delivers one pending reward
per eligible peer per cycle using the same held-checkpoint verification and recovery
as trades. Rewards bypass the trade interval and do not require a useful trade proposal.
There is no reward cooldown, roster qualification, or individual approval.

The board lists rewards separately from completed exchanges. Game state includes earned,
delivered, and pending counts under `league_rewards`. Keep the older `mew_event` false
when using this pool. Both adventures remain intact. A deliberate manual new-adventure
restart clears the reward ledger. Ordinary recovery and restarts of the server retain it.


## Independent safe points

The coordinator checks that both games are healthy, running, and have parties before
starting a useful operation. Each game then checks its current battle, text, and menu
state when asked to prepare. API snapshots do not need to show both games in the
overworld at the same instant.

Preparation shares one 15-second retry window across both games. Only the explicit
overworld-wait response is retried, at intervals of up to 250 milliseconds. Requests
already in flight retain their existing 20-second transport timeout. Other rejections
or an expired retry window abort the operation and release prepared peers. A failed
cleanup remains durable for the next coordinator cycle. The 15-minute trade interval,
reward fairness, and game-side checkpoint checks are unchanged.
