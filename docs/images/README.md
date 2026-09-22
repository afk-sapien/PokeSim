# README screenshots

Captured September 21, 2026 from the running Red adventure (eight badges, 138 of 151
registered, 26 League wins, 735 game hours). These are browser screenshots of actual
game state, not mockups or generated art. The live simulation continued running during
capture, so `journal.png` predates the others.

The capture browser reported the tab as hidden, and the viewer stops fetching frames
for a hidden tab on purpose, so `document.hidden` was overridden for the live shot and
the page then loaded its own frames as usual. Page zoom was reduced to fit each view
into one capture.

| File | View |
| --- | --- |
| `live-adventure.png` | Live game, six teammates with moves and DV ratings, and the plan across the foot |
| `pokedex.png` | Registered, seen, caught, level 100 and perfect find counts, and the first species rows |
| `pc-storage.png` | Party and all boxes, sorted by power with the strongest first |
| `journal.png` | Recent highlights, game screenshots, and milestones |

The running build includes development work ahead of the release it displays, so its
displayed version alone does not identify all of those changes. Portraits come from an
optional local pack and are not included in PokeSim downloads.

Keep screenshots free of browser chrome, local file paths, credentials, and private
settings. Use actual interface controls to choose a view without altering game state.
Keep images in the source package so the README also works in downloaded source.
