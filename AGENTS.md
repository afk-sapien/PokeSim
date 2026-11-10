# Project rules

## Project identity

All agents and automation acting on the owner's behalf must use only this
identity for this project:

- GitHub account and Git author/committer name: `afk-sapien`
- Git author/committer email: `327645577+afk-sapien@users.noreply.github.com`

Never use a work account, a work email, another saved login, or an agent's
suggested co-author identity for this work. This applies to commits, tags,
co-author and sign-off trailers, pull requests, merges, releases, issues,
comments, package publication, and other authenticated project operations.
Preserve legitimate third-party attribution in upstream code and history.

### Every checkout, clone, and worktree

These rules also apply to temporary clones, isolated checkouts, worktrees,
subprojects, and delegated work, regardless of their filesystem location.
A fresh clone does not inherit the source checkout's local Git configuration.
Before creating commits or tags in each checkout, set repository-local values:

```sh
git config --local user.name afk-sapien
git config --local user.email 327645577+afk-sapien@users.noreply.github.com
git config --local user.useConfigOnly true
```

Verify the effective identity with both `git var GIT_AUTHOR_IDENT` and
`git var GIT_COMMITTER_IDENT`. Both must have the exact name and email above.
Check for environment variables, command options, and worktree configuration
that override local settings. Recheck after changing checkouts or execution
environments. Do not change global Git identity or the global active login.
Other projects may intentionally use a different account.

### Authentication and publication

Git authorship and service authentication are separate checks. Before any
authenticated project operation, verify the actual account used by that CLI,
connector, browser, credential helper, or API client is `afk-sapien`. For GitHub
CLI, `gh api user --jq .login` must return `afk-sapien`. Ensure Git pushes use
that same verified account. A repository URL, a successful push, or a
`github.account` setting alone does not prove the effective identity.
Use credentials scoped to this repository or operation. Never print tokens.

If the required account is unavailable or either identity check fails, stop
the authenticated or history-writing operation and report the mismatch.
Never fall back to another saved account or bypass a project identity guard.

Before pushing, inspect every new commit's author, committer, and attribution
trailers. Before merging or publishing, inspect the final merge or squash
message and tag attribution too. Correct unintended identities before they
become public. Pass these rules explicitly to delegated agents and temporary
checkouts that might not load this file automatically.

## Project conventions

- Never use em dashes or semicolons in authored output.
- Pull requests do not edit `CHANGELOG.md`. Say in the description what a user sees. The release pull request writes the version's changelog section from the pull requests merged since the last tag, as [the release guide](docs/publishing.md#the-changelog) says.

## pokecore

- `pokecore` lives in `packages/pokecore` as a uv workspace member. A checkout, the dev instance and the container build all run that source, so a change there is live on the next sync.
- pip users and other projects get pokecore only from a pokecore release. `tools/check_release_pins.py` fails when the URL pin in `pyproject.toml` names another version than `packages/pokecore`, so bump the member version and cut its release with the PokeSim release that ships the change.
- Run its suite from `packages/pokecore` with `uv run pytest -q`. It keeps its own ruff settings, at the root's ruff version.

## Local runs

- All local PokeSim work shares `pokesim.slice`, capped at 12 cores and 22G. Install the slices once per machine with `sh tools/local_sims.sh install`.
- Run one heavy job at a time under `tools/load_gate.sh`, at most `pytest -n 12`. The gate runs every command at nice 10 or lower priority, in `pokesim-tests.slice` (10G), whose CPU weight beats the sims.
- Before a PR, run locally only lint and the tests for the files you touched. The full suite runs in CI only, so do not repeat it locally. A pull request tests Python 3.12 on Linux x86, and tags, the nightly run and manual runs test every Python and platform.
- Tests marked `slow` skip unless `POKESIM_SLOW_TESTS=1`. The local nightly run sets it. It runs the whole suite with the private replays on a fresh origin/main, in its own clone, under the load gate's heavy lock.
- Install the local nightly once per machine with `bash tools/nightly_tests.sh install`, then `systemctl --user daemon-reload && systemctl --user enable --now pokesim-nightly.timer`. It runs at 02:00 in `pokesim-tests.slice` and waits for the heavy lock when another heavy job holds it. The first line of `~/.local/state/pokesim-nightly/<date>.txt` says whether anything beyond the known replay failures failed.
- A new failure, a broken run or a timeout hands that line to `POKESIM_NIGHTLY_NOTIFY_COMMAND` from the nightly settings file. A night with only the known failures sends nothing. Turn the nightly off with `systemctl --user disable --now pokesim-nightly.timer`.
- Merge with `gh pr merge <n> --auto --squash --match-head-commit <sha>`, which merges once the required gates pass, in place of a polling watcher. Start the next PR while CI runs, on top of the first one when it depends on it.
- After a test module's run time changes a lot, rewrite `tests/durations.json` with `python tools/record_durations.py` from the JUnit reports a CI run uploads, so the browser and Windows shards stay balanced.
- A behaviour PR, one that changes bot, planner, policy, strategy, battle, overworld or game loop code, runs `uv run --locked --extra dev python tools/preflight.py <cartridge folder>` on its pushed head before it merges. It plays the ladder gate and every private replay, as `REPLAYS=1` does, in about 10 minutes, and posts the `preflight` commit status. Storage, UI, tooling and docs changes skip it.
- A replay that also fails on main goes into `known-failures.txt` in the scenarios folder once, and the work goes on. Do not rerun it to prove it.
- Every release runs `tools/stage_ladder.py gate` before the release soak, and a release with a gate failure does not ship. The gate takes the load gate's heavy lock on its own, so never wrap it in a `flock` of those lock files or a script that takes them. A gate inside its own lock waits forever.
- Run every long local job in the background under `timeout`, and look at it when it runs past twice its usual time. A full gate takes about 3 minutes, so run it under `timeout 30m`. A job at 0% CPU for that long is stuck, so report it.
- For a behavior change, the gate replaces long full-sim batches. Run full-sim batches only when the change targets late-game play the 30 game minutes from each rung cannot reach.
- The gate baseline is the tracked `tools/ladder/gate-baseline.json`. It moves only in a pull request that names the behaviour change that justifies it. Take it with `--write-baseline` on a branch of current main, and keep any rung it makes worse on record in a dated list beside it before the move, as `tools/ladder/regressions-suspected-20261109.md` does.
- A deploy needs a passing `tools/live_soak.py smoke --candidate <commit>`. It boots every soak save, plays 5 game minutes, saves, reloads and fails on any error log line, in about 3 minutes under the heavy lock. The two game hour `run` comparison only reports and never blocks a deploy.
- The hosted app is for viewing and playing. Tests, soaks and temporary sims, such as fresh games for a stall hunt, run locally, never on the hosted app.
- A temporary sim runs as one long-lived local app with its own data root, outside the checkout and the live soak root, in `pokesim-sims.slice` (12G), started with `sh tools/local_sims.sh start <unit> <env> <code> <data> <port> <revision>`. That runs it at nice 19 with `AUTH=none` on 127.0.0.1. Turn auto trading off for each adventure and add no notification integration. Soaks and pytest stay the one heavy job and win the CPU.

## Gen 1 vs Gen 2 parity

- A new field in the live state, statistics or activity ledger payload must be filled for Red, Blue and Yellow and for Gold, Silver and Crystal.
- If one generation leaves it out on purpose, add its key path to `ALLOWED` in `tests/test_generation_parity.py` with a one-line reason.
- That test fails when one generation fills a field that the other sends as missing, None or empty.
