# Automatic trading between trusted adventures

The owner can enable ordinary automatic exchanges for the local Red and Blue pair.
The current request to make trading common authorizes enabling that policy on this
pair. The earlier proposal-only milestone and per-exchange approval requirement are
superseded for eligible routine trades. Other installations default to disabled.

The coordinator checks once a minute and allows one useful exchange every 15 minutes.
It waits while either game is paused, unhealthy, in a battle, or displaying a menu or
text box. Both games pause and stop briefly at an overworld checkpoint. Their current
speed settings are preserved. No network-facing endpoint can execute a trade.

Eligible exchanges use spare boxed partners. Party members, the best retained copy of
each species, last copies, and current collection or training subjects are protected.
Owners can protect additional internal species IDs in `protected_species`. The worker
rechecks the exact stopped checkpoints instead of trusting an earlier board proposal.

New Pokédex entries and trade evolutions come first. Already registered species can
still provide a useful upgrade: at least five levels, four total DVs with a similar
level, or 20,000 stat experience without a lower level. One side may help its peer by
sending a spare, but neither spends a protected copy. There is no level-90 price rule
for routine exchanges. A schedule never forces a swap with no collection or training
benefit. Shortages still require ordinary catching and training.

Each exchange backs up the two source checkpoints, manifests, and SQLite databases.
Both outputs are staged and verified before publication. Party contents, badges, box
counts, unrelated slots, incoming individual data, and Pokédex registration are checked.
A durable transaction decision controls recovery. Before commitment, recovery removes
both outputs. After commitment, it finishes journaling and starts both games without
applying the swap again. Journal entries and transaction markers commit together.

The latest trade marker must match restored checkpoints. This prevents a later
recovery or manual rewind from restoring an inventory from before a completed trade.
Unversioned event rewinds are unavailable after trading. New autosaves retain the
marker. Explicitly starting a new adventure clears that adventure's marker.

The board displays completed exchanges and upcoming opportunities. It mounts the
coordinator directory read-only and cannot access ROMs or saves. The worker is a
separate local operator process with explicit paths to the two trusted games.

## Container installation

The live installation uses `deploy/compose.trading.yaml` and a committed tools
directory selected with `TRADING_SOURCE`. It runs the coordinator every minute using
the host's existing Docker client and socket. It requires operator-level Docker access
and mounts only the configured games' data plus its recovery directory. The client
must be compatible with the release image. The games and browser-facing board never
receive the Docker socket. Set the exact `POKESIM_IMAGE` tag, configure `policy.json`
as below, and start the compose service. This persists without a desktop session.

## Alternative host service installation

Deploy the same tagged release to both games and the board first. Copy
`tools/trade_pair.py` into `/docker/pokesim-trading/trade_pair.py`. Copy
`deploy/trading-policy.json.example` to `/docker/pokesim-trading/policy.json`, set the
exact image tag, paths, and trusted peers, then set `enabled` to true.

Give the broker a read-only `/docker/pokesim-trading:/trading:ro` mount and set
`BROKER_TRADING_DIR=/trading`. Install `deploy/pokesim-trading.service` and
`deploy/pokesim-trading.timer` into `/etc/systemd/system`, reload systemd, and enable
the timer. The host runner needs Python 3 and Docker access. The image supplies PyBoy
and the game code. Only the local trusted coordinator receives access to both saves.

Set `enabled` to false to stop new exchanges. Keep the timer running until any existing
`active.json` transaction is recovered. A root lock prevents concurrent coordinators.
The worker keeps the latest 20 recovery directories and 50 visible exchange records.
Completed transaction IDs remain in each game's database for idempotent recovery.
