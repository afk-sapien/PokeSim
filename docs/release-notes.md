# PokeSim 0.4.0 experimental beta

See how far each adventure has come, and stop finished trades filling the disk.

## The road so far

The Journal now opens with three small charts: Pokédex registered, badges, and League wins, each
drawn over the days the adventure has run. They share one clock, so you can see when a run raced
through the gyms and when it settled into collecting.

Adventures from before this release are rebuilt from their Journal the first time they start, so
their charts begin on day one. A League win replayed after a rewind counts once.

## Storage

A busy adventure used to add about 100 MB a day. Most of it came from finished trades, which kept
their files and a copy of their game state long after they were done. Now, each time an adventure
starts:

- only the files of its newest twenty finished trades are kept;
- trades that were called off drop their copy of the game state, as completed ones already did;
- once a lot of space inside its database is empty, the database is compacted and gives that
  space back.

On the home server that frees about 350 MB for each of the two busiest adventures.

## Upgrading

Nothing to do. The first start after upgrading adds the chart history and may take a few seconds
longer while a large database is compacted. Back up the library first, as always.
