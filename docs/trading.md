# Trading

Use this guide for the Trading page, trade settings, and broker connection
settings. See [automatic trading](automatic-trading.md) for coordinator setup,
exchange rules, and recovery.

## Trading page

Everything about trading lives on each adventure's Trading page at
`/games/{id}/trading`. Trading in 0.5.0 is one of two things: automatic trades,
which become suggestions to accept or dismiss while [Ask me first](#ask-me-first)
is on, and trades you build by hand between your own adventures. The page has
three tabs:

1. **Trade** builds a trade by hand: another adventure, the Pokémon you send and
   the Pokémon you get.
2. **Auto** holds the automatic trading switch, the wish list and each Pokémon's
   trade setting.
3. **History** shows hand-picked and automatic trades together, newest first.

Trades that are waiting or running show under **Current exchange** above the
tabs, on the pages of both adventures.

The page remembers the last tab in the browser. A link can open a tab with
`?tab=trade`, `?tab=auto` or `?tab=history`, and `&mon=` with a
trade key preselects a Pokémon on the Trade tab. The PC shows each Pokémon's
trade setting read only, with a **Trade…** link that opens the Trade tab with that
Pokémon chosen.

The library's Trading page lists every adventure under **Make a trade**, each
linking to that adventure's Trade tab. The old library-wide picker at `/trade`
now redirects there.

A game run on its own, outside the library, serves its own `/trading` page with
Auto, Opportunities and History tabs. Its Auto tab is the only place such a game
sets trade settings, and Opportunities shows the shared broker's matches, which
library adventures do not use. The shared broker remains an internal read API. Its old root page redirects to the configured game or directs visitors
to their game navigation.

## Trade settings

Each Pokémon has one trade setting. It only steers automatic trading:

- **Can trade**, the default. Automatic trading may use it when it is a spare.
- **Prefer to trade**. Automatic trading uses it before other spares.
- **Never trade**. Never suggested automatically, and automatic PC release never
  releases it. You can still pick it by hand.

Never trade also protects a Pokémon in the party from the in-game trader.
Shiny and perfect DV Pokémon are always protected. They cannot be set to Prefer
to trade, and the PC shows them as Protected. Upgrading converts older choices
once: a lock becomes Never trade, a withdrawn offer becomes Never trade, and an
offer becomes Prefer to trade. The stored values are still `auto`, `offered` and
`locked`, so an older release reads them. Releases before 0.5.0 called these
settings Auto decides, Trade first and Keep.

Settings persist across box moves, renaming, evolution, ordinary restores, and
server restarts. Starting a new adventure clears them. The emulator saves a change
between input actions and discards pending inputs before resuming. Release
confirmations and trade checkpoint staging recheck the setting, so a Pokémon set
to Never trade after it was selected is not released or traded.

## Automatic trading

The Auto tab has a switch that turns automatic trading on or off for this adventure.
Switching it off stops only automatic trades. Other adventures still collect for
it, and trades you pick by hand still reach it. The overview shows Off for an
adventure with automatic trading switched off.

The wish list names species this adventure wants. A wished species it holds none of
makes an exchange worth doing even when the Pokédex does not need it, and such an
exchange is ranked ahead of every other. Pokémon set to Prefer to trade come next.

### Ask me first

**Ask me first** is one switch for the whole library, on the Auto tab, and it
starts on. While it is on, automatic trading does not start a trade by itself. It
suggests its best exchanges instead, at most three at a time, and never two that
share a Pokémon. Each suggestion shows at the top of the Trading page of both
adventures as a card with the two Pokémon, why it was suggested, and **Accept**
and **Dismiss**.

Accept queues the trade like one you picked by hand, after checking both Pokémon
again. Dismiss hides it, and the same pair is not suggested again for seven
days. A suggestion expires by itself when either Pokémon stops being available
for automatic trading: it moved to the party, evolved, was traded, or was set to
Never trade. It also expires when its adventure turns automatic trading off, is
archived or is deleted. A stopped adventure keeps its suggestions until it runs
again. Switching Ask me first off drops waiting suggestions, and automatic trades
then start on their own as before.

The page reads suggestions from
`GET /api/v1/interactions/trade-requests?adventure_id=` and answers them with
`POST /api/v1/interactions/trade-requests/{id}/accept` or `/dismiss`.
`PUT /api/v1/interactions/trade-requests/settings` with `{"ask_first": false}`
switches it off.

Automatic trading also follows fixed rules that no setting changes:

1. A shiny Pokémon never travels automatically.
2. The last copy of a species stays home, unless the trade evolves it or registers
   a new Pokédex entry for the other adventure.
3. Active party members and Pokémon in a project stay home.
4. A Pokémon in a hand-picked trade is left for that trade.

Trades you pick by hand ignore trade settings and these rules. Only the limits in
[Make a trade](#make-a-trade) apply to them.

## Make a trade

The Trade tab runs one exchange you choose:

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

The trade is queued at once and the History tab opens. The trade shows under
Current exchange until it finishes, then in History. Trade settings, party
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

## Trading API

The trade builder is under `/api/v1/interactions/trade-builder`:

- `GET /pokemon?adventure_id=` lists every Pokémon an adventure could trade by
  hand, with the hard limits marked.
- `GET /targets?from_id=` and `GET /limits?from_id=&from_key=&to_id=` feed the
  Trade tab. Targets mark a view-only adventure unavailable with its reason.
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
`key` and `state`, which is `auto`, `first` or `keep`.

Trade settings are saved per game in SQLite, separately from cartridge checkpoints.
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
A deliberate new-adventure restart clears all trade settings.

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

When disconnected, the UI disables trade setting controls, shows a reconnecting message,
and preserves saved choices. `VIEWER_ONLY` blocks preference writes on the server.

Automatic trades preserve the last held Articuno, Zapdos, Moltres, Mewtwo, or
Mew in each adventure, even when another adventure needs its Pokédex entry.
Setting a boxed partner to Prefer to trade can override this protection. Party,
shiny, perfect DV, and Never trade protections still apply.
