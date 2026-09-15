# Roadmap: adventures that last for months

Updated September 14, 2026.

The target is entertaining autonomous Red and Blue adventures that can run for weeks
or months, alone or with several connected instances. Beating the Champion is the first
chapter. Collection, raising different teams, and useful exchanges should give each run
longer projects with visible intermediate achievements.

Release rc8 introduced starter variation
and the first persistent postgame director. The remaining long-term features below are
planned. Guaranteed Pokédex completion, restart farming, and authentic link-cable
emulation remain outside scope. Stat training and optional searches for better DVs are
now future goals. Perfect-DV completion is not a requirement for a successful adventure.
Missing encounters and unchosen gifts must remain visible limitations.

## 1. Break stalled objectives and recovery loops

The September 14 checkpoints expose two different problems. Blue can retain a planner
spacing timestamp from after a save rewind and wait until another rewind repeats the
problem. Red returns from Indigo Plateau into Victory Road's east corridor, where a
loose boulder blocks access to the main cave and the switch puzzles.

The current revision resets planner spacing on restore, clears that return passage,
checks route availability for every proposed expedition, and retires projects after
two simulated minutes without intermediate progress. Movement alone is insufficient.
Stationary strategic runs abandon their objective in the current game instead of
reloading the same save. Invalid states and battle timeouts retain the restore guard.

Verification must use copied checkpoints, record actual gains and failed objectives,
and distinguish policy recovery from save reloads. A healthy HTTP server is not evidence
of a productive adventure. Multi-day endurance remains an open validation item.

## 2. Make progress visible

Live shows the most recent achievement and its age alongside the current objective.
Activity distinguishes exploring, making progress, and recovering. Playtime announcements
retain their history across checkpoint restores, so rewinds cannot announce the same
hour repeatedly. The app clock remains persistent beyond the cartridge limit.

## 3. Introduce exchanges in stages

The proposal engine and save-based executor exist. First connect a read-only trade board
to the two live inventories. Show both Pokémon, their box locations, whether either is a
last copy, and what each game gains. No trade executes from the proposal board.

Next prepare one concrete exchange for explicit user approval. Re-read both inventories,
stop both runs, create cold backups, validate exact participants, stage both outputs,
verify their inventories and manifests, then install and resume both together. Do not
turn approval of one exchange into authorization for scheduled trading.

Consider automation only after approved exchanges and sustained autonomous progress have
been observed. Do not promise complete collections from trading alone.

## 4. Keep releases reproducible

Both deployments now use the repository's game-data loader, health endpoint, separate
sprite packs, and four-page interface. The older claim that every fix needs hand-porting
is obsolete. The remaining release requirement is a versioned commit, matching package
and image revision, test evidence, and a rollback record for each deployment.

Preserve PyBoy 2.7.0 while using existing checkpoints. Keep game data, sprites, ROMs,
and saves outside source releases. See [homeserver.md](homeserver.md) for the live layout.

## Long-term progression

### A persistent director for several kinds of progress

Build on bounded collection expeditions with durable goals for missing species,
evolution, training, trade preparation, and new Hall of Fame teams. Select among useful
goals using expected benefit, available resources, recent failures, and the run's
personality. Repeated movement, repeated familiar encounters, and repeated trades must
not count as new achievements by themselves.

Record each project's target, prerequisites, intermediate gains, completion condition,
and reason for abandoning it. A failed project should wait for a relevant change or a
bounded retry opportunity. Restarting the process must preserve this history.

Distinguish species registered from species currently held. Offer an optional living
collection goal that retains one representative of each obtainable species. Show what
is available locally, obtainable from connected peers, or blocked by a resolved one-time
choice. A network cannot create starter or gift lines that none of its runs possesses.

### Train and rotate a wider collection

After acquisition and evolution, raise selected reserves through useful level milestones
and eventually level 100. Rotate teams and attempt the League with different eligible
rosters. Record each roster's first championship, rather than treating every repeat win
with the same overpowered team as substantial progress.

Red and Blue use stat experience and DVs. Stat experience grows through training. DVs
are fixed, so improving those requires acquiring a different individual. Start with
stat training for favorite teams, then allow an optional collection-wide mastery goal.
Track effective stat gains, including the game's recalculation behavior, rather than
just filling counters that no longer change a stat.

