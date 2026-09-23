# README screenshots

Captured September 23, 2026 from a running Red adventure (eight badges, all 151 registered,
283 League wins, 1,603 game hours, 240 partners across the party and twelve boxes). These are
browser screenshots of actual game state, not mockups or generated art. The live simulation
continued running during capture, so the Journal entries are a few minutes ahead of the rest.

Captured at a 1280 pixel viewport and twice that pixel density, then halved, so the Game Boy
screen and the portraits stay sharp. The viewer stops fetching frames for a hidden tab on
purpose, so `document.hidden` was overridden for the live shot and the page then loaded its own
frames as usual. The live shot was taken during a wild battle, with the pace at 1x rather than
Max, because at Max speed the screen is wherever the run happened to be that frame.

| File | View |
| --- | --- |
| `live-adventure.jpg` | A wild Onix battle, six teammates with moves, PP and DV ratings, and the plan across the foot |
| `journal.jpg` | Highlights: an evolution, the League victory, and the Elite Four, each with its own screenshot |
| `pokedex.jpg` | Registered, seen, catches tracked, level 100 and perfect find counts, and the first species rows |
| `pc-storage.jpg` | Party and all boxes, sorted by DV star rating with the best first |

Only the JPEGs are kept. The README embeds these files directly, so an unreferenced PNG of the
same view is weight in the source package for nothing.

Portraits come from an optional local pack and are not included in PokeSim downloads. Without
one, every card shows a neutral placeholder with the Pokédex number in it, so retake these
against a library that has a pack installed or the collection pages will undersell themselves.

Keep screenshots free of browser chrome, local file paths, credentials, and private
settings. Use actual interface controls to choose a view without altering game state.
Keep images in the source package so the README also works in downloaded source.
