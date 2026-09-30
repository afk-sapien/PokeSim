# Shared game core

[PokeSim Core](https://github.com/afk-sapien/pokesim-core) is the Python package
shared by PokeSim and PokeAgent Bench. Its distribution name is `pokesim-core`
and its import name is `pokesim_core`.

PokeSim uses `pokesim_core.gen1` for Red and Blue WRAM addresses, text and numeric
decoding, individual Pokémon fields, party reads, and bag reads. Its known ROM
hashes come from `pokesim_core.rom`. `pokesim_core.dvs` supplies the reusable
DV-total probability reference model, with training and retention policy in PokeSim.

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
PokeSim retains its existing emulator runtime for those application behaviors.
The benchmark can use the core's optional emulator adapter independently.

## Where fixes belong

Fix shared ROM facts and memory decoding in the Core repository, with regression
coverage there. PokeSim's compatibility tests check the boundary between those
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

PokeSim pins Core 0.1.4. Each consumer records its reviewed dependency version. Publish a compatible Core release, then
update and validate each consumer's dependency pin. Core improvements reach both
applications through those reviewed package updates.

## Installing and updating

Normal PokeSim installation installs the shared package automatically.
The dependency in `pyproject.toml` references a versioned GitHub release wheel
with its SHA256 hash. `uv.lock` also records the artifact hash. A wheel works
with the existing container build and hash-checked dependency export without
requiring Git during installation.

To update the core, release and validate it first, replace the dependency URL
and SHA256 hash, and run `uv lock`. Review the lockfile changes and run:

```sh
uv sync --locked --extra dev
uv run --locked pytest --ignore=tests/test_rom.py -q
uv run --locked python tools/check_docs.py
uv build
uv run --locked python tools/check_package.py
```

Use a separate development environment to test an unpublished core checkout:

```sh
uv venv /tmp/pokesim-core-dev
uv pip install --python /tmp/pokesim-core-dev/bin/python -e '.[dev]'
uv pip install --python /tmp/pokesim-core-dev/bin/python --reinstall -e ../pokesim-core
/tmp/pokesim-core-dev/bin/python -m pytest tests/test_shared_core.py -q
```

Keep local editable overrides out of committed dependency files. Promote a
core update only after compatibility checks pass in both consuming projects.
