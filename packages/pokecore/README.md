# PokeSim Core

Shared Pokemon Red, Blue, Yellow, Gold, Silver and Crystal primitives for
simulation and agent research. Core decodes game memory, identifies cartridges,
drives the games' own menus and wraps the pyboy-rs emulator. PokeSim and a
separate agent benchmark both build on it.

The base install uses only Python's standard library. The optional `emulator`
extra adds the pyboy-rs emulator and Pillow.

## Install

Python 3.11 or newer. Core and pyboy-rs are released on GitHub, not PyPI. Pin
each file by its URL and the sha256 from the release's `SHA256SUMS.txt`, so pip
refuses a changed file. First pyboy-rs (pick your platform's wheel from the
[v0.1.6 release](https://github.com/afk-sapien/pyboy-rs/releases/tag/v0.1.6)):

```bash
base=https://github.com/afk-sapien/pyboy-rs/releases/download/v0.1.6
curl -fsSLO "$base/SHA256SUMS.txt"
wheel=pyboy_rs-0.1.6-cp311-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
sha=$(grep " $wheel\$" SHA256SUMS.txt | cut -d' ' -f1)
pip install "pyboy-rs @ $base/$wheel#sha256=$sha"
```

Then Core, with the hash from the
[release's](https://github.com/afk-sapien/PokeSim/releases/tag/pokecore-v0.12.2) `SHA256SUMS.txt`:

```bash
pip install "pokecore[emulator] @ https://github.com/afk-sapien/PokeSim/releases/download/pokecore-v0.12.2/pokecore-0.12.2-py3-none-any.whl#sha256=<sha256>"
```

## Example

Decode without an emulator:

```python
from pokecore.gen1 import read_bag, read_party, read_progress
from pokecore.rom import inspect_rom

identity = inspect_rom("/path/to/pokemon-red.gb")
print(identity.game, identity.sha256, identity.verified)

memory = bytearray(65536)  # or a live emulator's memory
party = read_party(memory)
bag = read_bag(memory)
progress = read_progress(memory)
```

Run an isolated emulator:

```python
from pokecore.emulator import GameBoy
from pokecore.gen1 import read_party

with GameBoy("/path/to/pokemon-red.gb") as game:
    game.tick(1800)
    game.press("start")
    game.tick(8)
    game.release("start")
    game.tick(2)
    image_bytes = game.screenshot()
    state_bytes = game.save()
    party = read_party(game.memory)
```

## What is included

- Cartridges: identify and validate the six clean English cartridges
  (`cartridges`, `rom`)
- Gen 1 readers: party, bag, progress, screen text, cursors, sprites and
  storage (`gen1`, `gen1_ui`), with Yellow mapped onto the Red layout (`yellow`)
- Gen 2 readers: party, boxes, items, player, Pokedex, clock, Day Care and full
  snapshots (`gen2`)
- Save summaries from a cartridge `.sav` with no emulator: badges, Pokedex, party,
  boxes, play time and story stage (`save_summary`, `pokecore summary`)
- Battle power, DV odds and Time Capsule conversion, using the caller's game
  tables (`gen1_battle_power`, `dvs`, `timecapsule`)
- Game data read from the caller's cartridge, with an override map for
  randomizers: species, learnsets, TM and HM learners, wild encounters,
  trainer parties and starters, plus a patcher that writes overrides into a
  copy of the ROM (`romdata`)
- A seeded randomizer with HM softlock checks and share codes (`randomizer`)
- Menu shortcuts for all six games: items, moves, switching, running, PC, mart,
  field moves, dialogue and walking (`shortcuts`)
- Controller helpers (`controls`, `naming`) and trusted setup resets
  (`resets`), never for agents
- Emulator: `Emulator` and `GameBoy` with checkpoints, deterministic clock
  control, memory snapshots and a Gen 1 virtual cable

Core ships no ROMs, game tables, artwork, database, MCP server or model SDK, and
imports neither application. Applications own labels, scoring, agent tools,
budgets and recovery.

## Documentation

- [API contracts](docs/api.md): every public name and its guarantees
- [Menu shortcuts](docs/shortcuts.md): the full shortcut catalog and results
- [Gold, Silver and Crystal](docs/gen2.md): Gen 2 readers and snapshots
- [Emulator interface](docs/emulator.md): saves, checkpoints, snapshots, native decoder
- [Real-time clock](docs/rtc.md): clock files, locking and checkpoints
- [Execution procedures](EXECUTION.rst) and
  [action and compatibility procedures](COMPATIBILITY.rst)
- [Validation records](docs/consolidation-validation.md) and
  [changelog](CHANGELOG.md)

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv build
```

Tests use synthetic memory and a fake emulator. CI runs without ROMs, PyBoy,
model API keys or paid services. Real cartridge checks run locally with
user-supplied files, and their artifacts are never committed. Emulator tests
need a pyboy-rs wheel installed (`pip install -e ".[dev]" pillow numpy`, then the
wheel). Build one with `maturin build --release`, not `maturin develop`.

## License

MIT, see [LICENSE](LICENSE). Adapted code and the pret disassembly references
are credited in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The emulator
extra installs pyboy-rs, which is LGPL-3.0-only.
