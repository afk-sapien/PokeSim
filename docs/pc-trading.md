# PC views and game-local trading

The PC has two views. Boxes preserves physical slot order and displays only the
selected party or box. All Pokémon hides the box picker and shows a sortable list
of the entire collection. Each view remembers its search and result page while
switching. Sorting never writes to game storage.

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
effect until the user offers that partner again. No action approves or executes
an individual trade. The existing coordinator continues automatically.

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

## Pokémon locks

Lock Pokémon is available in the PC list and partner details, including for party
members. Locked partners display a lock badge and are excluded from all trade
offers and automatic release. The autonomous in-game trader also skips locked
party members. Locks override prior manual offers and persist across box moves,
renaming, evolution, ordinary restores, and server restarts.

Only Unlock Pokémon clears a lock. Offering, withdrawing, or resetting trade
preferences cannot bypass it. Unlocking returns the partner to normal automatic
eligibility without restoring an old manual offer. Starting a new adventure
clears locks along with the rest of that adventure's preferences.

The emulator saves preference changes between input actions using a fresh snapshot
and discards pending inputs before resuming. Release confirmations recheck the
selected partner, so a lock placed after selection cancels the release. Trade
checkpoint staging rechecks the same locks. Locks remain editable when the broker
is disconnected, but view-only mode and active trade holds still block changes.

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
