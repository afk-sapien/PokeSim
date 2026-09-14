# Continuing operations

The user authorized ongoing monitoring, improvements, testing, and deployments on
September 14, 2026. Continue within the roadmap without repeatedly asking permission
for routine fixes or deployments. Preserve existing adventures and record backups.
The first live trade retains its specific participant approval requirement. Develop
and validate coordinated execution before attempting it. No automatic save resets.

The task heartbeat checks every 30 minutes. It stays quiet when nothing actionable
changes. Report material findings, verified improvements, deployments, problems needing
attention, and completed 24-hour, 48-hour, and week-long endurance milestones.

Run `.venv/bin/python tools/sample_live.py` from the repository. It uses SSH to `servarr`
and appends to `data/operations/live-samples.json`, retaining at most 3360 samples. This
private file includes current project details and resource measurements. Read previous
samples when judging progress, rather than comparing only coordinates or HTTP health.

Compare each run's container start time and image before interpreting frame or reload
counters. A deployment starts a new endurance interval. Record failures even when a
later sample recovers. Distinguish in-game blackouts, policy replanning, save reloads,
container restarts, and failed health checks. Do not claim an uninterrupted pass when
the record has gaps or relevant failures.

Investigate two consecutive samples with no useful progress, a repeated objective,
recurring save reloads, or unhealthy service. Training can make useful experience gains
without a level-up, and a difficult catch can take longer than one sample. Check the
selected partner, objective outcomes, pickup history, inventory, and recent journal
events. Read more frequent samples or copied-save traces to distinguish slow progress
from a loop. Both runs were attempting storage management immediately before rc8, so
watch that behavior particularly closely.

Reproduce gameplay failures on copied saves with matching ROM and PyBoy metadata.
Commit bounded fixes, run relevant tests, and deploy exact source revisions with fresh
cold backups. Verify that the new image loads a copy of the latest save before starting
the live process. Preserve configuration and existing ROM, save, and game-data mounts.
Do not restore an old save merely to improve reported progress. Keep any failed run's
evidence before rolling back a faulty application change.

Use `docs/homeserver.md` and the release receipts for current images and backup paths.
Keep runtime artifacts and game data out of Git. Update the roadmap and release status
when observations materially change what is complete or what should happen next.


The first heartbeat deployed rc9 from `8ca0271` after reproducing Red's stale routes
through reset Victory Road gates. Its backups and startup checks are recorded in
`docs/validation/release-0.2.0rc9.json`. The rc8 live interval had no observed save reloads,
but Red stalled. Do not classify that interval as successful gameplay endurance.

Next checks should confirm that live Red reaches healing and gains experience or journal
milestones. Also audit the director's training identity for duplicate species. A copied
replay credited an existing level-100 Graveler to a level-43 Graveler's project. Use
journal level events and the selected individual until that accounting is corrected.
