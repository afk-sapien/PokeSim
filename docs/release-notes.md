# PokeSim 0.3.4 experimental beta

Two changes to the same thing: how much an adventure writes to disk just by existing. Together
they take the journal's storage on a long-running adventure down by about 98%.

## A save state is kept only for moments worth returning to

Every journal entry that counted as *notable* stored a full emulator save state so that entry
could be rewound to. That conflated three different questions, because "notable" also decides
what reaches the Atom feed and what sends a phone notification. A Pokémon reaching level 50 is
worth reading about. It is not worth a 167 KB snapshot of the entire machine.

Measured across two live adventures: 2,840 stored states, of which **levelling up was 840 and
walking into a new map was 421** — 46% between them, and 82% once every other incidental type is
counted. Badges were 17.

States are now kept for the things that are rare, hard to undo, or that you would want to get in
front of: badges, Hall of Fame runs, new partners, evolutions, blackouts, stalls and legendary
retries. Everything else still appears in the journal, the feed and your notifications exactly as
before — it simply no longer carries a snapshot.

Entries written before this release keep the states they already have, so no rewind that works
today stops working.

## Those states are compressed (from 0.3.3)

A PyBoy save state is 167 KB of mostly zeroed RAM and was written raw. It gzips about ten to one:
measured on a real state, 167,677 bytes to 15,826, and PyBoy loads the compressed state back to
the correct game state. Reading detects the gzip magic, so older uncompressed states still load.

Compacting the existing states on the server this was found on took its library from 1.6 GB to
961 MB, with the application running.

## Together

That server was writing roughly 40 MB an hour per adventure, nearly all of it these states. With
both changes a comparable adventure writes on the order of **half a megabyte an hour** for its
journal, and the historical 456 MB becomes about 8 MB once only the rewindable moments are kept.

## Upgrading

Nothing to migrate and no action required. New entries follow the new rules immediately; old ones
are untouched.

If you want the existing space back, gzip the `event-*.state` files under each adventure's
`states/` directory in place, keeping the same filenames — the reader accepts either format. Do
that only on 0.3.3 or later, because an older build reads those files raw and its rewind will
fail on a compressed one.

Autosaves and the policy manifest beside them are still uncompressed. They are bounded at twenty,
and the manifest's checksum is recorded over the raw bytes in several places including the trade
path, so compressing those is a wider change than this one.
