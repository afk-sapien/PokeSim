# Contributing to PokeSim

Original code is MIT licensed. Keep changes focused and describe the problem, resulting
behavior, and validation in each pull request. Start with the
[documentation index](docs/README.md) and [module boundaries](docs/architecture.md).

## Development setup

Use Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), Git, and Node.js 22 for browser
checks. From the repository root:

```sh
uv sync --locked --extra dev
git clone https://github.com/pret/pokered .reference/pokered
git -C .reference/pokered checkout a1a22aaf84d1675bcdbaeb194592379d586d838e
uv run --locked python -m pokesim.prepare_data .reference/pokered
```

Reference preparation writes local game data for tests and native runs. It does not
create a ROM. For an existing reference checkout, skip cloning and verify its revision.
See [desktop development](docs/desktop.md#build-a-standalone-application) for bundling
and native launcher checks.

## Checks before a pull request

```sh
uv run --locked pytest --ignore=tests/test_rom.py -q
uv run --locked python tools/check_web.py
uv run --locked python tools/check_docs.py
uv build
uv run --locked python tools/check_package.py
```

`check_web.py` checks every packaged browser script and runs every `tests/*.test.cjs`
file. `check_docs.py` checks local Markdown link destinations. CI runs the same checks.
Run focused tests while editing, then the full suite for changes to shared behavior.

Optional ROM integration tests use your own supported ROM:

```sh
uv run --locked pytest tests/test_rom.py -q
```

Never add ROMs, cartridge saves, portrait packs, private traces, or generated game data
to source control, CI artifacts, or issues. Use synthetic states or private copied
checkpoints for policy scenarios.

## Repository map

| Path | Responsibility |
| --- | --- |
| `pokesim/` | Emulator, persistence, game data, and desktop entry points |
| `pokesim/policies/` | Gameplay decisions and project planning |
| `pokesim/web/` | HTTP routes, presentation helpers, and browser assets |
| `pokesim/trade/`, `pokesim/broker/` | Checkpoint exchanges, coordination, and inventory matching |
| `tests/` | Python scenarios and Node browser tests |
| `tools/` | Data preparation, validation, replay, and packaging commands |
| `deploy/`, `compose*.yaml` | Server deployment examples |
| `docs/` | Current guides, plans, and indexed historical evidence |

`data/`, `roms/`, `.reference/`, `.release-local/`, `build/`, and `dist/` are local working
artifacts excluded from Git. Some contain irreplaceable saves or private reproductions.
Do not treat them all as disposable caches.

## Compatibility and documentation

Save-format changes need a format version, upgrade and rollback notes, and a recovery
test. PyBoy is pinned deliberately. Test existing checkpoints before upgrading it.
Use `uv lock --upgrade-package PACKAGE` for an intentional dependency update, then rerun
affected checks and the container build.

Generated data must retain its upstream revision and generator command. See the
[feature guide](docs/guide.md#generated-game-data) and
[third-party notices](THIRD_PARTY_NOTICES.md).

Update the owning guide when behavior changes and add user-visible changes to
[CHANGELOG.md](CHANGELOG.md). Keep future work in the roadmap and deployment details
in validation receipts. Review `docs/release-notes.md` for the exact tag before publishing.

Bug reports should include the release or commit, operating system and CPU architecture,
ROM hash, sanitized settings and logs, and reproduction steps. Omit tokens and private
save files. Use [private reporting](SECURITY.md) for security issues.
