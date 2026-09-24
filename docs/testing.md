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
uvx ruff==0.16.9 check pokesim tests tools
```

Ruff runs the Pyflakes checks only: unused names, undefined names and names used before
they are assigned. It does not restyle the code.

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

## Stuck scenarios

A stuck scenario is a saved moment the player once could not get out of, replayed as a
regression test. It passes when the player achieves something again within its budget.
Scenarios hold private game data, so they live under `data/scenarios` or a folder named by
`POKESIM_SCENARIOS`, never in the repository.

Stalls come from two places, in the same layout. A running adventure keeps the last
`KEEP_STALL_BUNDLES` (default 5) in its `stalls/` folder: `noticed.state` from the moment the
stall was reported and `before.state`, the first autosave after the last achievement.
`tools/find_stalls.py` plays an isolated adventure at full speed and writes the same bundles.

```sh
uv run --locked python tools/find_stalls.py --rom roms/pokered.gb --output data/operations/stall-hunt/run-1 --until-champion
uv run --locked python tools/stuck_scenarios.py add seafoam-boulders data/operations/stall-hunt/run-1/stall-01
uv run --locked python tools/stuck_scenarios.py run
POKESIM_SCENARIO_TESTS=1 uv run --locked --extra dev pytest tests/test_scenarios.py -q
```

`add` also edits the copied save into a situation that is hard to reach by playing:

```sh
uv run --locked python tools/stuck_scenarios.py add league-everyone-frozen league-entry.state \
  --party all:status=frozen --item FULL_RESTORE=0 --item REVIVE=0 \
  --fallback league-entry.state --until champion --budget 300
```

`--party` takes a slot or `all` with `status`, `hp` (a number, or a share such as `0.25`) and
`pp`. `--item NAME=0` removes an item and `--money` sets the wallet. Edits are applied each time
the scenario loads, so the copied save stays as it was. When a battle runs past its timeout, or
the player reports that it cannot end, the runner reloads the scenario as the application
reloads an autosave. The second reload goes to the unedited `--fallback` save, as the
application restarts a League attempt from its entry save. `show` prints the party, bag and
place a scenario starts from.

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

## Distribution installation checks

On Linux, build both packages and install the wheel in a fresh temporary environment:

```sh
uv build
uv run --locked python tools/check_package.py
uv run --locked python tools/check_installed_wheel.py
```

The wheel check runs outside the repository and resolves the wheel's declared
dependencies. It tests the installed launcher, setup assets, duplicate launch, and
protected shutdown. It needs uv and access to the package index.

Native runtime checks use PyBoy's demonstration ROM and verified reference data. They do not
validate Pokémon cartridge playback on that platform.

For an isolated server installation test:

```sh
docker build -t pokesim:check .
uv run --locked python tools/check_container.py pokesim:check
```

The test creates a uniquely named Compose project, disposable named volume, and
random localhost port. It uses only PyBoy's demo ROM, downloads verified reference
data, checks HTTP health, stops cleanly, verifies saved checkpoint hashes, and
restarts from a checkpoint. It removes only its test project and volume afterward.
It does not touch an existing adventure or establish autonomous campaign progress.

## Publishing a complete release

Choose a new version, update package metadata and release notes, and tag the reviewed
commit. Run **Publish public release** with that existing tag from a branch containing
the updated workflow. All five desktop targets must pass before publication continues.
Every package must carry the same version and clean source revision. The final
manifest and `SHA256SUMS` cover desktop, container, Python, and configuration assets.

Publishing a GitHub release starts the workflow, which uploads the downloads and
checks every uploaded digest. An interrupted upload or verification failure leaves
the release with incomplete assets. Rerun the workflow manually for the same tag.
The preflight rejects a release whose downloads are already attached. Never replace
a completed release. Release candidates are marked prerelease based on the `rc` version suffix.

Publication does not merge the public default branch or upgrade any deployment.
Keep the public installation page aligned with the newly published version, and
verify downloads anonymously before announcing it.
