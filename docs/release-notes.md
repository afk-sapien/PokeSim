# PokeSim 0.3.6 experimental beta

Every page is redrawn as one instrument panel, and the boxes on it finally line up.

## One design across the whole site

The live page, Pokédex, PC, trading, journal, library, settings and the desktop launcher used to
carry six stylesheets that had grown apart. They now share one set of tokens and one component
sheet: square edges, hard bevels, meters drawn as discrete cells, and a 5x7 pixel face for names
and readouts. There is a light and a dark theme, and the switch sits in the footer; it follows
your system until you pick one.

Portraits scale by whole pixels only, so a Game Boy sprite is never smeared. A 96-pixel pack whose
art sits in the middle 56 pixels is recognised and scaled as 56-pixel art, so hand-installed packs
and the portraits read from your cartridge come out the same size.

## Things line up

- **Live page.** The game screen and the six party bays end on the same line. The screen keeps
  the Game Boy's 10:9 shape at every width and never letterboxes; spare height becomes bezel.
  The plan is its own row across the full page. Under 1280px the screen and the party stack, and
  the party runs two abreast while it fits.
- **Party bays** keep one height. Moves show only when a bay is wide enough to hold them on two
  rows; the details dialog always has them. Long names fit on a phone.
- **PC.** The party and box list is wider, with larger names and counts, and at desktop width it
  starts and ends level with a full box of twenty.
- **Library.** A stopped adventure keeps the same screen space as a running one, so titles and
  buttons line up across a row.
- **Settings and notifications.** Panels in a row share a height; the four settings panels sit
  two by two.
- **Journal entries.** The details sheet stands as tall as the screenshot beside it, and the
  logged time shows in your own time zone.

## Upgrading

Nothing to migrate: no database, save or policy change. Browsers pick up the new stylesheets on
their own, because every changed stylesheet and script has a new version in its URL.
