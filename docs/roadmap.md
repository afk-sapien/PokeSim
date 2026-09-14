# Roadmap: two adventures that keep progressing

Updated September 14, 2026.

The near-term target is two entertaining autonomous Red and Blue adventures that keep
making progress and can eventually exchange Pokémon. Guaranteed Pokédex completion,
restart farming, perfect-DV optimization, and authentic link-cable emulation are outside
this scope. Missing encounters and unchosen gifts must remain visible limitations.

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

## Later work

Improve encounter and NPC trade data, separate shop and PC state from the main policy,
and consolidate reset bookkeeping as related changes require it. Existing serial-hook
experiments are research, not a prerequisite for the save-based exchange workflow.
