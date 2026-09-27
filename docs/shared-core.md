# Shared game core

[PokiSim Core](https://github.com/afk-sapien/pokisim-core) is the Python package
shared by PokeSim and PokeAgent Bench. Its distribution name is `pokisim-core`
and its import name is `pokisim_core`.

PokeSim uses `pokisim_core.gen1` for Red and Blue WRAM addresses, text and numeric
decoding, individual Pokémon fields, party reads, and bag reads. Its known ROM
hashes come from `pokisim_core.rom`.

The existing `pokesim.ram` imports remain compatible. It re-exports shared
constants and helpers, wraps decoded party dictionaries in `PartyMon`, and
builds the same `Snapshot` objects. Species names and move PP data still come
from PokeSim's user-provided game data. Storage bank handling, derived state,
gameplay policies, recovery, trading, and the application UI remain in PokeSim.
PokeSim retains its existing emulator runtime for those application behaviors.
The benchmark can use the core's optional emulator adapter independently.

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
uv pip install --python /tmp/pokesim-core-dev/bin/python --reinstall -e ../pokisim-core
/tmp/pokesim-core-dev/bin/python -m pytest tests/test_shared_core.py -q
```

Keep local editable overrides out of committed dependency files. Promote a
core update only after compatibility checks pass in both consuming projects.
