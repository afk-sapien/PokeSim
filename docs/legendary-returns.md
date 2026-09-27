# Legendary returns

PokeSim can bring Articuno, Zapdos, Moltres, and Mewtwo back to their original
locations for repeat expeditions. Every adventure has its own walking progress.
The default milestone is 1,000,000 completed steps.

## Rules

- A milestone makes one return available for each previously acquired legendary.
  Pokédex registration through a trade also qualifies.
- Unclaimed returns stay available. Passing additional milestones does not bank
  extra encounters. A successful capture consumes the available return.
- Failed attempts use the existing delayed retry system. Balls, damage, and
  travel costs are preserved. A new battle generates its DVs normally.
- The player must leave the encounter's room before PokeSim changes its flags.
  Battles, dialogue, and menus defer that change.
- The AI plans repeat expeditions even for registered species. It uses the
  legendary capture routine, including status moves, supplies, and storage checks.
- Captured returns stay spent across process restarts and checkpoint restores.
  An old save does not earn a new claim. The AI leaves already spent encounters,
  and the encounter flags are reconciled after it leaves the room.

## Progress and settings

Journal Stats shows the remaining steps and any returned legendaries ready to
revisit. A short journal entry announces each return.

Stop an adventure to change **Steps between legendary returns** in its settings.
Use 0 to disable returns. Re-enabling starts a new milestone from the current
walking total. Changing an active interval starts the next milestone
from the current walking total and preserves existing unclaimed returns.
Standalone deployments can set `LEGENDARY_RETURN_STEPS`.

## Counting and persistence

Walking progress begins when this feature is installed. Older sampled walking
statistics are not converted into milestone credit. The counter hooks the
verified English Red and Blue cartridge instruction that decrements the game's
step counter after a completed movement tile. Scripted movement is excluded by
the cartridge routine. Walking, cycling, and surfing use the same routine.
Unknown cartridges do not receive an unverified hook or claim exact progress.

The durable step total is saved every 30 seconds, at milestones, and during
normal saves. A forced process kill can lose at most the unflushed step buffer.
Return claims live separately from emulator checkpoints. Their consumption is
atomic with the catch receipt, so retrying receipt processing cannot spend a
second claim. Historical milestone cycles do not create a backlog of captures.
