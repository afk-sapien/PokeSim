# PokeSim 0.3.1 experimental beta

A repair release. Everything here came out of a review of the 0.3.0 source, and two of the
findings were things every new adventure did to itself in its first three minutes.

## A new adventure stops inventing its own history

Start a game and the journal filled up before the game did: two "Blacked out!" entries, with the
notifications to match, and four starters the player never received. Both came from reading
cartridge memory before the cartridge had made it mean anything.

`AddPartyMon` raises the party count and writes the species list *before* the nickname screen, and
only copies the 44-byte struct once naming is over. PokeSim read the species out of that struct, so
for as long as the naming screen was up — 27 seconds, measured — the new partner read as species 0
with no HP. That is indistinguishable from a fainted team, so the run recorded a blackout on its
way out of Oak's lab, and the live page showed the slot as `No Mon`, level 0, fainted, which is the
ROM's own label for species 0. A counted slot with no struct yet is now held apart from the team it
is joining, and the live page draws it as a slot that is filling.

Separately, the region the Pokédex flags will later occupy holds other values for a couple of
seconds in Oak's lab, before the Pokédex exists. Read as flags, those values said the player owned
Bulbasaur, Ivysaur, Charmander and Squirtle at once — Ivysaur is not obtainable there at all — and
four `Got ...!` entries went into the journal. Registering a species always marks it seen on the
cartridge, so owned flags are now masked by seen ones, and a half-initialised read registers
nothing.

Adventures that already recorded these entries keep them. Nothing rewrites a journal that has
already been written; the fix stops the next one being wrong.

## The trade checks no longer depend on a flag

After both sides of an exchange are written, and before either is adopted, PokeSim verifies that
the party, badges, bag, box counts and every untraded slot came through untouched, and that the
arriving Pokémon is the agreed one down to its struct and original trainer. It also compares a
checksum just before a staged checkpoint is adopted.

All of that was written as bare `assert` statements, which `python -O` removes outright. Nothing in
this project sets `PYTHONOPTIMIZE`, so it never fired — but the one irreversible operation in the
application should not rest on an interpreter flag. The checks raise now, and name which side
failed and how.

## The README shows what the application actually renders

Every collection view in the old screenshots had an empty square where each portrait goes, so the
first thing a reader saw was a Pokédex of blank cards. That is not what the application does: a
missing portrait has drawn a neutral placeholder with the Pokédex number in it since 0.2.0, and
those shots simply predated a library with a pack installed.

Retaken from a run with eight badges, all 151 registered and 240 partners. The live shot is a wild
battle at 1x rather than whatever frame Max speed happened to land on, the PC is sorted by DV
rating the way the paragraph beside it claims, and the Journal has a picture of its own.

## Also in this release

- The game proxy forwarded a worker's raw body while dropping `content-encoding` from the headers
  it passes on, so a compressed response would have reached the browser as undeclared gzip. It
  decodes at the proxy now. Nothing compresses one today, which is the only reason this was
  invisible.
- The small print on the Pokédex cards was set between 2.5 and 3.7 to 1 against the card at nine
  pixels. The line telling you whether you have caught something was the hardest thing on the page
  to read; every colour now clears 4.5 to 1.
- `pokesim --help` names its commands. The help listed the flags for serving the library and
  nothing else, so `adventures`, `import`, `import-pair`, `backup` and `restore` could only be
  found by reading the source, and the usage line called the program `__main__.py`.
- Four tools that did nothing of their own are gone: three byte-identical shims around
  `pokesim.prepare_data` and a copy of `prepare_test_data.py` that differed by one word of
  docstring. A personal checkout path no longer appears in an error message, and `sample_live.py`
  asks for a host rather than defaulting to one machine's name.

## Upgrading

Nothing to migrate. No database change, no policy state change, and existing checkpoints resume
untouched. Replace the image or the package where it is deployed, as usual — publishing a release
does not upgrade a running application.
