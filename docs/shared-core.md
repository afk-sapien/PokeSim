# Shared game core

PokeSim Core is the Python package shared by PokeSim and PokeAgent Bench. Its
distribution and import name is `pokecore`. Its source lives in this repository in
[`packages/pokecore`](../packages/pokecore), merged with its full history from the
[pokesim-core repository](https://github.com/afk-sapien/pokesim-core), which stays
archived as the readable history before the move. Core 0.9.0 dropped the old
`pokesim-core` distribution and the `pokesim_core` import name.

PokeSim uses `pokecore.gen1` for Red, Blue and Yellow WRAM addresses, text and numeric
decoding, individual Pokémon fields, party reads, and bag reads. Its known ROM
hashes come from `pokecore.rom`. `pokecore.dvs` supplies the reusable
DV-total probability reference model, with training and retention policy in PokeSim.
`pokecore.gen2` supplies the Gold, Silver and Crystal memory map and verified
cartridge hooks. Yellow reads the Red addresses through the translating view in
`pokesim/yellow.py`.

Core also owns cached screen glyphs, immutable box decoding, resumable name
entry, linear menu selection and explicit flag-update mechanics. PokeSim keeps
its name pools, step thresholds, reward claims and route decisions. The benchmark
uses Core's bounded item-use and party-switch macros through its existing
recorded, budgeted controller. Its observation policy stays in the benchmark.

The existing `pokesim.ram` imports remain compatible. It re-exports shared
constants and helpers, wraps decoded party dictionaries in `PartyMon`, and
builds the same `Snapshot` objects. Species names and move PP data still come
from PokeSim's user-provided game data. Derived state,
gameplay policies, recovery, trading, and the application UI remain in PokeSim.
Every adventure runs on Core's emulator adapter (`pokecore.emulator`) over PyBoy RS.

## Where fixes belong

Fix shared ROM facts and memory decoding in `packages/pokecore`, with regression
coverage in `packages/pokecore/tests`. PokeSim's compatibility tests check the boundary between those
shared values and its existing application types. Keep gameplay decisions, Power
ranking, UI copy, trading, and save recovery in PokeSim.

Mechanical actions belong in Core when another consumer would otherwise have to
repeat the same button sequence. Current APIs include `use_item`,
`switch_pokemon`, `name_step` and `enter_name`. Item macros currently support
restorative items with one party target, not TMs, balls or per-move PP items.

Trusted event resets are a separate API. `reset_encounter` and `reset_events`
require caller-supplied cartridge definitions and reject visibly unsafe contexts.
PokeSim uses `update_flags` after its existing scheduling and unloaded-room
checks. It preserves durable claim history and never resets a game simply
because Core offers a reset function. Benchmark agents never receive these APIs.

Other projects pin a released pokecore wheel. A Core change reaches them only through a
pokecore release and a reviewed pin update in each project.

## Installing and updating

`[tool.uv.sources]` in `pyproject.toml` makes `pokecore` a workspace member. A
checkout and the container build install it from
`packages/pokecore`, and `uv.lock` records no wheel for it. A Core change is live
in PokeSim on the next `uv sync`, with no release.

pip and pipx users install the PokeSim wheel, whose metadata keeps the
`pokecore` dependency as a versioned GitHub release wheel with its SHA256 hash.
`tools/check_release_pins.py` fails when that pin names another version than
`packages/pokecore/pyproject.toml`. With `--remote` it also downloads the wheel
and fails when its files differ from the workspace source. So a PokeSim release
that ships a Core change needs a pokecore release of the same source first.

Test a Core change from the checkout:

```sh
uv sync --locked --extra dev
(cd packages/pokecore && uv run pytest -q)
uv run --locked pytest tests/test_shared_core.py -q
uv run --locked python tools/check_docs.py
```
