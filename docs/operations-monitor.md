# Continuing operations

The user authorized ongoing monitoring, improvements, testing, and deployments on
September 14, 2026. Continue within the roadmap without repeatedly asking permission
for routine fixes or deployments. Preserve existing adventures and record backups.
The first live trade retains its specific participant approval requirement. Develop
and validate coordinated execution before attempting it. No automatic save resets.

The user prefers maximum speed whenever resources allow. Use unlimited speed (`0`)
for both live games and copied-save progression tests. Keep that preference across
upgrades and restarts, and only slow down for a specific timing check, resource issue,
or an explicit user request. Both live games were confirmed at speed 0 on September 15
UTC, after the user changed the speed. Red's saved compose setting was also changed
from 1 to 0 without restarting the game. Blue already persisted 0. Earlier Red samples
were collected at 1x, so account for that change when comparing progress per wall hour.
The sampler now records speed and pause state alongside health and progress.

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


The 00:38 UTC September 15 check confirmed Red had restored its depleted attacking PP
and recorded further live level gains after the healing concern. Both container start
times remained unchanged, with zero save reloads. Blue continued gaining levels and
its completed training count reached 18. Registered entries remained Red 111 and Blue
116. Storage was stable at 78.57 percent used, with 22.72 GB free. No deployment or
new runtime change was needed for this check. Keep the partial-training accounting
change queued and continue the existing live endurance intervals.


## September 15 item capacity investigation

The 03:24 UTC sample showed both games making level gains at unlimited speed, with
zero save reloads and unchanged container start times. Inventory investigation found
Blue carrying 20 item types, with no Nuggets or TMs eligible for existing cleanup.
The copied save attempted no pickups over 144020 frames. Earlier expired Ultra Ball
detours were not reproduced, so battle timing remains an unconfirmed explanation.

A candidate allowing battle-booster sales sold X Accuracy and bought Full Restore,
leaving the bag full again. It completed a League rematch but increased local policy
recoveries from 6 to 26 and still attempted no pickups. All 389 candidate tests passed,
but this does not establish a pickup improvement. The candidate was removed from the
runtime checkout and preserved as a patch with the private reproduction. No deployment
was performed. The existing queued partial-training fix remains the only pending
runtime change. See [the comparison](validation/item-capacity-20260915.json).

Next, investigate bounded PC item storage for verified retired story items. Preserve
items instead of discarding them, and keep necessary keys, HMs, balls, medicine, and
escape supplies available. Also reproduce the expired pickup detours independently.
The sampler now records item contents and occupied bag slots. The private reproduction
is `data/operations/repros/blue-item-capacity-20260915`, the sixth retained case.


## PC sorting release, September 14 evening

Both games now run rc14 from `1473f1d`, including the previously queued partial-training
accounting fix. Cold backups and save compatibility checks passed. All 12 public checks
and six static asset comparisons passed. Red has 112 registered entries and Blue has
116. Both are healthy at unlimited speed with zero post-startup save reloads. The
maintenance restarts begin fresh endurance intervals. Bag capacity remains the next
simulation investigation. See [the release receipt](validation/release-0.2.0rc14.json).


## Scoped trading release, rc16

Both games, the broker, and the scoped coordinator now run rc16 from `caa092b`.
The original privileged coordinator was rejected before startup and replaced with
an ordinary UID 10001 service using authenticated trade controls and durable holds.
The implementation passed 406 Python tests, seven JavaScript tests, and a copied-save
crash recovery rehearsal. Live trading remains disabled. Automatic approval review
requires explicit approval of the first exchange and subsequent automatic policy.

The pending first exchange is Red's spare DIRTNAP (Machoke, level 41) for Blue's spare
MOCHI (Vulpix, level 32). Recheck these individuals and protect their current projects.
If approved, verify this exact exchange before enabling the ordinary 15-minute policy.
Both games remain unpaused at unlimited speed, with 113 and 116 entries and zero reloads.


## September 15, 05:34 UTC pickup retry investigation

The 33-minute rc16 interval retained both container start times, healthy workers,
unlimited speed, and zero save reloads. Red's SPROUT reached level 100, confirmed in a
later copied checkpoint. Both games gained other levels, and Blue completed two more
training projects and two supply projects. Registered entries stayed at 113 and 116.
Blue still has 20 bag slots occupied and no new pickup history during this interval.
Disk use was 83.15 percent, with 16.53 GB free. No endurance milestone is reached yet.

Red's live pickup history repeatedly alternated failed Max Revive and Max Potion
approaches. A 216004-frame copied replay gained five levels and won five trainer
battles, including a League rematch, but made no pickup attempts. A candidate with
persistent capped retry backoff had identical gameplay and 29 local policy recoveries.
Its 408 tests passed, but the replay did not establish a benefit. The candidate was
removed from the runtime checkout and retained as `held-backoff.patch` with the private
case `data/operations/repros/red-pickups-20260915`.

The sampler now records active pickup targets, retry deadlines, completed pickup keys,
next scan time, and local policy recoveries. Those fields should help capture a save
while the failed detour is active. The case count is seven. Retain at most eight cases,
preserving validation records and held patches before retiring older private artifacts.
No games were restarted and no runtime deployment was made. Trading remains disabled
under the existing approval block. See [the comparison](validation/pickup-retry-20260915.json).