Optional quality hunting should retain useful improvements with explicit encounter and
storage budgets. Protect favorites and unique acquisitions. Do not make a rare perfect
roll the only remaining objective, or reset a completed adventure to reroll its starter.
Mechanics references: [stat experience](https://bulbapedia.bulbagarden.net/wiki/Effort_values)
and [DVs](https://bulbapedia.bulbagarden.net/wiki/Individual_values).

### Make connected runs cooperate

Extend the broker from comparing current inventory to matching requests and offers
across several peers. A run should be able to catch a spare version-exclusive Pokémon
for another run, prepare a trade evolution, or raise a requested partner. Trade goals
must feed back into the adventure planner so a shortage can create an expedition.

After the first verified live exchange, add an owner-configured automatic trading mode
for trusted peers. Within that policy, ordinary eligible exchanges should execute
without approval of every transaction. Keep review mode available. Protect favorites,
active party members, and last copies by default. Permit explicit settings for owners
who prioritize dex registration over retaining every species.

Execute at safe points with fresh participant checks, backups, durable transaction IDs,
and a recovery record for both sides. Handle a peer disconnecting between preparation
and completion without duplicating a Pokémon or applying half a trade on resume.
Journal the exchange in both adventures and prevent repeated exchanges that create no
new benefit. A trade frequency setting should limit interruptions, not force useless
swaps to meet a quota.

### Give new adventures different beginnings

New adventures now make a persisted, seeded random choice among Bulbasaur, Charmander,
and Squirtle, with a fixed choice available in configuration. Existing saves keep their
actual starter. All three opening campaigns have passed through the first badge. Extend
validation to later gyms and longer runs as the planner changes.

For groups creating new runs together, optionally distribute starter choices across
the group before repeating a choice. Variation in gifts, team preferences, and expedition
selection can make runs distinct without manufacturing species or restarting saves.

### Make months of operation practical

Validate progression over 24 to 48 hours, then a week, with several seeds, starters, and
game speeds. Measure gains appropriate to the active project, time without meaningful
progress, repeated objectives, save rewinds, memory, CPU, and storage growth. Two hours
of replay is a regression check and cannot establish months of reliability.

Bound checkpoint, backup, journal, and trade-record storage while retaining enough
history for recovery and summaries. Test graceful shutdown, restart, upgrades, and peer
outages during long projects. Provide configurable pacing and resource limits so an
unlimited-speed instance does not consume its finite goals or server resources blindly.

When useful goals are exhausted, report that honestly and offer low-activity maintenance
or an owner-selected new adventure with the old record archived. Never silently reset
the save or portray aimless movement as continuing progression.

## Remaining implementation priorities

The persistent director, random starter selection, first-badge checks, reserve level
training, and visible ground-item detours are implemented. Continue from that baseline:

1. Prove sustained collection and training progress. Improve travel and maintenance
   interruptions, while preserving productive live runs for endurance observation.
2. Build and validate durable coordination for the first specifically approved live
   trade. Then add trusted-peer automatic exchanges and trade preparation objectives.
3. Extend reserve training with varied Hall of Fame teams and visible stat-training
   milestones. Keep useful partial progress distinct from completed targets.
4. Bound backup, image, journal, and checkpoint growth and validate upgrades and outages
   over multi-day runs. This work should proceed alongside progression improvements.
5. Add optional quality hunting after the ordinary adventure and trading paths are
   reliable. Perfect DVs and guaranteed completion remain outside the required target.

Improve encounter and NPC trade data, separate shop and PC state from the main policy,
and consolidate reset bookkeeping as related changes require it. Existing serial-hook
experiments are research, not a prerequisite for the save-based exchange workflow.

## September 14 delivery record

Release `v0.2.0rc7` was committed and deployed to both games from commit `ca32f70`.
The read-only board is connected. Two-hour copied-save replays show new trainer victories
in Red and a successful return from Blue's Plateau position to Viridian with level gains
and trainer victories. The original Blue checkpoint also caught Moltres in replay.

One proposed exchange has been rehearsed on copies. Its Pokédex registration bug is fixed
in a subsequent commit. The next trade step remains approval of specific participants,
then coordinated execution using that corrected code. Automatic trading is disabled.
Multi-day endurance and further collection improvement remain open.

## First postgame director delivery

Release `0.2.0rc8` adds persisted category rotation, bounded outcome history,
and increasing delays for repeated failures. Training projects use the existing party
and storage controls and pursue the next ten-level milestone, up to level 100. Only
the selected partner's gains extend a training session. A productive partial session
is recorded separately from a completed level target.

New adventures choose a seeded random starter, with a fixed `STARTER` override. The
choice survives reloads. Existing checkpoints retain their partner. All three choices
pass the opening test through receiving the Pokédex without save reloads.
Separate default-pace runs also earned Brock's badge with all three choices. Their
blackouts and frame budgets are recorded in the [starter checks](validation/starters-0.2.0rc8.json).

Two simulated hours on the copied Red checkpoint produced a Moltres catch, increasing
the dex from 111 to 112, and level gains on several partners. Blue retained 113 entries
while gaining levels, completing a League rematch, and reaching Cerulean Cave. Both
replays disabled rewinds. Red used 34 local policy recoveries and Blue used 36, so the
evidence does not establish that all stalls are solved. See the
[Red](validation/red-progress-0.2.0rc8.json) and
[Blue](validation/blue-progress-0.2.0rc8.json) records.

The rc8 changes are now deployed to both adventures from commit `addfb73`.
Coordinated automatic trades, external trade requests
as planner objectives, deliberate stat training, and multi-day endurance remain open.

The deployed rc8 release includes short detours for visible ground items during ordinary travel
and collection expeditions, including Victory Road. The detour preserves the original
project, respects bag capacity, and records confirmed pickups in the journal. A copied
Red checkpoint collected Max Revive and TM47 Explosion, with inventory changes and
journal events verified in the [pickup record](validation/ground-pickups-0.2.0rc8.json).
The earlier two-hour and first-gym evidence above predates this followup. Hidden items
are not part of the new pickup behavior.

The user has authorized ongoing improvements and monitoring. A 30-minute task heartbeat
compares health and actual project progress, investigates recurring failures on copied
saves, and deploys validated fixes with backups. See [the operating plan](operations-monitor.md).


## First monitoring followup

Blue gained two live Pokédex entries after rc8 without save reloads. Red remained in
Victory Road with exhausted attacking PP. A copied current save reproduced no party
experience or dex progress over 72006 frames. Remembered navigation steps were crossing
switch gates that had reset on reentry. The rc9 fix rejects those stale routes and uses
the upper ladder when the lower boulder is inaccessible.

The revised 432028-frame Red replay gained four levels, won two trainer battles, and
collected TM Explosion. Its dex remained at 111 and it used 25 local policy recoveries.
The Blue regression replay gained experience and won a trainer battle, with 13 local
policy recoveries in 144020 frames. Neither replay enables save rewinds. See the
[Red](validation/red-progress-0.2.0rc9.json) and
[Blue](validation/blue-progress-0.2.0rc9.json) evidence.

The following heartbeat confirmed live Red had resumed gaining levels. Both games
remained healthy with zero observed save reloads. Continue improving collection efficiency.

## Training verification followup

The suspected duplicate-species training error was traced to a transient PC withdrawal
snapshot. The game briefly copied Graveler into a party slot while retaining that slot's
previous level 100. Its actual level was 43. Release rc10 accepts training progress during
battle or after returning to the overworld, so PC and party menu transitions cannot
complete a project. Missing party entries also no longer reset the training idle timer.

The reproduced withdrawal previously completed the level-50 project after 1662 frames.
With the fix, the 72002-frame replay kept the project active, gained 8088 experience, and
recorded the real level 44. A 144012-frame replay of Blue's current save also gained levels.
All 383 tests passed. See [the transfer evidence](validation/training-transfer-0.2.0rc10.json).
Historical director totals may contain incorrect completions and remain preserved.

Next, monitor sustained live training and meaningful collection progress. New catches
remain slow, especially on Red. Prioritize a copied-save investigation of repeated
Moltres and Ditto objectives if those projects still fail to reach useful encounters.
Avoid maintenance restarts when there is no verified material fix to deploy. Multi-day
endurance and coordinated trading remain open.


## Navigation candidate held after comparison

The third heartbeat confirmed ongoing live level gains, trainer victories, zero observed
save reloads, and stable process memory. Collection counts remained at 111 for Red and
115 for Blue. A copied Red checkpoint exposed remembered steps through a currently
occupied boulder square. The local rc11 candidate checks observed object positions on
the current map and preserves distant learned routes until fresh readings are available.

The longer comparison did not establish overall benefit. Red made no new catches in
either run, and rc10 produced more journal achievements. The candidate is committed
and tested but is not deployed. The live release remains rc10. See
[the candidate record](validation/navigation-candidate-0.2.0rc11.json).

Collection trips still spend substantial time on supply and storage interruptions.
A controlled Moltres objective was repeatedly replaced by restocking before reaching
the encounter. Next, investigate maintenance budgeting and reaching the chosen location,
using the saved reproductions. Preserve the live endurance interval until a fix shows
clear overall benefit. Physical collision correctness alone was insufficient here.

Monitoring now records filesystem space and the sizes of each game's data and backups.
The initial measurement found about 25.6 GB free and 8.2 GB in these backup directories.
No retention settings or historical files were changed.


## Seafoam recovery delivery

The next heartbeat found Blue without a journal achievement for about 29 minutes.
Its party had exhausted attacking PP. A copied save repeated falls from Seafoam B1F
through B2F and B3F, followed by the current to B4F, while trying to reach healing.
Release rc12 avoids the eight floor holes during routine travel and uses ladders.

The corrected replay fully restored HP and PP at Fuchsia Pokémon Center after 7632
frames, then picked up Full Restore and resumed gaining experience. Red's regression
was unchanged. All 386 tests passed. Blue received rc12 with a cold backup and has
already left Seafoam live. Red remains on rc10 so its active endurance interval continues.
See [the evidence](validation/seafoam-exit-0.2.0rc12.json) and
[deployment receipt](validation/release-0.2.0rc12.json).

The held rc11 experiment is preserved on `codex/held-navigation-candidate` and is excluded
from rc12. Next, watch Blue for renewed training and successful expeditions. Seafoam's
Articuno boulder puzzle still needs explicit planning. Continue investigating collection
budgets consumed by restocking and storage trips on Red.


## Reserve preparation followup

Release rc13 resets training idle time once when a selected partner first reaches a
stable party snapshot. The persisted experience baseline prevents reloads and repeated
PC transitions from repeating this milestone. The overall project deadline is unchanged.

In the two-hour comparison from a fresh Red checkpoint, both versions gained six levels.
The candidate also picked up two items and won six trainer battles, including a League
rematch. Local recoveries fell from 38 to 33. Neither version caught a new species, and
the initially selected Butterfree still failed to gain experience. Preparation was one
contributor, not a complete explanation of slow collection. Blue's regression remained
unchanged. All 387 tests passed. See
[the comparison](validation/training-preparation-0.2.0rc13.json).

Red received rc13 from `17cd997` with a cold backup and a successful current-save load.
Blue stayed on rc12 and caught a level-25 Kangaskhan live in Safari Zone East, reaching
116 registered entries. Both games remained healthy with zero save reloads. All 12
public checks passed. See [the receipt](validation/release-0.2.0rc13.json).

Next, preserve the live intervals while measuring actual training gains and new catches.
Investigate repeated supply detours and arrival at chosen encounter areas if Red remains
unproductive. The new reproduction is `data/operations/repros/red-preparation-20260914`.
The first live trade remains unapproved and unexecuted.

Filesystem use after the build and backup was 78.58 percent, with 22.71 GB free.
No historical saves or backups were deleted. Continue watching storage growth and plan
bounded backup and image retention before repeated releases consume the available space.


## Partial training accounting followup

A validated change awaiting the next release keeps productive training marked as partial
progress when the idle guard ends a project. Previously this path escalated the failure
penalty despite recorded XP gains. The ordinary retry delay and idle deadline remain.
All 388 tests pass, and the copied Red healing replay is unchanged. Both live processes
continue on their existing releases for endurance observation. See
[the evidence](validation/partial-training-20260915.json).
