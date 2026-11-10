# Emulator interface

The `emulator` extra installs pyboy-rs, Core's only emulator backend. Only Core
imports the native package. Applications import Core.

## Emulator

`Emulator` owns isolated machine operations, memory and register wrappers,
RGBA output, signed 8-bit stereo audio, hooks, and explicit cartridge export.
It has no application thread, automatic file writes or agent policy. Memory
writes and hooks are trusted host APIs. Applications decide which observations
and actions their agents can access.

- `press` and `release` queue the input. It reaches the machine at the start of
  the next `tick`, so a raw `save()` between `press` and `tick` does not contain
  the press. `checkpoint()` stores the queue as `pending_inputs`, and
  `restore_checkpoint` restores it.
- Batched `tick` advances exactly the requested positive number of frames and
  renders and samples its last frame. Tick one frame at a time for continuous
  media.
- Output views are read-only and change on the next tick or state load. Use
  bytes to keep a snapshot. Image encoding imports Pillow lazily. NumPy views
  need NumPy installed by the caller.
- Hooks are owned by the caller and must be registered on a fresh machine before
  resuming instrumented execution.
- Real-time clock control is described in [rtc.md](rtc.md).

## Saves and checkpoints

Raw `save` and `load` keep PyBoy format-15 compatibility. They exclude pending
controller operations and keep the caller's current pending queue. A failed
state load leaves the machine unchanged.

`checkpoint` and `restore_checkpoint` also keep pending inputs and frame counts
and validate the ROM, settings and native build. Manifests identify pyboy-rs
with its version, state format and native extension and binding hashes.

`restore_checkpoint(checkpoint, match="version")` compares the backend, its
version and the state format, so a wheel rebuilt in CI or built for another
operating system restores checkpoints of the same version. `match="exact"` also
requires the identical binary and binding hashes. `match="state_format"`
accepts any version of the same backend and format.

`checkpoint()`, `checkpoint_metadata()` and `retag_checkpoint()` keep
`pyboy_version: "2.7.0"` beside the `emulator` record exactly when PyBoy 2.7.0
could load the saved state: a format-15 raw state from that lineage with no
clock lock carried. Consumers that require the field refuse checkpoints without
it, which includes every checkpoint saved with a locked clock.

`emulator_state` owns runtime fingerprints and the import rules for older
checkpoint formats. `checkpoint_audio` converts silent legacy checkpoints.
Ordinary imports accept PyBoy 2.7.0 format-15 saves. Trade outputs keep an
explicit source-to-output runtime migration record.

## GameBoy adapter

`GameBoy` wraps `Emulator` for verified English Red and Blue ROMs. Narrow the
accepted games with `allowed_games=("red",)`. Each instance uses fresh
in-memory SRAM and never reads or writes save files next to the ROM. Nothing
advances until `tick` is called. There is no background loop, autoplayer,
navigation, recovery or memory editing helper.

`GameBoy.load` restores a trusted state. The caller owns state provenance and
compatibility checks. The memory view and `load` are trusted application APIs.
Do not expose them directly to an agent. This library is not a sandbox.

## Per-step memory snapshot

```python
from pokecore.emulator import Emulator
from pokecore.memory_snapshot import snapshot_emulator

game = snapshot_emulator(Emulator)("/path/to/crystal.gbc", sound_emulated=False)
```

The returned class has the same constructor and API. Between two steps its
`memory` serves reads from a lazy copy:

- Banked WRAM and cartridge RAM reads come from one `read_bank_bytes` call per
  bank, served natively by pyboy-rs builds with the `bank_bytes` feature and by
  per-byte bank reads otherwise. `memory.snapshot_window(bank, address, size)`
  returns the cached bytes or None. The Gen II readers and
  `storage.memory_bytes` use it automatically.
- Unbanked reads inside `0xC000-0xDFFF` (`memory[address]`,
  `memory[start:stop]` and `memory.read_bytes`) come from one copy of that
  range, so the Gen I readers and `snapshot.read_fields` use it unchanged.

