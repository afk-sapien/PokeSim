# Gameplay and feature guide

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
| `/pokedex`, `/pc`, `/journal`, `/trading` | collection reference, storage and locks, event history, and game-local trading |
| `/stream` | MJPEG stream of the screen (`/frame.jpg` for a single frame) |
| `/feed.xml` | Atom feed of notable events; `?all=1` for everything, `?types=badge,catch` or `?min_priority=4` to filter |
| `/events/{id}` | one event and screenshot, with rewind available when a saved state and access policy allow it |
| `/api/state` | JSON: emulator status + parsed game state |
| `/api/events` | JSON event list (`limit`, `all`, `types`, `min_priority`, `before`) |
| `/api/control` | POST an `action` and optional `value`. Actions: `pause`, `resume`, `take_control`, `save`, `restart`, `speed`, `load_state`, `press` |

## Notifications

Open the Library and choose **Notifications**. No account or settings file is needed.

1. Leave the server as `https://ntfy.sh`, or enter your own ntfy server.
2. Choose **Generate a random topic**. On a public server anyone who knows the topic can read
   it, so a random topic works like a password. An access token is only needed for a protected
   topic or a private server. It is stored in the application folder and never shown again.
3. Subscribe to the same topic in the ntfy phone app, or open the address shown on the page.
4. Turn on **Send notifications**, choose **Send a test notification**, then save.

Choose which adventures notify and which kinds of news are sent. New adventures notify until
they are turned off. Changes apply to running adventures right away, and each title names its
adventure, such as "Red · Beat Brock! Got the Boulder Badge". Notifications keep their
screenshot and open the journal entry when tapped.

| Kind | Default | Events |
|---|---|---|
| Stuck or needs attention | on | `stall` |
| Gym badges | on | `badge` |
| Elite Four and Champion | on | `champion`, Elite Four `trainer` wins |
| Legendary Pokémon | on | legendary `catch`, `legendary_retry` |
| New Pokédex entries | on | other `catch`, `obtain` |
| Evolutions | on | `evolve` |
| Trades between adventures | off | completed Cable Club exchanges |
| Rival and notable trainers | off | other notable `trainer` wins |
| Level milestones | off | `level` (every tenth level) |
| New areas and key items | off | `map`, `item` |
| Blackouts | off | `blackout` |
| Everything else | on | `money`, `name`, `playtime`, and any type added later |

Only notable events (priority 2 and up) are ever pushed. **Least important notification**
raises that threshold.

`NTFY_URL`, `NTFY_TOKEN`, `NTFY_MIN_PRIORITY` and `NTFY_MUTE` in the manager's environment are
optional defaults. They apply until notifications are saved in the Library, and the Library
wins from then on. The legacy single-game runtime has no Library and uses only these variables.

## Configuration (environment)

These variables configure the legacy single-game runtime. The Adventure Library keeps its
settings in the browser.


| Var | Default | Meaning |
|---|---|---|
| `ROM_PATH` | `roms/pokered.gb` | the ROM |
| `DATA_DIR` | `data` | sqlite db, screenshots, save states |
| `SPEED` | `1` | emulation speed multiplier, `0` = unlimited |
| `POLICY` | `strategic` | objective-driven play with verified menu actions, navigation, battle estimates, and resource management. `smart_random` and `guided_random` remain available as baselines |
| `FAST_TEXT` | `1` | force the in-game text speed to FAST |
| `BATTLE_ANIMATIONS` | `1` | `0` turns battle animations off (faster) |
| `SEED` | random | RNG seed for the policy, starter choice, and random names |
| `STARTER` | `random` | new strategic adventures choose among all three starters. Set `bulbasaur`, `charmander`, or `squirtle` for a fixed choice. Saved adventures retain their choice |
| `NTFY_URL` / `NTFY_TOKEN` | off | push notable events (with screenshot) to an ntfy topic, such as `https://ntfy.sh/my-topic`. Optional defaults for the Library's [Notifications](#notifications) page |
| `NTFY_MIN_PRIORITY` | `2` | only push events at or above this priority (1–5, see below) |
| `NTFY_MUTE` | | comma-separated event types never pushed, e.g. `map,blackout` |
| `PUBLIC_URL` | `http://localhost:8000` | absolute links in the feed / ntfy click actions |
| `AUTOSAVE_SECONDS` / `KEEP_AUTOSAVES` | `60` / `20` | save-state rotation |
| `STUCK_RELOAD_SECONDS` | `600` | stationary timeout, valid strategic overworld play replans while other cases can reload an autosave |
| `STALL_ALERT_GAME_MINUTES` | `120` | game time without an achievement before a `stall` journal entry is recorded, `0` turns it off |
| `STALL_ALERT_REAL_MINUTES` | `15` | real time that must also pass, so Max pace does not report brief lulls |
| `STALL_ALERT_REPEAT_HOURS` | `6` | real hours before a continuing stall is reported again |
| `BATTLE_TIMEOUT_SECONDS` | `900` | a battle lasting this long → reload |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | native service bind address and port |
| `VIEWER_ONLY` | `0` | disable browser game controls and preference writes |
| `EVENT_RETENTION_DAYS` | `0` | journal retention, with `0` keeping all history |
| `TRADING_URL` / `TRADING_INSTANCE` | empty | broker URL and instance key for [game-local trading](pc-trading.md) |
| `TRADE_TOKEN` | empty | scoped peer authentication for [automatic exchanges](automatic-trading.md) |
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
- Guards: invalid game state and battle timeouts can trigger checkpoint recovery.
  A stationary strategic run with a valid overworld snapshot abandons its objective
  and replans without reloading.
  Baseline policies can reload an autosave after the stationary timeout.

