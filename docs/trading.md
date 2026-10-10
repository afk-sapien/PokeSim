# Trading

Use this guide for the Trading page, trade settings, offers, and broker connection
settings. See [automatic trading](automatic-trading.md) for coordinator setup,
exchange rules, and recovery.

## Trading page

Everything about trading lives on each adventure's Trading page at
`/games/{id}/trading`. It has five tabs:

1. **Trade** picks a trade by hand: one of this adventure's Pokémon, another
   adventure, and the Pokémon you want back.
2. **Offers** lists offers for this adventure and offers it sent.
3. **Auto** holds the automatic trading switch, the wish list and each Pokémon's
   trade setting.
4. **History** shows hand-picked and automatic trades together, newest first.
5. **Cable Club** lists the adventures this one can hold a
   [Cable Club session](#cable-club-sessions) with, and opens the session page.
   A pair that cannot link is greyed out with the reason.

The page remembers the last tab in the browser. A link can open a tab with
`?tab=trade`, `?tab=offers`, `?tab=auto` or `?tab=history`, and `&mon=` with a
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

- **Auto decides**, the default. Automatic trading may use it when it is a spare.
- **Trade first**. Automatic trading prefers it over other spares.
- **Keep**. Automatic trading never uses it, and automatic PC release never
  releases it.

Settings set to Keep also protect a Pokémon in the party from the in-game trader.
Shiny and perfect Pokémon cannot be set to Trade first, and the PC shows them as
Protected. Upgrading converts older choices once: a lock becomes Keep, a withdrawn
offer becomes Keep, and an offer becomes Trade first. The stored values are
unchanged, so an older release still reads them.

Settings persist across box moves, renaming, evolution, ordinary restores, and
server restarts. Starting a new adventure clears them. The emulator saves a change
between input actions and discards pending inputs before resuming. Release
confirmations and trade checkpoint staging recheck the setting, so a Pokémon set
to Keep after it was selected is not released or traded.

## Automatic trading

The Auto tab has a switch that turns automatic trading on or off for this adventure.
Switching it off stops only automatic trades. Other adventures still collect for
it, and trades you pick by hand still reach it. The overview shows Off for an
adventure with automatic trading switched off.

The wish list names species this adventure wants. A wished species it holds none of
makes an exchange worth doing even when the Pokédex does not need it, and such an
exchange is ranked ahead of every other. Pokémon set to Trade first come next.

Automatic trading also follows fixed rules that no setting changes:

1. A shiny Pokémon never travels automatically.
2. The last copy of a species stays home, unless the trade evolves it or registers
   a new Pokédex entry for the other adventure.
3. Active party members and Pokémon in a project stay home.
4. A Pokémon in a hand-picked trade or an open offer is left for that trade.

Trades you pick by hand ignore trade settings and these rules. Only the limits in
[Make a trade](#make-a-trade) apply to them.

## Make a trade

The Trade tab runs one exchange you choose:

1. Pick one of this adventure's Pokémon, from the party or the PC.
2. Pick another adventure. One that cannot take the Pokémon is greyed out with
   the reason: stopped, archived or busy finishing another trade, a Red, Blue or
   Yellow game for a Pokémon that cannot go through the Time Capsule, or a game
   with nothing that can be traded for it.
3. Pick the Pokémon you want back. Pokémon the cable cannot take are greyed out
   with the reason.
4. Press **Trade now**. When the other adventure is view only, the button reads
   **Send offer** and the offer waits for an answer instead.

The Offers tab then opens with the trade listed. Trade settings, party
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
trades wait in line, oldest first, while the Cable Club is busy. You can cancel
while the trade is waiting or preparing. Once both saves are being committed the
trade always finishes.

The Trade tab uses `POST /api/v1/interactions/trade-offers` with `from_id`,
`from_key`, `to_id`, `to_key` and an optional `request_id`. The older
`/api/v1/interactions/manual-trades` admin API is gone.

## Cable Club sessions

A Cable Club session lets you hold both controllers and trade by hand, the way
two people trade with a link cable. Open `/games/<id>/cable?with=<other id>` and
press Start session. Sessions work between two Gold, Silver or Crystal
adventures for now. Red, Blue and Yellow pairs and Time Capsule pairs show that
they are not yet supported. The Cable Club tab on the Trading page links to the
session page for each adventure that can link with this one.

Both adventures walk to the Cable Club and save there, as for any trade. The page
then shows both screens side by side, or stacked on a phone, with a d-pad, A, B,
Start and Select under each. The keyboard drives the game you last clicked or
focused: arrows move, X or Z is A, C or Backspace is B, Enter is Start and Shift
is Select. The status line reads preparing, travelling, ready, in session,
checking, done or rolled back, with the reason.

Trade as many Pokémon as you like, then press Finish. Both trainers leave the
Trade Center and save through the cartridge. PokeSim then checks that the two
adventures still hold the same Pokémon between them, that each side received
exactly what the other sent (or its trade evolution), that nothing was copied or
lost, and that nothing but the parties changed. Only then are both saves kept.
Otherwise both adventures go back to their Pokémon Center saves, and so do they
after Cancel, after five minutes without a button press, after finishing without
a trade, or if PokeSim stops during the session. One session runs at a time, and
both adventures count as busy until it ends. A view link shows the screens and
the status without controls.

`GET /api/v1/interactions/cable-sessions/partners?adventure_id=` lists every
other adventure with the reason it cannot link, or an empty reason. The API is
`POST /api/v1/interactions/cable-sessions` with `left_id`, `right_id`
and an optional `request_id`, `GET /api/v1/interactions/cable-sessions/{id}`, and
`POST /api/v1/interactions/cable-sessions/{id}/input` with `side` (`left` or
`right`) and `button`, `.../finish` and `.../cancel`.

## Offers

An offer from the Trade tab to an adventure you control starts at once, because
there is nobody else to ask. An offer to a view-only adventure waits until that
adventure answers it.

The Offers tab lists **Offers for this adventure** with Accept and Decline, and
**Offers this adventure sent** with Withdraw. Each card shows both Pokémon with their
portrait, level, Battle Power and Stat Power, the offer's status and its reason.
Accepting checks both Pokémon again and then puts the trade in the same queue as
Make a trade, so the card shows the same steps from waiting for the Cable Club to
the saved trade.

Only the limits from [Make a trade](#make-a-trade) apply. Trade settings, party
protection and the last-copy rule do not. An offer is
`pending` until it is answered. It becomes `declined` or `withdrawn` when answered,
`accepted` while its trade runs, and then `completed` or `failed`. It is `expired`
after 7 days without an answer, when either adventure is archived or deleted, or
when a Pokémon in it has left its adventure by the time it is accepted. A Pokémon
that is still there but can no longer be traded, such as one that became the only
party member able to battle, makes the offer `failed` with that reason. If the
other adventure is only stopped, Accept says so and the offer keeps waiting.
An adventure can have 25 offers waiting at once.

Offers are saved in the Library database, so they survive restarts. View links and
`VIEWER_ONLY` instances show no offer controls, and the server refuses every offer
write from them. An adventure whose settings make it view only cannot send, accept,
decline or withdraw offers either.

## Trading API

Offers are under `/api/v1/interactions/trade-offers`:

- `GET ?adventure_id=` lists an adventure's incoming and outgoing offers.
- `GET /pokemon?adventure_id=` lists every Pokémon an adventure could trade by
  hand, with the hard limits marked.
- `GET /targets?from_id=` and `GET /limits?from_id=&from_key=&to_id=` feed the
  Trade tab. Limits include the other side's Pokémon and `starts_now`.
- `POST` creates an offer from `from_id`, `from_key`, `to_id`, `to_key` and an
  optional `request_id`.
- `GET /{id}` reads one offer, and `POST /{id}/accept`, `/{id}/decline` and
  `/{id}/withdraw` answer it.

`GET /api/v1/interactions/auto-settings?adventure_id=` reads the switch and wish
list, and `PUT` with `enabled` and `wishlist` (a list of Pokédex numbers, up to 50)
saves them. A game's own `POST /api/trading/preferences` sets one Pokémon with
`key` and `state`, which is `auto`, `first` or `keep`.

Trade settings are saved per game in SQLite, separately from cartridge checkpoints.
Trainer ID and DVs identify a partner across box moves, renaming, evolution, and
training. Generation I has no unique individual identifier. When multiple held
partners have the same signature, their settings are suspended and their
controls are disabled. Older snapshots without identity data retain
read-only automatic offers.

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
Setting a boxed partner to Trade first can override this protection. Party,
shiny, perfect DV, and Keep protections still apply.