Every tick, memory write, state load, checkpoint restore, input and every other
method outside `memory_snapshot.READ_ONLY` invalidates the copy. Reads made
during a call, for example from a hook, go to the live machine. On a Crystal
save a full `gen2.read_snapshot` takes about 0.13 ms with the snapshot and
region cache, against about 0.67 ms on live memory.

`Emulator.memory.read_bank_bytes(bank, start, stop)` is also available on the
plain emulator.

## Gen 1 virtual cable

`gen1_cable.CableEndpoint` owns the verified ROM-hook transport, queues,
register parking and hook cleanup. Applications own participants, navigation,
time budgets, persistence and transaction adoption.

`gen1_cable.CableDriver(sides, plan, progress=None, cancelled=None, *, walk=None,
snapshot=None)` presses the controller buttons of one Red, Blue or Yellow trade:
`enter` walks both trainers to their Cable Club attendants and into the club,
`exchange` offers each side's `party_slot`, `leave` saves and walks out, and
`return_to_center` confirms a Continue prompt after a restart. `plan` needs
`max_steps`, `timeout_seconds` and `speed` (0 runs unpaced). `enter` records the
Center each side starts in as `source_center_map` and refuses to start anywhere else.
Progress is reported under each side's `label`. Route finding stays with the caller: `walk(side, snapshot, target)`
returns the next button toward `target` (map, x, y). Without `walk` the driver raises
`CableError` as soon as a trainer has to move. `snapshot(side)` defaults to
`centers.location(side.pb.memory)`.

`centers` holds the Centers a cable session can start from:

- `CENTERS` maps each map ID with a Cable Club attendant to its `name`, its `pc` tile
  and its `rendezvous` tile in front of the attendant. The Celadon hotel is left out.
- `location(memory)` reads the map, position, battle flags, `textbox` and
  `start_menu` from Red-layout memory. `valid` is a table-free check (a real map ID, a
  playtime clock below 60, party levels and HP in range) and `started` is true once
  there is a map, playtime or a party.
- `safe_center(snapshot, map_id, memory)` is true only in the loaded overworld of
  Center `map_id`, with no battle, text box, menu, naming keyboard or quantity prompt,
  and not on the Continue screen that shows the save just loaded.
- `screen(memory)` gives the raw screen `rows`, whole-word `text`, the `cursor` and the
  top menu corner.

## Experimental native decoder

The separate, unpublished `pokesim-core-native` distribution in `native/` uses
PyO3 and Maturin to decode a complete WRAM snapshot in one native call. It is
optional and not part of the `pokecore` metadata. Core uses it
automatically when it is installed. CI builds and tests it in its own job.

```bash
maturin build --release --manifest-path native/Cargo.toml --out dist
pip install dist/pokesim_core_native-*.whl
POKESIM_CORE_DECODER=rust pytest
```

`POKESIM_CORE_DECODER=auto` (the default) uses the native decoder when
installed and Python otherwise. Set it to `python` for the reference decoder or
`rust` to require the extension. Invalid modes, an incompatible native API and
native decoder errors fail explicitly.

- `pokecore.snapshot.read_fields(memory, move_data=None)` returns fresh
  snapshot fields, including party dictionaries. It never advances the emulator
  or reads banked storage. Call it on the emulator's owning thread between
  steps.
- `Memory.read_bytes(start, stop)` returns detached bytes.
- `Emulator.tick_read(frames, start, stop, render=True, sound=True)` is an
  experimental combined advance and byte read. It keeps pending inputs, hooks,
  frame counts and media refresh, and collects bytes after the final frame.
  Invalid ranges fail before advancing. Bindings without it fall back to
  separate operations.
- `pokecore.identity.pokemon_identity(trainer_id, dvs)` computes Pokemon
  signatures with a bounded cache of immutable integer inputs.
