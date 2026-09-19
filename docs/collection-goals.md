# Long-term collection goals

These goals are included in the development source. They are not part of the
published rc31 download yet. Each adventure keeps its own records.

## A level 100 Pokédex

The Pokédex shows a gold star and a progress counter out of 151. A species earns
its star when a level 100 partner is observed in the party or any PC box.
A final evolution also awards stars to all its ancestors. For example,
Venusaur awards Bulbasaur, Ivysaur, and Venusaur. Vaporeon awards Eevee and
Vaporeon. Jolteon and Flareon each need their own completion.

Training projects prefer partners whose evolution line still has stars to earn.
Existing level 100 partners are recognized automatically after the upgrade.
The historical counter does not claim that every individual is currently level 100.

## Perfect DV finds

A perfect Pokémon has 15 in every DV: HP, Attack, Defense, Speed, and Special.
HP is derived from the other four DVs. This measures natural potential, not
stat experience or current battle stats.

Perfect individuals receive a soft animated halo and a labeled badge in the PC.
The effect respects reduced-motion preferences. Their actual species also receives
a Pokédex badge. Evolving a perfect Bulbasaur records Ivysaur when it is observed,
then Venusaur when it is observed. It does not invent sightings of other forms.

The automatic player keeps perfect individuals alongside its best practical
partner of each species. Automatic release, NPC exchanges, and peer trade offers
exclude them. Repeat expeditions continue looking for rare partners after the
ordinary Pokédex is complete, while training and supply trips still have priority.

The total displayed with a plus sign is a **confirmed minimum**, accompanied by
the number of perfect species discovered and perfect partners currently held.
Existing partners establish a baseline. New perfect catches on verified Red and
Blue cartridges add durable capture receipts, so replaying the same saved capture
does not add another find.

Generation I does not have a unique individual identifier. For existing inventory,
records use the largest simultaneously observed count for each original trainer
and evolution family. Nicknames, evolution, or moving boxes cannot create extra
finds. Identical gifts or trades after a partner leaves may be indistinguishable,
and previously released partners cannot be reconstructed. Unknown DV data never
receives perfect credit.

## Persistence

Records live in the adventure's SQLite database, separately from save checkpoints.
They survive application restarts, evolution, ordinary save rewinds, and journal
pruning. Starting a fresh adventure resets its goals. Back up the entire adventure
data directory to preserve both the game and these records.
