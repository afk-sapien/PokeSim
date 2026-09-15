# Managed Cable Club executor

The managed trading backend runs the cartridge's original trade logic on two disposable emulator copies. It does not swap party or box records, write evolutions, or manufacture Pokédex registration. Successful results remain provisional until the manager durably commits both participants.

The transport descends from experiment commit `705ec4ddc2f0e5a1265170b33f101141c5892960`. A fresh reproduction of that experiment passed before extraction. The current implementation additionally negotiates arbitrary party slots, exits the selection menus, returns through the game's supported reset flow, and verifies both independent restart modes.

## Supported runtime

The adapter pins PyBoy 2.7.0 and these English retail ROM identities:

| Version | SHA-1 |
| --- | --- |
| Red | `ea9bcae617fdf159b045185467ae58b2e4a48b9a` |
| Blue | `d7037c83e1ae5b39bde3c30787637ba1d4c48ce2` |

Verified symbol addresses and hook instruction signatures are bundled in `pokesim/interactions/cable_metadata.py`. Installed applications do not require RGBDS, a reference disassembly, or a development worktree. Each emulator receives its own ROM byte stream and cartridge RAM stream. A checkpoint alone is sufficient because it contains cartridge RAM. An absent save file initializes a private 32 KiB stream before the checkpoint is loaded.

The adapter replaces synchronous byte and nybble exchange routines with bounded queues. Waiting CPUs temporarily park in verified unused ROM padding with interrupts disabled. The peer continues. Queue overflow, mismatched ordering, invalid stacks, invalid returns, deadlocks, phase stalls, and overall deadlines fail the complete attempt. These checks remain enabled under optimized Python.

## Session contract

`pokesim.interactions.link_worker.run_session(plan, output_dir, progress=None)` accepts a frozen `CableSessionPlan` containing two `CableParticipant` objects. Each participant identifies its adventure, verified ROM, prepared checkpoint, optional cartridge save, zero-based party slot, optional expected hashes, and optional selected identity key. Identity keys use the existing trading-preference contract. An explicitly selected key must uniquely identify the intended participant's Pokémon.

The source checkpoints must be safe overworld states in Vermilion's Pokémon Center, map 89. The driver walks independently to the attendant at `(11, 3)`. The participant preparation controller is responsible for reaching this Center and withdrawing a boxed candidate through normal gameplay before exporting the source.

The command-line entry accepts a JSON plan from standard input or `--plan FILE`:

```bash
python -m pokesim.interactions.link_worker --out NEW_OUTPUT_DIRECTORY < plan.json
```

The frozen application dispatches `--link-session` to the same entry point. Managed launches add `--watch-parent` with a plan file and keep an inherited standard-input pipe open. EOF cancels the attempt. A 45-second orphan failsafe terminates a native hang. Progress is emitted as JSON lines. The latest `left.jpg` and `right.jpg` previews are atomically replaced at most ten times per second. Preview progress includes each adventure ID, side, frame, position, and image path. Recording does not accumulate. The output directory must be new. Speed defaults to 1, with 0 available for unrestricted test execution. Step and wall-clock limits are explicit plan fields.

A successful `manifest.json` binds the interaction ID, attempt ID, plan digest, adapter ID, both source hashes, both selected keys, both output hashes, and verification evidence. The manifest is published only after both state files and cartridge saves are flushed and verified. Each participant entry provides `state_path` and `cartridge_save_path`. The coordinator must fence the attempt, stage both results with their owning workers, and durably decide whether to commit. Neither the executor nor its manifest authorizes resumption.

Any exception produces `failure.json` without a success manifest. Partial output files must never be adopted. Reusing an output directory is rejected. A parent must still terminate a stuck native process at its own deadline because Python-level watchdogs cannot interrupt every native failure.

## Why return uses reset and Continue

The original Trade Center has no exit warps. Its object definition has an empty warp table. `TradeCenter_SelectMon` allows both players to select Cancel, which calls `ReturnToCableClubRoom`. It does not leave the room.

The game's `TradeCenter_Trade.tradeCompleted` calls `SavePartyAndDexData` specifically to permit a reset back into the Pokémon Center. `_Joypad` and `TrySoftReset` implement the standard A+B+Start+Select reset combination. The production driver therefore:

