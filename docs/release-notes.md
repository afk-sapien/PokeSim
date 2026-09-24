# PokeSim 0.3.7 experimental beta

Every page loads fast and holds still while it does.

## Fast

Each request to an adventure used to wait about 40 ms for nothing: the connection between the
manager and an adventure's worker held back small replies, waiting on an acknowledgement. That
is gone, and the manager now reuses its connections instead of opening one per request. On a
local machine a game request takes 2–5 ms instead of 21–45 ms.

Stylesheets, scripts and the font are now fingerprinted, so your browser keeps them for a year
and only fetches one again when it actually changes. Everything larger than a kilobyte is
compressed. A repeat visit to the live page transfers about 30 KB instead of about 1 MB, which
you will notice most on a phone or away from home.

## Steady

Switching pages used to make the whole interface shuffle for a moment: the scrollbar appeared
and pushed everything sideways, the footer jumped, the status pill changed width and shoved the
tabs, and the adventure picker widened once it had loaded. Each of those now has its place from
the first frame. The worst page moved 0.96 by the browser's own layout-shift measure; the worst
now moves 0.02.

## Tidier

- **The Library › adventure trail** sits under the name like the version sits under PokeSim,
  instead of borrowing the tab styling. On a phone it is one row.
- **Digits and punctuation** are spaced properly in the panel face: `010`, `12/151` and `01:32`
  no longer have a gap after every 1 or colon.
- **Pokédex cards** keep a one-line header (Unseen, Seen, In Pokédex or Hunting), so rows line
  up again.
- **Dropdowns** on the PC, Library and Settings pages match the Pokédex ones.
- The status pill says **Running** rather than a second "Live", the Library says "1 adventure",
  and journal entries stop repeating the place they are named after.

## Upgrading

Nothing to migrate: no database, save or policy change. Browsers pick up the new files on their
own. Anything reading `/frame.jpg` or `/stream` directly now receives PNG frames at the same
paths.
