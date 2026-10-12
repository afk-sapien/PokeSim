# Trading

Use this guide for the Trading page, locks, and broker connection
settings. See [automatic trading](automatic-trading.md) for coordinator setup,
exchange rules, and recovery.

## Trading page

Everything about trading lives on each adventure's Trading page at
`/games/{id}/trading`. Trading in 0.5.0 is one of two things: automatic trades,
which start on their own, and trades you build by hand between your own
adventures. The page is one page, top to bottom:

1. The **Automatic trading** status box, with the on/off switch, a note on the
   rules and the wish list, folded away under the switch.
2. **Current exchange**, for trades that are waiting or running, on the pages of
   both adventures. It is hidden when there is none.
3. **Make a trade** builds a trade by hand: another adventure, the Pokémon you
   send and the Pokémon you get.
4. **History** shows hand-picked and automatic trades together, newest first.

Older links with `?tab=trade`, `?tab=auto` or `?tab=history` scroll to the
matching section, and `&mon=` with a trade key preselects a Pokémon to send. The
PC's **Trade…** link opens Make a trade with that Pokémon chosen.

The library has no trading page. It has Library, Notifications and Settings, and
the old `/trading` and `/trade` addresses redirect to the library.

A game run on its own, outside the library, serves its own `/trading` page with
Possible exchanges and History. Opportunities come from the shared broker, which
library adventures do not use. The shared broker remains an internal read API. Its old root page redirects to the configured game or directs visitors
to their game navigation.

## Locks

Every Pokémon can be traded automatically unless it is locked. Lock one on the PC
page: press the Pokémon, then press **Locked: never traded** in its popup. The
same key unlocks it. A locked Pokémon has a lock icon on its card in the PC grid
and the party. A view link shows the lock but cannot change it.

A locked Pokémon is never traded automatically, and automatic PC release never
releases it. You can still pick it by hand in Make a trade. A lock also protects a
Pokémon in the party from the in-game trader. Shiny and perfect DV Pokémon are
always protected, and the popup shows them as Protected instead of a lock key.

Locks use the stored trade setting, so locks and Never trade choices from earlier
releases carry over unchanged. The stored values are `auto`, `offered` and
`locked`. An older Prefer to trade choice still ranks that Pokémon first in
automatic trading, and the PC shows it as unlocked.

Locks persist across box moves, renaming, evolution, ordinary restores, and
server restarts. Starting a new adventure clears them. The emulator saves a change
between input actions and discards pending inputs before resuming. Release
confirmations and trade checkpoint staging recheck the lock, so a Pokémon locked
after it was selected is not released or traded.

## Automatic trading

The status box at the top of the Trading page has a switch that turns automatic
trading on or off for this adventure.
Switching it off stops only automatic trades. Other adventures still collect for
it, and trades you pick by hand still reach it. The overview shows Off for an
adventure with automatic trading switched off.

The wish list names species this adventure wants. A wished species it holds none of
makes an exchange worth doing even when the Pokédex does not need it, and such an
exchange is ranked ahead of every other.

Automatic trades start by themselves when a useful exchange is ready, with no
approval step. The status box reads **On, trades automatically**.

Automatic trading also follows fixed rules that no setting changes:

1. A shiny Pokémon never travels automatically.
2. The last copy of a species stays home, unless the trade evolves it or registers
   a new Pokédex entry for the other adventure.
3. Active party members and Pokémon in a project stay home.
4. A Pokémon in a hand-picked trade is left for that trade.