1. Requires exactly one completed trade and the post-trade save.
2. Chooses Cancel independently for both players and returns to the Club room.
3. Requires drained transport queues and no pending exchange.
4. Detaches all hooks and restores the parking bytes.
5. Holds the normal reset buttons, releases them, and selects Continue through the original menus.
6. Requires both players to be safely back in the Center with link state cleared.

The result is a normal cartridge save restart, not a coordinate write or a shortcut around trading. The prepared source is at the Center, so the reset preserves the correct return baseline. The result checkpoint is then independently loaded into a fresh emulator without hooks. The save file is separately cold-booted and continued in another fresh emulator.

## Verification and reproduction

See `docs/validation/cable-production-20260915.json` for recorded results. The private cartridge test matrix covers Red/Blue, Red/Red, and Blue/Blue, each with normal and reversed connection roles. It exercises all six outgoing party slots with different selections on each side. The game moves the received Pokémon to the end of the party. Its evolution routine preserves custom nicknames and replaces an unchanged default species name with the evolved species name. Both cases are verified through real cartridge runs. The verifier requires exact conservation of all other party records and all twelve stored boxes.

Synthetic test fixtures prove all four supported trade evolutions, Haunter to Gengar, Kadabra to Alakazam, Machoke to Machamp, and Graveler to Golem. The fixture generator is a test-only tool and writes synthetic records before sessions start. It is never imported by the runtime executor.

Additional tests disable the cable, disconnect one endpoint partway through exchange, use unequal emulator stepping, cancel during a trade, reject changed source hashes and selected identities, reject reused output paths, and fail the final progress consumer before manifest publication. The negative control confirms zero trades and unchanged parties.

```bash
export GAME_DATA_DIR=/path/to/verified/game-data
export POKESIM_CABLE_FIXTURES=/path/to/private/fixtures
export POKESIM_CABLE_ROMS=/path/to/private/roms
python -m pytest -q tests/test_cable_session.py

python tools/qualify_cable_session.py \
  --roms "$POKESIM_CABLE_ROMS" \
  --fixtures "$POKESIM_CABLE_FIXTURES" \
  --out NEW_QUALIFICATION_DIRECTORY
```

Without the two private-resource environment variables, pytest runs the non-ROM unit checks and explicitly skips the cartridge cases. The qualification tool requires `pokered.gbc`, `pokeblue.gbc`, and each edition's `.state` and `.sav` fixture files.

## Boundaries

This is a ROM-level virtual connection, not cycle-accurate emulation of electrical serial hardware. Two emulators live in one temporary process. Other ROM editions and emulator versions fail closed. Link battles, remote serial streaming, and freeform two-player gameplay are outside this adapter.

The executor does not own reservations, participant policy memory, database journaling, recovery decisions, or preparation travel. Those belong to the application coordinator and participant workers. Safe cartridge return is verified here, and resuming autonomous policy after adoption is a separate integration responsibility.

## Managed worker integration

`tools/check_managed_cable.py` and `tests/test_managed_cable_integration.py` exercise two real adventure worker processes and a separate link child. Disposable copies start with a full party and boxed offers. They use ordinary PC menus to prepare different selected individuals, export held sources, run the trade, and independently validate and stage both outputs.

The integration checks duplicate stage, apply, and release calls, restarts one participant while committed and held, restarts both after release, and checks that each incoming individual survives with exactly one journal receipt. A second case damages one staged result, aborts both participants, and verifies the exact prepared parties survive both abort and restart without a committed journal entry.

These checks use authenticated loopback HTTP and require permission to create local sockets. Source fixtures and ROMs remain untouched. The harness copies them into the explicitly named new output directory.

`tools/check_managed_app.py` additionally exercises the actual manager and coordinator with three worker processes. Two selected games complete the trade while the third keeps advancing. An injected participant failure after durable commitment leaves recovery pending. Reopening the manager completes both sides from the preserved results, retains one completed history record, and resumes the unrelated game. The test also checks the latest preview images and unchanged source fixture hashes.
