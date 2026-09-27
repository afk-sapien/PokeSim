# PC storage

The PC has two views. Boxes preserves physical slot order and displays only the
selected party or box. All Pokémon hides the box picker and shows a sortable list
of the entire collection without pagination. Every matching partner is on the page,
including the party. All Pokémon defaults to Power, highest first. Explicit sort
choices in bookmarked links are preserved. Each view remembers its search while
switching. Sorting never writes to game storage.

For Power, DVs, training, and victory counts, see [Pokémon stats and Power](pokemon-stats.md).
For offering or withdrawing partners, see [Trading](trading.md#offers).

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
