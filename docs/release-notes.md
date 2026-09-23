# PokeSim 0.3.3 experimental beta

One change, and it is the largest single source of disk growth in the application.

## Journal save states are compressed

Every notable journal entry stores a full PyBoy save state so that entry can be rewound to. That
state is 167 KB of mostly zeroed RAM and it was written raw. They are only ever added to, never
rewritten, so they accumulate for the life of an adventure.

On the server this was found on, two adventures were carrying **2,836 of them, 456 MB** — against
68 MB of the screenshots beside them and 108 MB of autosaves, which are bounded at twenty. That
is essentially all of the roughly 40 MB an hour an adventure was writing.

A PyBoy state gzips about ten to one. Measured on a real state from that server: 167,677 bytes to
15,826, and PyBoy loads the compressed state back to the correct game state. Compacting the
existing states on that server took its library from 1.6 GB to 961 MB.

Reading detects the gzip magic, so **states written before this release still load**. An existing
library keeps resuming and every journal entry written so far keeps its rewind.

## Upgrading

Nothing to migrate, and no action required — new entries are written compressed from the first
one.

Existing entries are left as they are and keep working. If you want the space back now, gzip the
`event-*.state` files under each adventure's `states/` directory in place, keeping the same
filenames; the reader accepts either format. Do that only on a version that includes this
release, because an older build reads those files raw and its rewind will fail on a compressed
one.

Autosaves and the policy manifest beside them are deliberately left uncompressed. They are
bounded at twenty, and the manifest's checksum is recorded over the raw bytes in several places
including the trade path, so compressing those is a wider change than this one.
