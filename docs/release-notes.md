# PokeSim 0.3.5 experimental beta

The collection pages are illustrated out of the box, and the journal stops keeping save states.

## Portraits come out of your own cartridge

The Pokédex and the PC have always shown a neutral numbered placeholder unless you went and found
artwork yourself and dropped 151 files into `assets/sprites`. Almost nobody did, so the two pages
that are most of the appeal looked half-finished.

The pictures were in the ROM the whole time. Adding a ROM now decodes all 151 front sprites from
it into `assets/sprites`, and every adventure shares them. Nothing is shipped with the
application and nothing is downloaded for this — it is your cartridge, read on your machine, and
the images never leave it. A file already in that folder is never replaced, so if you have
installed your own pack it still wins, and an adventure's own `sprites` folder still overrides
individual entries.

The decoder is a port of pret/pokered's `home/uncompress.asm`. A Generation I picture is two 1bpp
chunks, each written two bits at a time down byte-columns across four passes, then differentially
decoded row by row and merged. **All 151 match that project's reference art pixel for pixel**,
which the test suite checks wherever a ROM and a reference checkout are both present.

Mew needed its own path: its header sits outside the base-stats table, at `0x0425B`, because it
was added late — in Shigeki Morimoto's words, slotted into "a miniscule 300 bytes of free space"
left over when the debug features came out.

The lightest of the four shades is written transparent rather than white, so one portrait sits
correctly on a light page and a dark one.

## A journal entry no longer keeps a save state

0.3.4 narrowed this to eight event types. It should have been none.

The rewind those states power is refused outright on any adventure that has completed a Cable
Club trade: the button is gated on there being no trade barrier, and every checkpoint older than
the barrier is rejected on load anyway. On the server this was found on, both adventures had a
barrier — so 456 MB of save states existed for a button that could not appear on either of them.

Going back to a moment is already covered, and by bounded things: twenty rotating autosaves a
minute apart, a League entry checkpoint, a before-stall checkpoint, and the save-state list the
interface already offers. A journal entry now costs its screenshot, about 3.6 KB against 167 KB.

Entries written earlier keep the states they have, so any rewind that works today keeps working.

## Upgrading

Nothing to migrate. Portraits appear the next time a ROM is added; to get them for a ROM already
installed, remove and re-add it, or drop the files in yourself.

Existing journal entries are untouched. If you want the space back from the states already on
disk, delete `event-*.state` under each adventure's `states/` directory — the journal keeps its
entries and its screenshots, and only the rewind on those particular entries goes away.
