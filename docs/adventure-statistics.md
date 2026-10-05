# Adventure statistics

Journal Entries contains the event log. Stats opens with an overview, milestone
times, recent progress, and two collection highlights. Collection details,
activity totals, existing trend charts, return visits, and Marathon records sit
in visible sections with clear headings. Entries does not load these charts.

## Overview and shared totals

The overview shows simulated playtime, League wins, Pokémon held, catches tracked,
perfect finds, and shiny acquisitions. Playtime and League wins use the same
sources as Live. The playtime plus sign means the app inherited a cartridge clock
that had already reached its limit. Pokémon held includes the party and every PC
box. Activity details show areas explored, current money, battles entered, and
steps from the same completed-step tracker used for return visits.

## Milestone times

Seven records cover the first badge, all eight badges, first Champion victory,
151 registered, first level 100, first shiny acquired, and first perfect acquired.
New achievements are confirmed across consecutive valid observations. Their
records preserve the app's simulated playtime and date. A lower-bound play clock
retains its plus sign. A shiny sighting alone does not award an acquisition.

The records are stored separately from journal entries and emulator checkpoints.
Journal pruning, restart, and save rewind do not erase an achievement or award
it twice. Explicitly restarting from power-on starts a new milestone timeline.

On upgrade, existing progress supplies the earliest recorded date. If its
matching retained journal entry has an uncapped cartridge clock, that time is
preserved and labeled Recorded cartridge time. Other achievements say First
recorded and Time unknown. An achievement already present in the initial collection also has
unknown timing. Existing records are never assigned the current playtime as an
invented acquisition time.

## Recent progress and highlights

The 24-hour and 7-day choices use real-world time windows. They show tracked
catches, League wins, and net changes in registered and level-100 species. Queries
use the original database records rather than the bounded chart response. A
period starting before tracking began is labeled partial, with the available
starting dates. Negative collection changes remain visible after a new run.

Catches include verified custom gifts, as in the overview. Gift imports use their
original journal dates, not import dates. Gifts with missing dates are excluded
from period totals and explicitly mark the history as incomplete.

Two highlights identify the strongest currently held Pokémon by Battle Power
and the highest DV score. Links open the corresponding species in the PC, sorted
by the relevant rating. Ties follow current party and PC order. Unknown ratings
are excluded and an incomplete comparison is labeled.

## Collection activity

The overview and collection details show catches tracked, individual perfect
finds, wild shinies seen, shiny catches plus custom gifts, and shiny and perfect
Pokémon currently held.
These are individual totals, separate from the Pokédex's species coverage out of
151. Partial catch history is labeled as tracked since collection began, and
perfect finds retain the plus sign for a verified minimum. Unavailable tracking
is shown explicitly. The API exposes these records under `collection_records`.

## Collection strength

All current party members and all PC boxes contribute once to total collection
power. Strongest-six power sums the six highest individual power scores,
regardless of their current box or party slot. Average power distinguishes
individual improvement from simply collecting more Pokémon.

Historical power charts explicitly show Stat Power, the stat-based score also
available in PC and described in [Pokémon stats](pokemon-stats.md). Their history
is not reinterpreted as moves-aware Battle Power.
It uses permanent species, level, DVs, and stat experience rather than temporary
battle boosts or current HP. Missing individual data stays unknown.

Average DV score is the mean of the held Pokémon's DV percentages, including the
derived HP DV. Three-star or better counts held Pokémon with at least 60 of 75
DV points. These describe the current collection, so catches, releases, trades,
and training can move the numbers in either direction. Average level and the
number held provide context for those changes.

## Activity

- Pokémon caught comes from verified capture receipts, including duplicate
  species, committed League reward gifts, and the custom Mew gift. Trades do not
  count as catches. Existing receipts and saved custom reward journal entries
  seed the total once. Other missing history is not estimated.
- Marathons completed counts finished races in the durable journal, including
  existing races. Abandoned races are excluded.
- The legacy sampled-steps chart counts adjacent movement observed on the same map. Map changes,
  large jumps, observation gaps, menus, and battles do not add distance. Walking,
  cycling, and surfing all count. Movement between observations can be missed.
- Battles entered counts observed transitions into wild or trainer battles.
- Observed damage dealt records reductions in the same opponent's HP.
  Observed damage taken records reductions in the same party members' HP during
  battle. Healing and identity changes do not count. These are sampled HP-loss
  totals, including recoil and status effects, not exact attribution to attacks.
  Fast changes or damage on an unobserved battle exit can be missed.
- The legacy sampled-game-hours chart counts valid observed emulator frames at 60 frames per
  second. Pauses, offline time, and gaps are excluded. It does not inherit the
  cartridge clock's hour limit.

New activity totals start when tracking starts. They are accumulated outside
emulator checkpoints. Restoring a checkpoint resets the observation baseline,
without resetting totals or counting the jump itself. Further play after a
rewind counts as additional activity. Capture receipts retain their own replay
protection. Starting a fresh run in the same adventure keeps journal activity
and starts new collection measurements.

## Persistence and long histories

Counters flush every 30 wall-clock seconds and with normal saves. An abrupt
process or machine failure can lose the unflushed activity since the last
write. A normal shutdown flushes it. SQLite transactions keep a history point
and its saved counters together. Counters are not limited to 32-bit values.

Collection measurements require two matching observations and refresh roughly
every 30 seconds. History keeps hourly endpoints for 30 days, then daily
endpoints indefinitely. The initial baseline is retained for comparisons.
These are trend samples, not every temporary peak. Collection charts use labeled
scales around the measured range so small improvements are visible. DV changes
are shown in percentage points. Missing measurements leave gaps in the lines. The API returns at most
600 points per chart history so a very old adventure does not overload the
browser. Existing journal milestone history is also bounded when served.

New measurements are not projected backward onto earlier journal entries.

## Legendary returns

A compact panel shows completed-step progress toward the next legendary return
and the encounters ready to revisit. This uses the cartridge step counter rather
than the older sampled steps chart. See [Legendary returns](legendary-returns.md)
for the milestone rules and settings.

## Marathon records

The Kanto Marathon panel shows the personal best, current attempt and checkpoint
progress, and last result. Times use simulated game time, including battles and
healing. Pauses and offline time add nothing. Only a completed race can set a
record. Existing saved records appear automatically.

These records follow the adventure's policy checkpoint, so restoring an older
checkpoint also restores its race records. The lifetime finishes chart above
uses durable journal entries. See [Kanto Marathon](marathon.md) for the course
and timing rules.
