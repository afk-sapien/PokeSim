# Code ownership and refactoring guide

Keep game decisions separate from emulator I/O, persistence, and HTTP presentation.

For the proposed application that manages several adventures in one desktop app or Docker container, see the [multi-adventure architecture and refactor plan](multi-adventure-app-plan.md). That document describes planned work and acceptance gates, not current runtime behavior.

| Area | Owner | Boundary |
| --- | --- | --- |
| Runtime ownership | `pokesim/runtime.py` | Holds the adventure directory lock, opens storage and emulator, and closes them in order. Reports final-save errors after shutdown. Shared by desktop and server. |
| Shopping controller | `pokesim/policies/shopping.py` | Owns buying, selling, and restocking state. Returns menu decisions and supply plans from explicit snapshot, goal, and project inputs. |
| Storage controller | `pokesim/policies/storage.py` | Owns PC operation, reserve destination, and pending release confirmation. Rechecks protection and slot identity before release. |
| Emulator lifecycle and input | `pokesim/emulator.py` | Owns PyBoy and executes queued commands on the worker thread. Releases each pressed button even if a frame update fails. |
| Event journal and run memory | `pokesim/store.py` | Owns SQLite and event attachments. Serializes connection access and rolls back failed writes. |
| Checkpoint files | `pokesim/checkpoints.py` | Owns file publication, checksums, manifests, lookup, and autosave retention. Can be used without SQLite or PyBoy. |
| HTTP endpoints | `pokesim/web/app.py` | Validates requests, applies viewer restrictions, and connects runtime services to responses. |
| Journal detail presentation | `pokesim/web/event_page.py`, `pokesim/web/static/event.js` | Renders escaped event data independently of routing. The browser requests rewinds and displays rejected requests without navigating away. HTTP routes retain access checks. |
| Desktop lifecycle | `pokesim/desktop.py`, `pokesim/desktop_setup.py`, `pokesim/platform_io.py` | Owns local setup, launcher identity, platform paths, and desktop shutdown presentation. Delegates adventure resource ownership to Runtime. |
| Trade preferences and presentation | `pokesim/trade/preferences.py`, `pokesim/web/trading.py` | Defines partner eligibility and shapes broker results for the local game UI. |
| Atom presentation | `pokesim/web/feed.py` | Renders event dictionaries without reading configuration, querying storage, or creating an HTTP app. Uses XML serialization and separately escapes embedded HTML. |
| Pokédex reference | `pokesim/web/pokedex.py` | Assembles Pokédex entries from the generated tables and reshapes one snapshot dictionary for the Pokédex page. Reads no configuration, storage, or emulator state, and creates no HTTP app. |
| Policy orchestration | `pokesim/policies/strategic.py` | Coordinates observed screens, goals, navigation, collection, and action confirmation. |
| Domain decisions | Other modules in `pokesim/policies/` | Own battle scoring, routes, progression, team preparation, naming, puzzles, and collection planning. |

The `Store` checkpoint methods remain available as forwarding methods. Existing callers and the version 1 checkpoint format remain compatible. Changes to file handling belong in `CheckpointStore`, rather than in the SQLite facade.

Event insertion and its attachment writes share a database transaction. If a write or database update raises an exception, the row is rolled back and attachment cleanup is attempted before another writer can use the connection. Cleanup errors are logged without replacing the original error. This is exception recovery, not a transaction across SQLite and the filesystem. A process or machine crash can still leave orphaned attachments.

Each checkpoint file is published using a temporary file and an atomic rename. A handled write failure removes the new pair when possible. A crash between publishing the state and manifest can still leave an incomplete pair, which startup rejects before trying an older compatible checkpoint. Do not change this fallback into a silent new game.

## Transition contracts

- Resume discards queued input and recovery timers while retaining event observations,
  game state, speed, and durable progress.
- Restore also discards stale event comparisons, loads paired checkpoint memory, and
  refreshes the snapshot. Existing pause and manual-control settings are preserved.
- Restart clears the adventure's policy memory, autosaves, offer preferences, rewards,
  and trade barrier. It resets the frame clock and starts automatic play. Journal
  history and configured speed remain available.
- Trade holds reject restart, resume, manual takeover, and ordinary restore at command
  execution time. A slow shutdown keeps the database and directory lock until the
  worker has actually stopped.

Shopping and PC controllers own transient state. `StrategicPolicy` chooses the menu
context and applies explicit returned effects, including completed supply preparation.
Controllers receive snapshots and project data rather than a reference to the policy.
Existing version 1 checkpoint dictionaries remain compatible.

## Next refactoring priorities

1. Apply the same explicit state ownership to battle and field-move interactions when
   changing those features. Keep routing and priority decisions visible in the policy.
2. Replace module-global settings before supporting several adventures in one process.
   The current runtime remains one adventure per process.
3. Keep HTTP presentation in focused renderers or static assets. Preserve route and
   real-browser checks for permissions and rejected actions.

Prefer synthetic snapshots and explicit failure injection for these changes. The persistence tests cover interrupted attachment writes, rejected database updates, incomplete checkpoint publication, corrupt manifests, and save path containment. The emulator tests cover button release before retrying after a frame error. Feed tests parse both the XML and embedded HTML.

The ROM smoke and deterministic opening replay tests provide additional integration coverage. They do not establish full-campaign or endurance reliability.
