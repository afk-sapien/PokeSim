# Multi-adventure application

The implementation lives on `codex/multi-adventure-app`. It was developed in an isolated worktree from baseline `bd9f570`, which captures the existing workspace work without changing the original checkout. The [design plan](multi-adventure-app-plan.md) explains the architecture and release gates.

## What now runs

One application owns the Adventure Library and starts one private process per running adventure. Several adventures can use the same Red or Blue ROM while keeping separate saves, journals, settings, process locks, and runtime generations. The Python desktop launcher and Docker use the same manager. Python packages and Docker are the supported distribution paths.

The library supports ROM upload and reuse, adventure creation, start, save and stop, archive and restore, profile settings, a running-game limit, local trading groups, explicit trades, automatic useful exchanges, backups, and legacy import. Existing game pages use adventure-scoped routes and an adventure switcher. The manager authenticates its browser session, protects writes against cross-site requests, and authenticates all private worker routes.

Game workers own their databases. The manager keeps library metadata and durable interaction decisions. A temporary cable child receives isolated prepared snapshots, executes the games' original exchange, and returns verified results. Each owner stages and adopts its own result.

## Trading behavior

The production cable adapter descends from experiment commit `705ec4d`. It supports the verified English retail Red and Blue ROMs on PyBoy 2.7.0. Verified hook metadata ships with the application, so players do not need RGBDS or a reference checkout.

An exchange follows this path:

1. Recheck the selected boxed offers and their protections.
2. Navigate each game to Vermilion's Center using normal gameplay. Use the PC menus to retrieve the exact selected individual, making space with a safe reserve if necessary.
3. Hold both adventures and export verified source checkpoints.
4. Start two temporary emulators connected by the bounded ROM-hook transport.
5. Run the original menus, transfer, animation, evolution, Pokédex update, and cartridge saves.
6. Cancel the trade menus, detach transport hooks, and use the game's supported soft-reset and Continue sequence to return to the Center.
7. Verify both checkpoint and cartridge-save restarts, exact individual data, untouched party members, and all stored boxes.
8. Durably stage both results, record one commit decision, then apply and release both owners.

The original Trade Center has no ordinary exit warp. The reset sequence follows the cartridge's intended save behavior and uses button input. It does not teleport a game or patch Pokémon records.

Cable failures have no record-swap fallback. Before commitment, both prepared sources remain authoritative. After commitment, recovery applies the recorded outputs without running the trade again. Unrelated adventures keep playing. Current link frames are available through the participating games' existing screen routes.

See [cable qualification](cable-production.md) for the original experiment, transport bounds, and private test matrix.

## Durable state and operations

- The application root has one ownership lock, and every adventure has a common runtime lock across managed and legacy launch modes.
- Repeated creation and lifecycle requests carry operation IDs. Replaying an old stop request cannot override a later start request.
- Prepared and staged files stay outside ordinary autosave discovery.
- The application records COMMIT only after both participants acknowledge durable staging.
- Each participant records its own commit receipt before promotion. Startup reconciles incomplete promotion before emulator restoration.
- Journal receipts and completed operation markers remain after temporary artifact cleanup.
- Shutdown preserves unresolved decisions and holds. Parent-pipe loss shuts down both ordinary workers and temporary link children.
- Optional Championship rewards and the custom Mew distribution are independent local operations. Their own durable receipt and rewind barrier prevent repeated delivery. They never substitute for a cable exchange.

## Imports and backups

Whole-application backups stop workers, copy a consistent registry and adventure set, and include a checksum manifest. Restore validates the archive into a separate empty directory. Browser imports reject traversal, symlinks, duplicate archive paths, and oversized expanded content.

Single legacy imports preserve gameplay, journals, checkpoints, and reward counters. A legacy adventure with trade history requires a coherent peer migration before it may join new exchanges. A copied individual campaign cannot silently bypass its past trading obligations.

The `import-pair` command verifies both stopped source adventures against their shared legacy coordinator history and retained result hashes, then registers the pair atomically. Unknown or incomplete lineage remains blocked. Backups preserve whether each resumed game was playing, paused, or under manual control, and queued launches wait until copying finishes.

The original services and source directories are not migrated or restarted by developing this implementation. Existing single-game deployment remains available through explicit `legacy` mode and `compose.legacy.yaml`.

## Validation

Local validation uses disposable copies of private test cartridges and checkpoints. No private ROM or save data belongs in the repository or public build artifacts.

Validated on Linux x86-64:

- Full Python and JavaScript regression suites.
- Same-version independent workers, request idempotency, capacity enforcement, authentication, and archive handling.
- Real Red/Blue, Red/Red, and Blue/Blue cable exchanges with both clock-role assignments and arbitrary selected party slots.
- All four trade evolutions, disabled-cable negative control, unequal stepping, disconnect, cancellation, and parent-death handling.
- Normal PC preparation from a full party, including reserve deposit and selected boxed withdrawal.
- Real two-worker owner staging, duplicate commands, restart while committed and held, restart after release, and exactly one journal receipt.
- Failure of the second stage, rollback of both prepared inventories, and restart without either provisional result.
- The complete manager flow with three real workers, a failure after durable commitment, manager restart recovery, exactly one history entry, and continued progress in the unrelated game.
- Default species names changing correctly during real trade evolution while custom nicknames remain intact.
- Source worker authentication and save on parent EOF.
- Linux Python launcher startup and two native workers with independent saves.
- One non-root container with a read-only root filesystem, two private workers, scoped game routes, health checks, and clean shutdown.
- Browser creation, ROM reuse, stopped pages, independent dashboards, and worker-limit errors.

The final broad suite passed **696 Python tests**, with 10 legacy fixture tests explicitly skipped. A subsequent watchdog and backup check passed eight tests, including one additional watchdog regression. All **27 JavaScript tests** passed. The wheel, source distribution, and Docker checks passed. The earlier standalone prototype also completed a real cable exchange, but standalone artifacts are no longer part of the release scope. See the [validation report](validation/multi-adventure-20260915.json) for evidence, artifact checksum, and qualification limits.

The package-only follow-up passed 38 affected regressions and a fresh wheel install outside the checkout. Three new adventures then started from the beginning with separate starters and seeds, minute autosaves, and a shared automatic trading group. Their initial health, frames, saves, and early-game progress passed. A 24-hour observation run is in progress. See the [Python installation and fresh-game smoke record](validation/python-install-smoke-20260915.json). This newer distribution scope supersedes standalone release gates in the earlier historical report.

## Remaining release gates

Windows, Intel macOS, Apple Silicon, and Linux ARM64 Python install checks have CI definitions, but their successful execution is not established by Linux tests. Standalone downloads, signing, and notarization are outside the release scope. An overnight coordinated soak and longer unattended operation remain release qualification work.

The first cable preparation target is Vermilion's Center. Games without a supported route wait or fail with a reason instead of being teleported. Remote installations, link battles, and hardware-cycle-accurate serial emulation remain outside this release.

The long-lived workers retain a process-local compatibility adapter for legacy configuration globals. The manager imports without generated game data, and each worker installs immutable settings before loading game modules. Multiple independent long-lived games in one Python interpreter are not supported.
