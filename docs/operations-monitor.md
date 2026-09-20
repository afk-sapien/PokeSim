# Monitoring runbook

This is the repository's monitoring procedure. Deployment-specific settings and access
are described in [homeserver.md](homeserver.md). The
[release status](../RELEASE_STATUS.md) summarizes the last recorded deployments.

## Collect evidence

For the documented homelab installation, run:

```sh
.venv/bin/python tools/sample_live.py
```

The sampler uses the configured SSH access to `servarr` and writes private observations
to `data/operations/live-samples.json`, retaining at most 3360 samples. It is specific
to that installation. Other installations need their own endpoints and access settings.

Compare container start times and image revisions before comparing counters. A restart
begins a new endurance interval. Read previous samples, not only the latest position.

Record:

- Health, pause state, speed, process uptime, save reloads, memory, and storage use.
- Registrations, catches, evolutions, training XP and levels, completed projects,
  incomplete outcomes, healing, and time spent preparing versus training.
- Trade availability, completed exchanges, pending rewards, storage capacity,
  persistent holds, and recovery failures.

Two consecutive observations without useful progress warrant investigation. Experience
can increase without a level-up, and a difficult catch can span multiple observations.
Inspect the selected partner, objective outcomes, supplies, recent events, and route
before calling a run stalled.

## Stall reports

Each adventure watches its own progress. With no badge, catch, evolution, gift, item,
trainer victory, level or new map for two hours of game time and fifteen real minutes,
it records a `stall` journal entry naming the objective and place, attaches the saved
moment, and sends it like any other notable event. Live shows Stuck? and the Library
summary sets `stalled`. Managed trades are arranged by the coordinator and do not count.
A continuing stall is reported again every six hours. The three `STALL_ALERT_*` settings
in the [guide](guide.md) adjust or disable this.

## Find stalls before a release

```sh
.venv/bin/python tools/find_stalls.py --rom roms/pokered.gb \
  --output ~/pokesim-soak/red-seed7 --until-champion --seed 7
```

This plays a fresh cartridge, or a copied `--checkpoint`, at full speed with no server
and no live data. One game hour takes about a minute. Every stall leaves a `stall-NN`
folder holding the moment it was noticed, the rolling checkpoint from before it began,
a screenshot and a report with the objective, position, money and recent failures.
Both checkpoints replay with `tools/validate_progress.py`, so a candidate fix can be
compared with the baseline on identical input. The run stops after six game hours in
one stall, at the Hall of Fame with `--until-champion`, or when `--hours` is spent, and
exits nonzero when it found any stall. Run several seeds and both editions.

## Investigate and validate

Reproduce failures on private copied saves with matching ROM and PyBoy metadata.
Distinguish policy replanning, blackouts, save reloads, failed health checks, and process
restarts. Keep failures in the record even when a later sample recovers.

Use the same checkpoint and comparison budget for candidate and baseline runs. Record
actual progress and regressions. A short replay does not establish multi-day endurance.
Do not restore older live saves merely to improve progress statistics.

For a deployment, preserve the current image and a complete cold backup, verify that
the candidate loads a copy of the latest save, and record the exact revision and receipt.
Follow [operations](operations.md) and the installation's configured access policy.

## Configuration and reporting

Inspect the deployed coordinator policy when interpreting rewards and trades. Older
releases include Mew in the random Championship pool. The working source grants it
separately once after Champion and uses seven species for repeatable rewards.
Check the deployed revision before changing expectations.

Report meaningful changes, verified fixes, failures requiring attention, and completed
endurance milestones. Unchanged healthy observations do not need repeated reports.
Update the short release summary and link sanitized evidence in `docs/validation`.
Keep ROMs, saves, tokens, and private traces outside Git.

The [archived operations record](history/operations-monitor.md) preserves prior
observations and their original operational context. It is not a current instruction
to change a deployment or a substitute for checking that installation's settings.
