# Marathons

After becoming Champion, the automatic player can occasionally take a break for
a town-to-town marathon. Red, Blue and Yellow run the Kanto Marathon. Gold,
Silver and Crystal run the Johto Marathon. Both courses use the same rules,
timing and records. Neither claims that map tiles equal real kilometers.

## Kanto Marathon

The course starts in Pallet Town, visits Viridian, Pewter, Vermilion, Lavender,
Saffron, and Celadon, then returns through Saffron, Vermilion, Pewter, and
Viridian to finish in Pallet Town, with 11 checkpoints.

It becomes eligible after becoming Champion and finishing four projects, with
access to Cut and open Saffron gates.

## Johto Marathon

The course starts in New Bark Town, visits Cherrygrove, Violet, Azalea,
Goldenrod, and Ecruteak, then returns through Goldenrod, Azalea, Violet, and
Cherrygrove to finish in New Bark Town, with 10 checkpoints. A course out to
Olivine was too long for the 50 minute budget once wild battles were counted.
Each checkpoint is the tile below the town's Pokémon Center door, or below
Elm's Lab door in New Bark Town.

Every leg is on land and can be walked both ways, so no leg needs Surf and no
one-way ledge blocks the way back. Azalea and Goldenrod are joined through Ilex
Forest, which needs Cut, and Goldenrod and Ecruteak through Route 36, which
needs Sudowoodo out of the way. The player never flies or surfs during the race.
The way to New Bark Town is not timed, so the player may fly or surf there,
which a player in Kanto needs.

It becomes eligible after becoming Champion and finishing four postgame
activities (better-copy hunts, training, shiny searches or League runs), with
Cut in the party and Sudowoodo cleared from Route 36.

## The race

The player must reach every checkpoint in order. Travel to the starting line
is preparation. The race clock begins on arrival there. Ordinary navigation,
Cut, battles, and necessary healing or shopping still use normal game controls.

The current objective shows the next checkpoint, elapsed game time, and recorded
steps. Starting and finishing create short journal entries with screenshots.
The finish report includes checkpoints, time, steps, battles, and healing stops.
The planner also saves the number of finishes, fastest time, and latest result.
Journal → Stats shows the course name, personal best, current attempt time and
checkpoint progress, and last attempt, and the history counts finished races.
A first finish sets the personal best. A faster finish gets a short record
announcement in the journal. Ties and unfinished attempts never replace the
best time.

## Timing and measurements

Time counts simulated frames while the player runs, including battles and supply
stops. Pausing or shutting down the application adds no race time. Checkpoints,
counters, and personal bests survive normal save and restart cycles.

Recorded steps are a conservative count of adjacent, same-map tile movements
observed by the player. Map transitions, warps, and gaps are excluded rather than
inventing distance. Battles count observed entries into battle, regardless of
whether the player wins or flees. Healing stops count visits to a Pokémon Center
where the same party is observed recovering HP, PP, or status, once per visit.

## When the player races

A marathon has a low selection weight. Missing Pokédex entries and urgent supply
projects take precedence. Each attempt is followed by at least six simulated
hours before another can be selected.

The entire attempt, including travel to the start, has a 50-minute simulated-time
budget. A stalled attempt can end earlier through the normal navigation recovery
or two-minute idle limit. Time in battle never counts toward that limit. In
Gold, Silver and Crystal, time in a menu the planner is working through, such
as a team change at a Pokémon Center, does not count either.
Unfinished attempts receive a separate journal report, never a finish or a
personal best. Optional item pickups and social detours are skipped during the
Kanto race.

Records belong to the adventure's policy checkpoint. Loading an older checkpoint
rewinds them along with its other planner state. A new adventure starts fresh.

## Judging a change on a save that races

`tools/replay_audit.py` counts frames by goal. A marathon never produces a find,
so the audit counts every race frame as wasted. On a save that races, judge the
two point bar on the frames wasted outside the marathon as a share of all
frames. Taking the race out of the frame total as well would count the time a
save spends racing against it. Count the trip from the finish back to the
player's previous goal as caused by the race. That trip already sits in the
non-marathon rows, so the bar includes it. Report the marathon rows for each
save next to the bar: attempts, whether each finished, time, and why an
unfinished attempt ended.
