# Tools

Commands for checking, releasing and running PokeSim. Run each one from the repository root, for
example `uv run --locked python tools/check_docs.py`. Every tool prints its arguments with `--help`.

Replays, bisects, stall hunts and soak runs share one harness, `python -m pokesim.replay`. Its
subcommands are `record`, `diverge`, `bisect`, `capture`, `find-stalls`, `stuck-scenarios`, `audit`,
`check-endurance`, `validate-progress`, `progress`, `play-gen2`, `profile-simulation`, `soak-release`
and `summarize-soak`.

## Checks

| Tool | Purpose |
| --- | --- |
| `preflight.py` | Run the local checks a bot behaviour pull request needs, and post the result on its commit |
| `check_docs.py` | Check local Markdown link destinations without network access |
| `check_web.py` | Check every browser script and run all Node browser tests |
| `check_install.py` | Check the built packages, the installers and an installed PokeSim outside the checkout |
| `check_container.py` | Check the container image, the Docker quick start and a first run in an empty library |
| `smoke_server.sh` | Start PokeSim in a throwaway data directory and run `pokesim smoke` against it |
| `verify_cartridge.py` | Exercise real cartridges, cable sessions and Gen II saves on disposable copies |
| `map_audit.py` | Audit the Gen II map facts the route planners trust |
| `check_gen2_ice.py` | List which warps of every Gen II ice map can be reached from which |
| `benchmark_decisions.py` | Benchmark identical decision inputs and verify fixed-frame gameplay traces |
| `audio_jitter_harness.py` | Measure live-audio gaps in a real browser through a delaying, jittery proxy |
| `stylelint/` | Shared breakpoints and plugins for the stylesheet check |

## Tests

| Tool | Purpose |
| --- | --- |
| `load_gate.sh` | Share the machine's test and play slots between local agents and the nightly watch |
| `nightly_tests.sh` | Run the whole suite on a fresh `origin/main` with the private replays and slow tests on |
| `stage_ladder.py` | Keep a save for each stage of the game and gate a change on replaying them all |
| `ladder/` | The ladder gate's baseline |
| `record_durations.py` | Record each test module's run time into `tests/durations.json` |
| `flake_rate.py` | Count how often a push run on main failed once and passed on a rerun |

## Releases

| Tool | Purpose |
| --- | --- |
| `release.py` | Check and prepare a PokeSim or pokecore release, one subcommand per step. The [release guide](../docs/publishing.md) gives the order |
| `bundle_dependency_sources.py` | Keep installed dependency notices and the matching Rust emulator source |

## Game data

| Tool | Purpose |
| --- | --- |
| `gen1_gates.py` | Generate the Gen I gate table from a pret/pokered or pret/pokeyellow checkout |
| `gen1_map_facts.py` | Generate the Gen I map facts from the same checkouts |
| `gen2_map_facts.py` | Generate the Gen II map facts from pret/pokecrystal and pret/pokegold checkouts |
| `prepare_gen2_test_data.py` | Generate the Gen II game data the regression tests read |

## Running and watching

| Tool | Purpose |
| --- | --- |
| `deploy_host.sh` | Build one commit into an image and deploy it to the managed app on a Docker host |
| `live_soak.py` | Gate a deploy on a copy of the live adventures |
| `local_sims.sh` | Run the dev instance and temporary sims inside the capped PokeSim user slices |
| `maintain.py` | Offline maintenance for stopped, backed-up PokeSim data |
| `observe_adventures.py` | Record one read-only observation of a running adventure library |
| `overnight_watch.sh` | Nightly watch of the real-cartridge tests, the private saves and the hosted app |
| `install_watch.sh` | Install the overnight and alert watches as systemd user units |
| `alert_watch.py`, `alert_watch.sh` | Turn each new main-page alert of a hosted app into a task |
| `quality_hunt_watch.py` | Check that a Gen II adventure goes back to better-DV hunts once its training runs out |
