# README screenshots

Captured September 24, 2026 from a running Red adventure (eight badges, 149 of 151 registered,
135 League wins, 1,391 game hours, 240 partners across the party and twelve boxes). These are
browser screenshots of actual game state, not mockups or generated art. The live simulation
continued running during capture, so the views are a few minutes apart.

Captured at a 1280 pixel viewport and twice that pixel density, then halved, so the Game Boy
screen and the portraits stay sharp. The viewer stops fetching frames for a hidden tab on
purpose, so `document.hidden` was overridden for the live shot and the page then loaded its own
frames as usual. The run was at Max speed, where the frame on screen trails the battle label by a
moment, so a live shot was kept only when the label read the same before and after it was taken.

| File | View |
| --- | --- |
| `live-adventure.jpg` | The Champion battle, six teammates with HP, experience and DV ratings, and the plan across the foot |
| `journal.jpg` | The road so far, then the latest highlights, each with its own screenshot |
| `pokedex.jpg` | Registered, seen, total caught, level 100 and perfect find counts, and the first species rows |
| `pc-storage.jpg` | Party and all boxes, sorted by DV star rating with the best first |

Only the JPEGs are kept. The README embeds these files directly, so an unreferenced PNG of the
same view is weight in the source package for nothing.

Portraits are decoded from your own ROM when it is added (see Odds and ends in the main README).
Retake against a library whose Pokédex shows those sprites, not numbered placeholders.

Keep screenshots free of browser chrome, local file paths, credentials, and private
settings. Use actual interface controls to choose a view without altering game state.
Keep images in the source package so the README also works in downloaded source.
