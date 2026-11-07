# PC storage

The PC has two views. Boxes preserves physical slot order and displays only the
selected party or box. All Pokémon hides the box picker and shows a sortable list
of the entire collection without pagination. Every matching partner is on the page,
including the party. All Pokémon defaults to Power, highest first. Explicit sort
choices in bookmarked links are preserved. Each view remembers its search while
switching. Sorting never writes to game storage.

For Power, DVs, training, and victory counts, see [Pokémon stats and Power](pokemon-stats.md).
A locked partner has a lock icon on its card. Press a Pokémon and press
**Locked: never traded** in its popup to lock or unlock it. Shiny and perfect
Pokémon show Protected instead. The popup's **Trade…** link opens the Trading page
with that Pokémon chosen. See [Locks](trading.md#locks).

## Release order

When the PC fills, the run releases spares to make room. Each stored Pokémon has
a PC value, and the cheapest go first. Its popup shows the value, the parts that
make it up and where it stands: a spare, a copy linked adventures need, or never released. The
next five to go carry a mark on their cards.

| Part | Adds |
| --- | --- |
| A plan role: breeding, training, team or an offered trade | 400 |
| Shiny | 300 |
| Perfect DVs | 250 |
| Legendary or one-time event Pokémon | 200 |
| Rare DVs for its species | 120 |
| Level and stat experience | up to 100 each |
| Ordinary gift or fossil | 80 |
| DVs | up to 60 |
| Traded in from an unlinked trainer | 60 |
| Linked adventures missing the species | up to 100 |

Keep-locked Pokémon, the best or only copy of a species, the party, eggs and the
copies a running plan uses (the training project's trainee and family, breeding
parents and stock and team members, two copies per species at most) are never
released automatically. A species that linked adventures are missing keeps one copy
for each of them, and a trade's give or an offered copy keeps its plan role. Those
copies go only after every spare. **Release at next PC visit** in the popup puts a
Pokémon at the front of the queue. An only copy asks you to type its name first.
**Cancel release** drops the request. The **Release order** select doubles the
shiny part with Favor shiny, or the DV parts with Favor DVs.

A visit takes the cheapest Pokémon box by box. Values within 50 of each other
count as equal, so a visit stays in one box instead of saving the game at every
box change. When the boxes are full and every stored Pokémon is protected, the PC page and the journal
say the PC is full.
