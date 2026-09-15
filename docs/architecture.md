# Code ownership and refactoring guide

Keep game decisions separate from emulator I/O, persistence, and HTTP presentation.

For the proposed application that manages several adventures in one desktop app or Docker container, see the [multi-adventure architecture and refactor plan](multi-adventure-app-plan.md). That document describes planned work and acceptance gates, not current runtime behavior.

| Area | Owner | Boundary |
| --- | --- | --- |
| Emulator lifecycle and input | `pokesim/emulator.py` | Owns PyBoy and executes queued commands on the worker thread. Releases each pressed button even if a frame update fails. |
| Event journal and run memory | `pokesim/store.py` | Owns SQLite and event attachments. Serializes connection access and rolls back failed writes. |
| Checkpoint files | `pokesim/checkpoints.py` | Owns file publication, checksums, manifests, lookup, and autosave retention. Can be used without SQLite or PyBoy. |
| HTTP endpoints | `pokesim/web/app.py` | Validates requests, applies viewer restrictions, and connects runtime services to responses. |
| Atom presentation | `pokesim/web/feed.py` | Renders event dictionaries without reading configuration, querying storage, or creating an HTTP app. Uses XML serialization and separately escapes embedded HTML. |
| Pokédex reference | `pokesim/web/pokedex.py` | Assembles Pokédex entries from the generated tables and reshapes one snapshot dictionary for the Pokédex page. Reads no configuration, storage, or emulator state, and creates no HTTP app. |
| Policy orchestration | `pokesim/policies/strategic.py` | Coordinates observed screens, goals, navigation, collection, and action confirmation. |
| Domain decisions | Other modules in `pokesim/policies/` | Own battle scoring, routes, progression, team preparation, naming, puzzles, and collection planning. |

The `Store` checkpoint methods remain available as forwarding methods. Existing callers and the version 1 checkpoint format remain compatible. Changes to file handling belong in `CheckpointStore`, rather than in the SQLite facade.

Event insertion and its attachment writes share a database transaction. If a write or database update raises an exception, the row is rolled back and attachment cleanup is attempted before another writer can use the connection. Cleanup errors are logged without replacing the original error. This is exception recovery, not a transaction across SQLite and the filesystem. A process or machine crash can still leave orphaned attachments.

Each checkpoint file is published using a temporary file and an atomic rename. A handled write failure removes the new pair when possible. A crash between publishing the state and manifest can still leave an incomplete pair, which startup rejects before trying an older compatible checkpoint. Do not change this fallback into a silent new game.

## Next refactoring priorities

1. Split `StrategicPolicy` by state ownership. Its menu dispatch and overworld planning share intent, shop context, storage targets, and recovery state. Extract controllers with explicit inputs and owned transient state. Moving methods into mixins would preserve the coupling. Start with shop and PC interactions, using the existing shopping-context and box-capacity scenarios to preserve precedence.
2. Consolidate emulator restore and restart bookkeeping. Those paths reset overlapping combinations of snapshots, pending events, input epochs, policy memory, and guard timers. Add transition scenarios before introducing a shared reset helper, since a rewind and a fresh run intentionally preserve different information.
3. Extract the event detail page from the HTTP module. Keep HTML generation separate from routing and replace its inline rewind script with a static event handler. Cover viewer restrictions and rewind behavior when doing that work.

Prefer synthetic snapshots and explicit failure injection for these changes. The persistence tests cover interrupted attachment writes, rejected database updates, incomplete checkpoint publication, corrupt manifests, and save path containment. The emulator tests cover button release before retrying after a frame error. Feed tests parse both the XML and embedded HTML.

The ROM smoke and deterministic opening replay tests provide additional integration coverage. They do not establish full-campaign or endurance reliability.