Trades you pick by hand ignore locks and these rules. Only the limits in
[Make a trade](#make-a-trade) apply to them.

## Make a trade

Make a trade runs one exchange you choose:

1. Choose the adventure to trade with from **Trade with**. One that cannot trade
   says why: view only, stopped, archived or busy finishing another trade.
2. Press **You send** and pick one of this adventure's Pokémon, from the party or
   the PC. The picker opens over the page with search, filters and sorting.
   Escape or the close button shuts it.
3. Press **You get** and pick the Pokémon you want back. Pokémon the cable cannot
   take are greyed out with the reason, and so is the whole list when the Pokémon
   you send cannot go to that adventure.
4. Press **Trade**. It is enabled once both slots are filled.

Press a chosen Pokémon to see its details, or **Change** to pick another one.

The trade is queued at once and the page scrolls to it under Current exchange,
where it stays until it finishes, then moves to History. Locks, party
protection, the last-copy rule and automatic ranking do not apply. The trade is
yours to make.

Only limits the cable itself cannot get past stop a pair, and the page says why:

1. Eggs, and a Pokémon that shares its trainer and stats with another one so it
   cannot be picked out safely.
2. In Gold, Silver and Crystal, the only party member that can still battle.
3. Through the Time Capsule, a Gen II adventure that has not unlocked it yet, and
   Pokémon past number 151, Pokémon with Gen II moves or Pokémon holding Mail.
4. Adventures that are stopped, archived, busy finishing another trade, under
   your control, or busy with an event such as the Battle Tower.

Each adventure walks to a Pokémon Center, uses the PC if the chosen Pokémon is
boxed (sending any party member to the PC if the party is full), and meets the
other at the Cable Club. The trade then goes through the same checked cable
exchange as automatic trades. A trade you choose goes before any automatic one.
An automatic trade that is still travelling is set aside for it, and chosen
trades wait in line, oldest first, while the Cable Club is busy. Once both saves
are being committed the trade always finishes.

View links, `VIEWER_ONLY` instances and adventures whose settings make them view
only cannot build a trade, and the server refuses it.

## Removed in 0.5.0

Trade offers and manual Cable Club sessions, where you held both controllers, are
switched off in 0.5.0 to keep trading simple. Their tabs, pages and API routes are
gone. Offers and sessions saved by an earlier build stay in the Library database
but are ignored: they do not hold back automatic trades and are never answered or
resumed. A session that was running when an earlier build stopped is still rolled
back to both Pokémon Center saves at startup.

The **Ask me first** switch and its Accept and Dismiss suggestions, from 0.5.0
release candidates, are gone too, and automatic trades start on their own as
before. The `/api/v1/interactions/trade-requests` routes return 404. A stored
Ask me first setting and any waiting suggestions are ignored.

## Trading API

The trade builder is under `/api/v1/interactions/trade-builder`:

- `GET /pokemon?adventure_id=` lists every Pokémon an adventure could trade by
  hand, with the hard limits marked.
- `GET /targets?from_id=` and `GET /limits?from_id=&from_key=&to_id=` feed the
  Make a trade section. Targets mark a view-only adventure unavailable with its reason.
  Limits include the other side's Pokémon and `starts_now`.
- `POST` queues a trade from `from_id`, `from_key`, `to_id`, `to_key` and an
  optional `request_id`, and returns its place in the queue. Sending the same
  `request_id` again returns the trade it already queued.

`GET /games/{id}/api/interactions` lists waiting trades under `queued`, beside
`active` and `history`. The older `/api/v1/interactions/manual-trades` admin API
is gone.

`GET /api/v1/interactions/auto-settings?adventure_id=` reads the switch and wish
list, and `PUT` with `enabled` and `wishlist` (a list of Pokédex numbers, up to 50)
saves them. A game's own `POST /api/trading/preferences` sets one Pokémon with
`key` and `state`: `keep` locks it and `auto` unlocks it. `first` (Prefer to
trade) is still accepted.

Locks are saved per game in SQLite, separately from cartridge checkpoints.
Neither generation stores a unique ID for each Pokémon, so a partner is known by
its trainer ID, its DVs and its evolution family. The family is every species
linked by evolution in Red, Blue, Yellow, Gold, Silver or Crystal, named by its
lowest Pokédex number. That keeps a partner's key through box moves, renaming,
training, evolution and the Time Capsule: Pichu, Pikachu and Raichu share one
family, and Tyrogue shares one with Hitmonlee, Hitmonchan and Hitmontop because
it can become any of them. Two different species that share a trainer and DVs,
which emulator reloads and Day Care breeding both produce, have different keys
and trade normally. Only two Pokémon of the same family with the same trainer
and DVs remain impossible to tell apart. Their settings are suspended, their
controls are disabled and the reason reads "Another Rattata from the same
trainer has identical stats, so the game can't tell them apart". Older
snapshots without identity data retain read-only automatic offers.

Releases before 0.5.0 keyed partners by trainer ID and DVs alone. The first
time an adventure reads its whole collection, a setting saved under an old key
moves to the new key when exactly one held Pokémon has that trainer and those
DVs. When several species share them, the setting stays under the old key and
applies to none of them, so set it again on the one you meant. Trades
in progress and League rotation counts saved with an old key still find their
Pokémon by the same rule: exactly one match, or the trade stops.

The staged checkpoint calculation reads the same saved settings as the broker.
Writes are blocked while an exchange holds the game. A completed exchange clears
the sender's setting in the same database transaction as its journal entry.
A deliberate new-adventure restart clears all locks.

## Connecting an installation

Set these environment values in each game service:

- `TRADING_URL`: The server-reachable base URL of the existing broker.
- `TRADING_INSTANCE`: The broker's exact instance key, normally `red` or `blue`.

For example, a game container on the same Docker network as the broker can use
`TRADING_URL=http://broker:8000`. Set `TRADING_INSTANCE=red` in Red and
`TRADING_INSTANCE=blue` in Blue. If the instance is omitted, the game version is
used. These values contain no peer tokens. The browser only calls its own game's
API. The broker and coordinator still use their existing private configuration,
public status mount, and authenticated game controls.

Set `BROKER_GAME_URL` on the broker to a browser-reachable game base URL to redirect
its old webpage to that game's `/trading` page. The broker's `/api/proposals` route
remains available to the coordinator. Deploy the games, broker, and coordinator
from the same revision so displayed offers and checkpoint validation agree.

When disconnected, the PC disables the lock key, shows a reconnecting message,
and preserves saved choices. `VIEWER_ONLY` blocks preference writes on the server.

Automatic trades preserve the last held Articuno, Zapdos, Moltres, Mewtwo, or
Mew in each adventure, even when another adventure needs its Pokédex entry.
An older Prefer to trade choice on a boxed partner can override this protection.
Party, shiny, perfect DV, and lock protections still apply.
