# pokesim

A Pokémon Red that plays itself. A headless Game Boy emulator (PyBoy) runs the game 24/7,
driven by a policy that plans objectives and checks each action against the game state. A small web app shows the
live screen, party and stats, and a timeline of things that happened. Notable events
(caught a Pokémon, beat a gym, evolved, new area, blacked out, champion, ...) are detected by
diffing the game's RAM and published as an Atom feed with a screenshot, and optionally
pushed to [ntfy](https://ntfy.sh).

## Run it

Follow the current [installation instructions](../README.md) and [operations guide](operations.md). This page describes gameplay and advanced settings.

## Endpoints

| Path | What |
|---|---|
| `/` | live view, stats, timeline, controls |
| `/stream` | MJPEG stream of the screen (`/frame.jpg` for a single frame) |
| `/feed.xml` | Atom feed of notable events; `?all=1` for everything, `?types=badge,catch` or `?min_priority=4` to filter |
| `/events/{id}` | one event with its screenshot and a "rewind the game to this moment" button |
| `/api/state` | JSON: emulator status + parsed game state |
| `/api/events` | JSON event list (`limit`, `all`, `types`, `min_priority`, `before`) |
| `/api/control` | POST `{"action": "pause"|"resume"|"save"|"restart"|"speed"|"load_state"|"press", "value": ...}` |

## Configuration (environment)

| Var | Default | Meaning |
|---|---|---|
| `ROM_PATH` | `roms/pokered.gb` | the ROM |
| `DATA_DIR` | `data` | sqlite db, screenshots, save states |
| `SPEED` | `1` | emulation speed multiplier, `0` = unlimited |
| `POLICY` | `strategic` | objective-driven play with verified menu actions, navigation, battle estimates, and resource management. `smart_random` and `guided_random` remain available as baselines |
| `FAST_TEXT` | `1` | force the in-game text speed to FAST |
| `BATTLE_ANIMATIONS` | `1` | `0` turns battle animations off (faster) |
| `SEED` | random | RNG seed for the policy and random names |
| `NTFY_URL` / `NTFY_TOKEN` | off | push notable events (with screenshot) to an ntfy topic |
| `NTFY_MIN_PRIORITY` | `2` | only push events at or above this priority (1–5, see below) |
| `NTFY_MUTE` | | comma-separated event types never pushed, e.g. `map,blackout` |
| `PUBLIC_URL` | `http://localhost:8000` | absolute links in the feed / ntfy click actions |
| `AUTOSAVE_SECONDS` / `KEEP_AUTOSAVES` | `60` / `20` | save-state rotation |
| `STUCK_RELOAD_SECONDS` | `600` | no position change for this long → reload an older autosave |
| `BATTLE_TIMEOUT_SECONDS` | `900` | a battle lasting this long → reload |
| `STREAM_FPS` | `15` | MJPEG frame rate |

## Event priorities

Every event has a priority from 1 to 5, using the same scale as ntfy so it maps straight onto
phone notification levels. Priority 2 and up is "notable": those events get a save state, appear
in the feed by default and are pushed to ntfy. Priority 1 events only show on the timeline
(and in `?all=1`). Filter the feed, the API and ntfy with `min_priority`.

| Priority | Events |
|---|---|
| 5 urgent | champion, gym badge, legendary catch, Elite Four member defeated |
| 4 high | catch, evolution, new Pokédex entry (starter, gift, fossil), key item, rival or Giovanni defeated, level 50 / 100 |
| 3 normal | level multiples of 10, wallet passed $100k+, rival named |
| 2 low | new area, blackout, play-time milestone |
| 1 minimal | first sighting, faint, ordinary trainer, other levels, small money milestones |

Defaults live in `pokesim/events.py`; change a priority there to reclassify an event.

## How it works

- `pokesim/emulator.py` runs PyBoy in a thread: ask the policy for an action, press the
  button, tick frames, publish a JPEG frame for the stream, and every 30 frames read a RAM
  snapshot. Autosaves every minute; on start it resumes from the newest one.
- `pokesim/ram.py` knows the Pokémon Red WRAM layout (from the pret/pokered disassembly) and
  turns it into a typed `Snapshot`.
- `pokesim/events.py` diffs consecutive snapshots into events.
- `pokesim/policies/strategic.py` is the default brain. It observes fresh RAM after each
  action and handles battle menus, moves, forced switches, medicine, shopping, naming,
  dialogue, and move replacement as separate input states. The current objective and
  decision reason appear in the web app and under `strategy` in `/api/state`.
- `pokesim/policies/smart_random.py` is the older baseline. Still random at heart, but it reads the
  screen (`pokesim/screen.py` decodes the tile map as text, so it knows when the battle menu,
  a list, a yes/no prompt, a shop, the PC or the naming grid is open) and RAM, and:
  - explores tiles it has stood on least (curiosity) and remembers walls it walked into;
  - in battle picks a move with PP, throws a ball only if it has one (and prefers to when the
    wild Pokémon is under half HP), switches when the active Pokémon is nearly dead, runs
    from wild battles as a last resort;
  - walks back to a known Pokémon Center over the paths it has learned when the party is under
    30% HP, and talks to people there;
  - breaks any loop by mashing random buttons when screen + position haven't changed for 20
    decisions (the "no items, ITEM → CANCEL forever" class of problem).
  Exploration memory persists across restarts. `guided_random.py` is the original dumb version.
  Implement `Policy.step()` to add another.
- Guards: if the RAM stops looking like a running game (glitch/crash), a battle never ends,
  or the player hasn't moved for 10 minutes, the emulator reloads an autosave from before
  the trouble started.

## Tests

```sh
pytest         # unit tests for the event detector; ROM smoke test runs if roms/pokered.gb exists
```

## Strategic play

All three policies enter random names for the player and rival during the opening, and
accept nickname prompts for newly caught Pokémon, starters, and gifts. Names are chosen
from readable word lists in `pokesim/policies/naming.py`, with separate pools for trainers
and Pokémon. The controller types through the normal naming grid, so catches sent to the
PC follow the same naming flow. Trainer names fit the seven-character limit and Pokémon
nicknames fit the ten-character limit. Choices avoid repeats until their pool runs out.
`SEED` makes the name sequence repeatable, and naming state is included in policy saves.
Existing names are kept when resuming a game. Player and rival names are chosen on a new run.

The planner follows story flags for the starter, Oak’s parcel, and the Pokédex. It then
prepares for each gym and follows prerequisites through all eight badges and the League.
This includes Mt. Moon, Bill, the S.S. Anne, the Rocket hideout, Pokémon Tower,
Silph Co., Safari Zone HMs, the mansion key, and each Elite Four member.
The Exploration selector controls occasional weighted detours toward less-visited tiles.
Goals still pull the player forward, with focused navigation for healing and supplies.
Blocked objectives trigger short autonomous recovery attempts, followed by replanning.
The policy never pauses the simulator or requests a human handoff. Only explicit user
controls can freeze the game or enter manual mode. Battles do not count toward the
navigation stall timer. HM teaching uses species compatibility and protects existing HMs.
Snorlax’s flute interaction uses the bag automatically. Healing and low supplies
temporarily take priority over the story objective. The September 9 copied-save playtest
completed Bill's quest, the remaining six badges, and the Champion battle, then entered
the Hall of Fame. See [playtests](../RELEASE_STATUS.md) for the fixes and validation scope.
The policy also stops for occasional conversations and signs, with cooldowns and memory
to prevent repeatedly talking to the same person. Puzzle planners handle mansion switches
and Victory Road boulders. Live NPC positions and story changes update navigation.

Navigation combines map geometry with observed movement. Learned edges store the actual
button and destination, including doors, map connections, and ledges. Reverse movement is
never inferred from a learned edge. Temporary obstacles expire, and map transitions settle
before coordinates are learned. Static geometry is enabled only for a recognized Red or
Blue ROM. Unverified ROMs fall back to observed paths and exploration.

Battle decisions use live battle stats, the Generation I physical and special type split,
same-type bonuses, type matchups, accuracy, PP, common fixed-damage effects, and estimated
knockout risk, including expected Generation I critical-hit damage. The policy can heal, switch to a better matchup, or escape a dangerous wild
battle. Damage scores are estimates. They do not simulate every volatile effect, accuracy
stage or enemy decision.

Catch attempts favor missing species and useful team coverage, weaken targets when possible,
and stop after a bounded number of attempts. The policy preserves the Master Ball. Shopping
uses inventory targets, bag capacity, and a cash reserve. Pokémon Centers restore HP, status,
and PP. Move replacement protects HMs and compares the new move against existing choices.

Manual button presses take priority at the next action boundary and also work while paused.
Choose **Take control**, or press any game button, to pause the AI automatically.
Manual mode runs the game at normal speed and keeps the AI stopped between inputs.
Choose **Let AI play** to resume. **Freeze game** stops time until you unfreeze it.
The controller is always visible below the game, with keyboard and touch input.
 Rewinds clear pending bot
inputs and transient policy state while retaining learned navigation.

## Repeatable benchmarks

The adaptive planner searches land encounter habitats for missing HM partners, using
compatible boxed Pokémon first and the Lapras gift only after Silph Co. is cleared.
It verifies movement, menu, item, and field-move outcomes and detects short cycles.
Failed approaches, recent recoveries, and a seeded exploration personality survive restarts.

Gym and League preparation estimates damage, survival, attack PP, and supplies against
representative opponents with level-appropriate moves. The dashboard shows the current
objective, next step, reasons, matchup estimates, route map, and recent recoveries.
Scores are preparation heuristics, not victory probabilities. Training ceilings prevent
endless preparation against an unfavorable estimate.

Healthy parties can take short local detours to people, signs, and items. Promising reserves
get bounded training sessions when nearby encounters are manageable. Better boxed partners
can replace underused reserves at Pokémon Centers. The strongest partner and the last
carrier of each known field move are protected. Low health and essential objectives take
priority over optional detours. No part of this process requests a human handoff.

Compare policies using identical frame budgets and multiple seeds:

```sh
python -m pokesim.benchmark --policies strategic smart_random --seeds 1 2 3 \
  --frames 200000 --target boulder --output data/comparison.json
```

Reports contain first milestone times, completion rates, blackouts, recovery reloads,
policy recovery attempts, time spent in each mode, and manual interventions. Milestone
averages include successful runs only, with the completion rate reported alongside them.
An autonomous benchmark always reports zero manual interventions. Game frames, rather than
wall-clock duration or tiles visited, are the main progress measure.

Start a focused scenario from a saved emulator state:

```sh
python -m pokesim.benchmark --policies strategic --seeds 1 --frames 30000 \
  --checkpoint data/states/event-12.state --target boulder \
  --trace data/decision-trace.jsonl --output data/checkpoint-result.json
```

`--scenarios` accepts a JSON list of objects with `name`, `checkpoint`, `target`, and `frames`.
Checkpoint paths are relative to the scenario file. Each checkpoint starts with fresh policy
memory, which makes comparisons independent of prior exploration. Reports distinguish
milestones already present in a checkpoint from later progress. Omit `target` to use the
whole frame budget for a battle, shopping, or navigation scenario. `tools/replay.py` exposes
the same command-line interface.

Replays use emulated time for policy contexts and recovery guards, fixed input cadence, and
seeded randomness. Keep the ROM, PyBoy version, starting state, frame budget, and battle
animation setting the same when comparing runs. Recovery reloads retain learned navigation
but clear in-flight actions, as in the application.

## Generated game data

Runtime data is generated locally during setup and excluded from release artifacts. The local `strategy.json` and bundle manifest record the source
revision from the [pret/pokered disassembly](https://github.com/pret/pokered). It contains
move data, type matchups, species data, event flags, shop prices, and map geometry.

To regenerate strategy data from a local checkout:

```sh
python -m pokesim.prepare_data /path/to/pokered
```

## Thorough Adventure and the collection journal

Thorough Adventure is the default adventure style. It mixes bounded collecting and
evolution projects into the badge journey, then continues with Pokédex expeditions
after the Hall of Fame. The adventure style selector offers Focused, Balanced, and
Thorough. It changes which activities the AI chooses, independently of playback
speed. The selection persists across restarts.

Missing species now matter even when they are too weak for the main battle team.
The catcher prefers sleep or paralysis, avoids attacks with a high knockout risk,
and can switch to a healthy status specialist. Missing legendary encounters receive
priority, including the Master Ball when available. Storage capacity still blocks
impossible throws, and ordinary hunts have an attempt budget.

Collection projects include version-specific grass, Surf, Safari and fishing
encounters, obtaining fishing rods, level and stone evolutions, withdrawing boxed
partners, gifts, fossil revival, available in-game trades, and Game Corner coins
and prizes. The strongest battler and sole HM carriers are protected when making
room at the PC. Useful vitamins and Rare Candies can free bag space. Projects time
out and enter a cooldown so one unsuccessful hunt cannot take over the adventure.

After the Champion, the simulator finishes the ceremony, continues the saved game,
and looks for more collection projects. It can visit unexplored areas, meet unbeaten
trainers, and undertake League rematches when funds run low. Captures, time budgets,
and unfinished projects survive controller restarts. No Pokémon are released.

The Collection section shows the current project, registered entries, remaining
possibilities, evolution targets, recent expeditions, and all twelve storage boxes.
Its searchable Pokédex separates link-trade and event requirements from available
sources. “Possible here” includes future evolutions and choices, rather than claiming
that every listed entry is immediately reachable or that all mutually exclusive
choices can be collected in one save. The planner checks routes before hunts and
uses separate Red and Blue encounter data.

Collection source data is regenerated from a pret/pokered checkout with:

```sh
python -m pokesim.prepare_data /path/to/pokered
```
