# Adventure statistics

Journal has two subpages. Entries contains the event log. Stats contains the
existing Pokédex, level 100, perfect-find and League history alongside collection
strength, potential, and activity trends.

## Collection strength

All current party members and all PC boxes contribute once to total collection
power. Strongest-six power sums the six highest individual power scores,
regardless of their current box or party slot. Average power distinguishes
individual improvement from simply collecting more Pokémon.

Power uses the same formula as PC, described in [Pokémon stats](pokemon-stats.md).
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
- Recorded steps count adjacent movement observed on the same map. Map changes,
  large jumps, observation gaps, menus, and battles do not add distance. Walking,
  cycling, and surfing all count. Movement between observations can be missed.
- Battles entered counts observed transitions into wild or trainer battles.
- Observed damage dealt records reductions in the same opponent's HP.
  Observed damage taken records reductions in the same party members' HP during
  battle. Healing and identity changes do not count. These are sampled HP-loss
  totals, including recoil and status effects, not exact attribution to attacks.
  Fast changes or damage on an unobserved battle exit can be missed.
- Recorded game hours counts valid observed emulator frames at 60 frames per
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