## Tests

See [Contributing](../CONTRIBUTING.md#checks-before-a-pull-request) for the Python,
browser, documentation, package, and optional ROM checks.

## Strategic play

All three policies enter random names for the player and rival during the opening, and
accept nickname prompts for newly caught Pokémon, starters, and gifts. Names are chosen
from readable word lists in `pokesim/policies/naming.py`, with separate pools for trainers
and Pokémon. The controller types through the normal naming grid, so catches sent to the
PC follow the same naming flow. Trainer names fit the seven-character limit and Pokémon
nicknames fit the ten-character limit. Choices avoid repeats until their pool runs out.
`SEED` makes the name sequence repeatable, and naming state is included in policy saves.
Existing names are kept when resuming a game. Player and rival names are chosen on a new run.

New strategic adventures also choose a random starter. The choice is saved before the
Pokémon is received, so restoring a checkpoint does not reroll it. `STARTER` selects a
fixed partner when desired. Checkpoints from older releases retain the previous
Bulbasaur choice, with the actual starter family recognized when the party is observed.
Changing this setting does not replace Pokémon in an existing save.

The planner follows story flags for the starter, Oak’s parcel, and the Pokédex. It then
prepares for each gym and follows prerequisites through all eight badges and the League.
This includes Mt. Moon, Bill, the S.S. Anne, the Rocket hideout, Pokémon Tower,
Silph Co., Safari Zone HMs, the mansion key, and each Elite Four member.
The automatic player occasionally takes weighted detours toward less-visited tiles.
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

After the Champion, a persistent adventure director alternates collection, evolution,
training, and exploration projects. Category selection favors collection and evolution,
but avoids three consecutive projects of one category when alternatives are available.
Urgent supply projects can take priority. Failures wait progressively longer before a
retry, from about 17 simulated minutes to about 133 simulated minutes. Active deadlines,
recent choices, and a bounded record of outcomes survive restarts.

Training projects bring a unique partner out of storage when needed, give it the lead,
and work toward its next ten-level milestone, up to level 100. Missing level evolutions
take priority over general training for that partner. Training measures that partner's
experience and levels, so unrelated battles and supply changes cannot hide a stalled
project. A productive session can end before its target and rotate to another project.
The current implementation does not train stat experience explicitly or search for
better DVs. Trade requests will join the planner after coordinated live trading is ready.

The collection status in `/api/state` includes `director` outcomes with completion or
deferral reasons, retry times in simulated frames, and training gains. These records
describe bounded projects, not a guarantee of Pokédex completion or indefinite progress.

Ground items have their own short detours, including during collection expeditions in
caves. The planner checks nearby item balls, selects a reachable approach on the same
map, and resumes its previous objective afterward. Healing, supplies, party management,
and League battles retain priority. A detour pauses the original expedition's budget
and lasts at most 30 simulated seconds before deferral. Failed pickups wait five
simulated minutes before another attempt.

Pickups require a free bag slot or room in an existing stack. A full stack is skipped,
and TM pickups conservatively require a free slot. The game object's disappearance
confirms collection, with completed pickups and retry times saved across restarts.
These detours target visible item balls. Hidden items and balls containing Pokémon
remain outside this pickup behavior. Item gains appear in the existing journal, and
the strategy's `pickups` status records recent pickup outcomes.

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

## The ongoing adventure and collection journal

The automatic player mixes bounded collecting and evolution projects into the badge
journey, then continues with Pokédex expeditions after the Hall of Fame. It chooses
projects automatically. Playback speed changes how fast the game runs.

Older saves still load with their active projects and progress intact. Saved adventure
style and exploration preferences are ignored, so every run uses the same automatic activity selection.

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
and unfinished projects survive controller restarts.

When storage needs room, duplicate cleanup keeps the best individual of each species.
It compares level, stat experience, move usefulness, and progress toward the next level
before using DVs as a tie-breaker. A better boxed copy is retained alongside an established
party member. Exact ties favor the party member, then the first stored copy. Older snapshots
without individual stats retain the level-only selection rule. Protected species and the
last copy of a species are never released. The trade broker uses the same spare selection.
This does not add perfect-DV hunts or replace party members for small DV differences.

The GUI has four pages:

- **Live** (`/`): the game, current goal, all six party members, and badge progress together.
  The game and the plan with the party align in two columns on desktop.
  A compact trainer strip below both columns holds badges, registrations, League wins, and money.
  The gamepad opens when taking control. Detailed planning, route, and bag panels are omitted from Live.
- **Pokédex** (`/pokedex`): all 151 species in one list, with search, filters, and individual records.
- **PC** (`/pc`): physical boxes or the entire collection on one page, with search, sorting,
  individual DVs, and training. All Pokémon includes every partner without pagination.
- **Journal** (`/journal`): event filters, highlights, and earlier moments.

The PC box selector changes the view, not the game's active box. Keyboard game controls
work only on Live. Old `/team` and `/journey` links return to the corresponding section on Live.
The nickname pool gives new catches names such as TAXFRAUD, MEATWIFI, and SOUPCRIME through
normal in-game naming. Names already assigned to existing Pokémon are preserved.

The Live page's play clock is stored by the app and keeps counting beyond 255 hours.
It counts 60 emulated frames as one second. Faster playback advances this clock faster,
and pauses or server downtime add no time. Autosaves and clean shutdowns persist the
clock. Loading an earlier save does not subtract time already spent playing, while
Restart run starts a new clock. An abrupt failure can lose time since the last autosave.

Existing runs start from their cartridge time. If the cartridge already reached 255 hours,
the clock shows a `+` and a note because the earlier total is a lower bound. The app counts
new time from that point. The cartridge display and older journal times stay unchanged.
The state API exposes the app clock separately as `play_clock`.

The searchable Pokédex separates link-trade and event requirements from available
sources. “Possible here” includes future evolutions and choices, rather than claiming
that every listed entry is immediately reachable or that all mutually exclusive
choices can be collected in one save. The planner checks routes before hunts and
uses separate Red and Blue encounter data.

Collection source data is regenerated from a pret/pokered checkout with:

```sh
python -m pokesim.prepare_data /path/to/pokered
```

## Reproduce a stalled expedition

Copy a live autosave and its matching JSON manifest into a scratch directory. Keep the
original pair unchanged. Use the matching user-supplied ROM and PyBoy 2.7.0:

```sh
python tools/validate_progress.py --rom /path/to/pokered.gb --checkpoint /scratch/auto-v1-example.state --frames 432000 --output /scratch/progress.json
```

The replay restores policy state as well as game state. It advances two simulated hours
without rewinds and reports new Pokédex entries, experience changes, journal achievements,
policy recoveries, and input fingerprints. It does not claim to replace live endurance
validation, whose guard timers use wall time.

## Read-only proposals for a live pair

Set `GAME_DATA_DIR` to a prepared game-data directory and run
`docker compose -f deploy/compose.broker.yaml up -d`. The board is available on port 8950
and polls Red on port 8930 and Blue on port 8940 through the host gateway. It mounts only
read-only game data and has no access to saves or ROMs. It cannot execute an exchange.
Each actual exchange requires approval of its specific participants before live saves
are stopped, backed up, validated, and exchanged.

## Ongoing collecting

Registering a species does not remove it from future catching expeditions. The
player prioritizes missing Pokédex entries and Pokémon requested by other running
adventures. It also seeks species it no longer holds and occasionally catches
another copy of a species already in its collection. Plentiful and recently caught
species receive less attention.

Each repeat expedition aims to acquire one additional individual before choosing
its next project. Ordinary repeat hunts require a reserve of normal Poké Balls and
use a bounded attempt budget. They do not spend a Master Ball. Storage cleanup
retains useful copies and respects locks, offers, active projects, and the copies
currently needed for other adventures. A single adventure continues collecting
without needing a trading partner.

## Individual Elite Four wins

The PC shows an **Elite Four wins** count on each Pokémon card and in its details. In **All Pokémon**, choose **Elite Four wins** under **Sort by** to rank the party and every box together.

Each completed Elite Four and Champion run credits every member of the Hall of Fame party, including fainted members. Boxed Pokémon receive no credit for that run. Counts persist through evolution, training, PC moves, restarts, and managed cable trades. Replayed victory records and repeated trade recovery do not add duplicate credit.

Counts include verified historical victory saves when imported. Missing history is not estimated. Generation I has no unique individual identifier. If two partners have indistinguishable trainer and DV data, the count shows **Unavailable** to avoid assigning one Pokémon's wins to another.

## Training more partners to level 100

After becoming Champion, training projects aim for level 100 and favor eligible Pokémon within five levels of the highest unfinished partner. Training takes a larger share of postgame projects, with breaks for collecting, exploration, League rewards, and urgent supplies. Productive training can return to the same individual after a bounded session, while stalled projects retain their normal timeout and retry safeguards.

Individually identifiable duplicates can train even when another member of their evolution family is owned. Pokémon already at level 100 are excluded. When preparing a boxed trainee, the party prefers to deposit a level-100 reserve while keeping a strong battler and required field moves. A trainee with a safe, effective attack stays in battle rather than switching merely for a stronger matchup. Healing and emergency switches still take priority.
