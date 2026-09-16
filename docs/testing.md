# Validation guide

Start with [Contributing](../CONTRIBUTING.md) for dependency and reference-data setup.
Use focused scenarios while editing and the full suite before a release.
See the [rc31 cleanup results](validation/cleanup-0.2.0rc31.json) for the recorded
local checks, copied-save comparisons, and their limits.

## Python and browser logic

```sh
uv run --locked --extra dev pytest --ignore=tests/test_rom.py -q
uv run --locked python tools/check_web.py
uv run --locked python tools/check_docs.py
```

The default suite skips the opt-in real-browser tests. The Node tests check isolated
browser logic. Lifecycle tests cover final-save failure, startup cleanup, process locks,
shutdown timeout, and the distinct behavior of restore, resume, restart, and trade holds.

## Real Chromium flows

Install the optional browser dependency and its browser binary:

```sh
uv sync --locked --extra dev --extra browser-test
uv run --locked --extra browser-test python -m playwright install chromium
POKESIM_BROWSER_TESTS=1 uv run --locked --extra dev --extra browser-test pytest tests/browser -q
```

On Linux CI, the installation command adds `--with-deps` for browser system libraries.
See [Playwright installation](https://playwright.dev/python/docs/library#installation).
For PowerShell, set `$env:POKESIM_BROWSER_TESTS = "1"` before running pytest.

The tests launch real Chromium against temporary localhost servers. Actual application
HTML, scripts, routes, and SQLite preference writes are exercised. Synthetic cartridge
state replaces the emulator boundary, so CI needs no Pokémon ROM. Coverage includes:

- Desktop file validation, starter selection, setup failure, retry, and quit.
- PC locks persisted across refresh at desktop and mobile widths.
- Disconnected trading, offer withdrawal, and view-only controls.
- A trade hold beginning after an event page loads, rejected rewind feedback, and retry.

Browser traces are written into each test's temporary directory. CI retains them on
failure. These scenarios do not establish native packaging or actual cartridge playback.

## ROM integration

Using your own supported ROM:

```sh
uv run --locked --extra dev pytest tests/test_rom.py -q
```

This checks boot, repeatable opening behavior, and all three starter choices. Do not
upload ROMs, save files, or private traces as CI artifacts.

## Compare longer copied-save runs

`tools/check_endurance.py` runs the existing checkpoint validator in child processes.
It defaults to two hours of game time per run, with a 30-minute wall-clock timeout.
It records progress, policy recoveries, project gains, and event gaps. Ten-game-minute
samples separate preparation from active training. Inputs are hashed before and after.

Prepare an isolated baseline from a reviewed commit, then compare the same copied
checkpoint under the baseline and current source:

```sh
mkdir -p /tmp/pokesim-baseline
git archive BASELINE_COMMIT | tar -x -C /tmp/pokesim-baseline
uv run --locked python tools/check_endurance.py \
  --rom roms/pokered.gb \
  --checkpoint data/private-reproduction/checkpoint.state \
  --baseline /tmp/pokesim-baseline \
  --frames 432000 \
  --require-equivalent \
  --output data/operations/refactor-comparison
```

Replace the commit and private checkpoint paths. The matching JSON manifest is required.
The output directory must be new. The tool never needs the running deployment's data
directory. Keep full reports private and commit only reviewed, sanitized summaries.

`--require-equivalent` fails on changed inventory, achievements, project outcomes,
recovery counts, or other compared behavior. Omit it for intentional gameplay changes
and inspect `changed_fields`. Fingerprints and wall time can differ without failing an
otherwise identical refactor comparison. An event gap can contain productive XP gains,
so inspect training samples before classifying it as a stall.

Game-time replays are regression checks. They do not prove 24-hour or week-long process
reliability. Use the existing isolated container checks in `tools/soak_release.py` and
[monitoring runbook](operations-monitor.md) for wall-clock endurance, resource growth,
viewer load, and process continuity.

## Build identity and packages

`/api/state` and `/desktop/status` include `build.version`, `build.revision`, and
`build.dirty`. Source checkouts report their Git revision and whether the tree is dirty.
Wheels, source distributions, and desktop bundles retain a build-time identity.
A missing revision or unknown dirty state is represented as `null`.

```sh
uv build
uv run --locked python tools/check_package.py
```

For source container builds, supply the reviewed revision explicitly:

```sh
POKESIM_REVISION=$(git rev-parse HEAD) docker compose -f compose.yaml -f compose.build.yaml build
```

The release workflow supplies the revision automatically. Containers report an unknown
dirty state because a revision argument alone cannot prove a clean build context.
The package check verifies embedded version metadata and required runtime resources.
