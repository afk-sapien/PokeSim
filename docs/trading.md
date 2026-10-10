# Trading

Use this guide for the trading screen, offers, and broker connection settings.
See [automatic trading](automatic-trading.md) for coordinator setup, exchange rules,
and recovery, or [PC storage](pc-storage.md#pokémon-locks) to protect a partner from
trading and automatic release.

## Trading views

Every game serves `/trading` with Trading block, Opportunities, and History.
The shared broker remains an internal read API. Its old root page redirects to
the configured game or directs visitors to their game navigation.

## Offers

Automatic offers are eligible spare boxed partners, plus last copies when the
existing coordinator policy allows them. The PC shows Withdraw offer for partners
already listed and Offer for trade for eligible unlisted partners.

A manual offer can nominate another boxed duplicate, including the copy automatic
ranking would normally retain. Explicit choices break ties between equally useful
exchanges. Party members, active projects, protected species, and the coordinator's
last-copy rule still apply. A last copy can only travel for a new registration.

Selected partners are reserved against automatic PC release until withdrawn or
traded. If a selected partner becomes part of the party or a project, its offer
is suspended with a reason. Withdrawals override automatic offers and remain in
effect until the user offers that partner again. Offers only steer automatic
trading. To run one particular trade, use [Make a trade](#make-a-trade).

## Make a trade

The Trade page at `/trade`, linked from Cable Club trading as Make a trade, runs
one exchange you choose. Pick an adventure and any Pokémon in its party or PC on
each side, then press Trade. Locks, offers, withdrawals, party protection, the
last-copy rule and automatic ranking do not apply. The trade is yours to make.

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

The API is `GET /api/v1/interactions/manual-trades/options`, `POST` and `GET
/api/v1/interactions/manual-trades`, `GET /api/v1/interactions/manual-trades/{id}`
and `POST /api/v1/interactions/manual-trades/{id}/cancel`. A request sends
`left_id`, `left_key`, `right_id`, `right_key` and an optional `request_id`.

## Trade offers between adventures

A trade offer asks another adventure for one of its Pokémon. Make a trade on the
Library's Trade page stays the admin trade, which runs at once. An offer waits
until the other adventure's Trading page accepts it.

1. In an adventure's PC, open a Pokémon and press **Offer trade**.
2. Pick another adventure. Each one is checked against the Pokémon you chose.
   An adventure that cannot take it is greyed out with the reason and cannot be
   opened: stopped, archived or busy finishing another trade, a Red, Blue or
   Yellow game for a Pokémon that cannot go through the Time Capsule, or a game
   with nothing that can be traded for it.
3. That adventure's PC opens in offer mode, with the same views, filters and
   sorting, sorted by Battle Power. A banner shows the Pokémon you are offering.
   Pokémon the cable cannot take are tagged Cannot trade, and their detail says why.
4. Open the Pokémon you want and press **Send offer**. The sender's Trading page
   opens with the offer listed.

Each Trading page lists **Offers for this adventure** with Accept and Decline, and
**Offers this adventure sent** with Withdraw. Each card shows both Pokémon with their
portrait, level, Battle Power and Stat Power, the offer's status and its reason.
Accepting checks both Pokémon again and then puts the trade in the same queue as
Make a trade, so the card shows the same steps from waiting for the Cable Club to
the saved trade.

Only the limits from [Make a trade](#make-a-trade) apply. Locks, offers for
automatic trading, party protection and the last-copy rule do not. An offer is
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

The API is under `/api/v1/interactions/trade-offers`:

- `GET ?adventure_id=` lists an adventure's incoming and outgoing offers.
- `GET /targets?from_id=` and `GET /limits?from_id=&from_key=&to_id=` feed the PC
  picker.
- `POST` creates an offer from `from_id`, `from_key`, `to_id`, `to_key` and an
  optional `request_id`.
- `GET /{id}` reads one offer, and `POST /{id}/accept`, `/{id}/decline` and
  `/{id}/withdraw` answer it.

Preferences are saved per game in SQLite, separately from cartridge checkpoints.
Trainer ID and DVs identify a partner across box moves, renaming, evolution, and
training. Generation I has no unique individual identifier. When multiple held
partners have the same signature, offers for those partners are suspended and
individual controls are disabled. Older snapshots without identity data retain
read-only automatic offers.

The staged checkpoint calculation reads the same saved preferences as the broker.
Writes are blocked while an exchange holds the game. A completed exchange clears
the sender's preference in the same database transaction as its journal entry.
A deliberate new-adventure restart clears all offer preferences.

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

When disconnected, the UI disables offer controls, shows a reconnecting message,
and preserves saved choices. `VIEWER_ONLY` blocks preference writes on the server.

Automatic trades preserve the last held Articuno, Zapdos, Moltres, Mewtwo, or
Mew in each adventure, even when another adventure needs its Pokédex entry.
An explicit Offer for trade can override this protection for a boxed partner.
Party, perfect DV, and locked partner protections still apply.
