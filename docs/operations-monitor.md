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
milestones. The training-counter concern was subsequently traced to PC transfer timing, as described below.


The second heartbeat confirmed live Red had resumed gaining levels. Red and Blue both
had zero observed save reloads during the rc9 interval, and memory remained near 112 MB.
Release rc10 fixes training completion during partial PC transfers. The duplicate-species
hypothesis in earlier notes was incorrect. During withdrawal, a level-43 Graveler briefly
had level 100 in RAM with its own experience before the game recalculated the party slot.
The corrected replay records 8088 XP and one real level gained, without false completion.
See `docs/validation/training-transfer-0.2.0rc10.json` and the rc10 deployment receipt.

Preserve historical outcomes, but treat pre-rc10 director totals as potentially inflated.
Next, compare actual partner XP and new journal milestones across samples. Investigate
repeated Moltres and Ditto objectives if Red continues gaining levels without useful
collecting encounters. Avoid restarts without a verified material fix, so the endurance
record can grow. The first specific live trade remains unapproved and unexecuted.


The third heartbeat left both games on rc10. At that time, the checkout contained an untagged
rc11 candidate at `6de8c1b`. It fixes remembered steps through currently observed solid
objects, but a 432000-frame comparison did not improve overall progress. Do not deploy
it without further work and stronger comparative evidence. The broader candidate image
`pokesim:0.2.0rc11-54569f0` is unused and superseded locally. No rc11 live deployment exists.

Preserved reproduction copies are under `data/operations/repros/red-navigation-20260914`
and `data/operations/repros/blue-training-20260914`. Keep this private repro directory
bounded to eight cases, retaining unresolved cases and removing only obsolete copies
created by this monitoring workflow when necessary. Never prune original live saves.
The comparison is `docs/validation/navigation-candidate-0.2.0rc11.json`.

Next, investigate collection deadlines during maintenance and navigation to the selected
encounter. Controlled Moltres testing showed restocking repeatedly overriding the trip.
Existing training and trainer victories remain real progress, so avoid restarting the
live games for a change that only improves a short navigation metric.

The sampler also records filesystem capacity and each game's data and backup directory
sizes. Watch their growth over time. The first reading was 76.46 percent filesystem use,
25.6 GB free, roughly 1.19 GB of game data, and 8.23 GB of backups. No files were deleted.


Current live versions after the Seafoam recovery delivery: Blue rc12 from `66b226f`,
Red rc10 from `6a23720`. Blue alone was restarted with a cold backup. Red's endurance
interval is continuous from its rc10 startup. The held rc11 experiment is excluded and
preserved on `codex/held-navigation-candidate`. The primary checkout now contains rc12.

Blue's copied save was trapped in repeated floor-hole falls and currents with depleted
attacking PP. The corrected replay reached full HP and PP after 7632 frames at Fuchsia
Pokémon Center. Live Blue subsequently left Seafoam and restored its main team's PP.
The sampler now retains each partner's HP, maximum HP, status, and PP for future checks.
See `docs/validation/seafoam-exit-0.2.0rc12.json` and the rc12 deployment receipt.

The new private reproduction is `data/operations/repros/blue-seafoam-20260914`.
Continue checking Blue's actual experience, catches, and expedition outcomes. Its
Articuno puzzle remains unsupported. Red is still progressing through levels and
trainer victories, so preserve that process while investigating maintenance budgeting.
The first live trade remains unapproved and unexecuted.

A followup at 166 seconds of Blue uptime confirmed a new live level-32 achievement.
Both reload counters remained zero. Red's container start time was unchanged.


## Reserve preparation followup

Release rc13 resets training idle time once when a selected partner first reaches a
stable party snapshot. The persisted experience baseline prevents reloads and repeated
PC transitions from repeating this milestone. The overall project deadline is unchanged.

In the two-hour comparison from a fresh Red checkpoint, both versions gained six levels.
The candidate also picked up two items and won six trainer battles, including a League
rematch. Local recoveries fell from 38 to 33. Neither version caught a new species, and
the initially selected Butterfree still failed to gain experience. Preparation was one
contributor, not a complete explanation of slow collection. Blue's regression remained
unchanged. All 387 tests passed. See
[the comparison](validation/training-preparation-0.2.0rc13.json).

Red received rc13 from `17cd997` with a cold backup and a successful current-save load.
Blue stayed on rc12 and caught a level-25 Kangaskhan live in Safari Zone East, reaching
116 registered entries. Both games remained healthy with zero save reloads. All 12
public checks passed. See [the receipt](validation/release-0.2.0rc13.json).

Next, preserve the live intervals while measuring actual training gains and new catches.
Investigate repeated supply detours and arrival at chosen encounter areas if Red remains
unproductive. The new reproduction is `data/operations/repros/red-preparation-20260914`.
The first live trade remains unapproved and unexecuted.

Filesystem use after the build and backup was 78.58 percent, with 22.71 GB free.
No historical saves or backups were deleted. Continue watching storage growth and plan
bounded backup and image retention before repeated releases consume the available space.


## September 15 partial training followup

Both live games remained healthy with zero save reloads. Blue continued gaining levels
and completing training projects, with 116 registered entries. Red gained a live level
for PUMPKIN after rc13, then returned toward healing. A copied current Red save reached
full HP and PP at Indigo Plateau after 10536 frames and resumed reserve training.
The 72028-frame replay used four local policy recoveries and retained 111 entries.

A separate accounting issue was reproduced in a focused test. The idle-abandon path
marked a training project as deferred even after its selected partner gained 524 XP.
The fix records partial progress and avoids escalating the failure penalty, while
retaining the idle guard and ordinary retry delay. It is queued for a later release,
with 388 tests passing and one optional test skipped. The same copied-save gameplay
was unchanged. Existing historical outcomes remain preserved. See
[the evidence](validation/partial-training-20260915.json).

No live deployment was performed during this heartbeat. Red stays on rc13 from
`17cd997`, and Blue stays on rc12 from `66b226f`. Do not assume the checkout's queued
accounting change is already running in either game. Use the release tags for live
baselines. The new private reproduction is
`data/operations/repros/red-partial-training-20260915`, the fifth retained case.

Storage stayed near 78.57 percent used, with 22.71 GB free. No files were pruned.
Continue measuring Red's collection progress and both live endurance intervals.
The first live trade remains unapproved and unexecuted.
