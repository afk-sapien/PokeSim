# Continuing operations

The user authorized ongoing monitoring, improvements, testing, and deployments on
September 14, 2026. Continue within the roadmap without repeatedly asking permission
for routine fixes or deployments. Preserve existing adventures and record backups.
The user explicitly authorized live automatic trading on September 15, 2026 UTC.
The scoped coordinator is enabled with a 15-minute minimum exchange interval. Last-copy
sharing is enabled only for new recipient Pokédex entries. Active parties and current
projects remain protected. Every newly observed Championship earns a random starter, Eevee, fossil Pokémon, or Mew.
Monitor earned, delivered, and pending claims, PC capacity, and duplicate delivery prevention.
There is no reward cooldown or roster qualification. Keep the older one-time Mew event
disabled. Do not
request individual trade approvals. Monitor completed trades, stuck holds, recovery,
and prolonged waiting for opportunities. No automatic save resets.

Both games caught Mewtwo on rc19. On rc20, missed legendary encounters can return after
leaving the room and a persistent retry delay. Track `legendary_recovery`, recent
legendary outcomes, capture supplies, and actual Pokédex registrations. Red's missed
Moltres returned in event 8655. Never respawn registered legendaries, including traded
copies. Empty balls and full storage must cause retreat and preparation. Distinguish
ordinary route battles, policy replanning, and save reloads. Do not repeatedly interact
with a resolved encounter or weaken a missing legendary.

The user prefers maximum speed whenever resources allow. Use unlimited speed (`0`)
for both live games and copied-save progression tests. Keep that preference across
upgrades and restarts, and only slow down for a specific timing check, resource issue,
or an explicit user request. Both live games were confirmed at speed 0 on September 15
UTC, after the user changed the speed. Red's saved compose setting was also changed
from 1 to 0 without restarting the game. Blue already persisted 0. Earlier Red samples
were collected at 1x, so account for that change when comparing progress per wall hour.
The sampler now records speed and pause state alongside health and progress. It also
records automatic trading status, completed count, last exchange time, useful proposal
count, and at most three compact exchange records from the public board.

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


## September 15, 06:11 UTC progress check

Blue obtained Lickitung through the Route 18 Gate 2F NPC exchange, confirmed by journal
event 3444, and reached 117 registered entries. This was an ordinary in-game NPC trade,
not a coordinated exchange between the servers. Red remains at 113. Each game completed
two more training projects in the 31.9-minute interval, and the selected partners also
showed current experience gains. Blue completed one collection and one supply project.

Both rc16 containers retain their start times and continue at unlimited speed with zero
save reloads. Local policy recoveries increased by 82 for Red and 88 for Blue. Red's
pickup history still records repeated failures, while both sampled active targets and
retry maps were empty. A bounded 90-poll capture attempt found no active pickup checkpoint.
No runtime change or deployment was justified, and neither game was paused or restarted.
Disk use remained stable at 83.16 percent, with 16.53 GB free. See
[the monitoring record](validation/monitor-20260915-0611.json).


## Automatic trading activated, September 15 UTC

The owner explicitly approved live automatic trading and no individual trade approval
requests. Both policies are enabled with a 900-second minimum exchange interval.
The existing coordinator continues independently of the desktop. The heartbeat now
monitors automatic exchanges and no longer carries the superseded approval requirement.

The board displays automatic mode. During the initial observation no exchange had
completed. One HTTP retry cleared and neither game retained a hold. Both adventures
remain healthy, unpaused, at unlimited speed with zero reloads and unchanged container
start times. Follow up on the first completion and investigate prolonged safe-point
waiting if the next monitor still finds no exchange. See
[the activation receipt](validation/automatic-trading-enabled-20260915.json).


## September 15, 06:59 UTC first automatic trade verified

The coordinator completed the approved DIRTNAP and MOCHI exchange at 06:32 UTC.
Red registered Vulpix, then autonomously evolved MOCHI into Ninetales in event 8360.
Blue received Machamp through the trade evolution. Red now has 115 registered entries
and Blue has 118. Both games journaled the transaction once, released their holds,
and retained the same trade marker in later autosaves.

The 32.85-minute interval preserved container start times, healthy workers, unlimited
speed, and zero recovery reloads. Red completed one training, one supply, and one
evolution project. Blue completed two training, two exploration, and one supply project.
Local policy recoveries increased by 85 and 78. No new confirmed pickup keys appeared.
Disk use is 83.2 percent with 16.47 GB free.

The next exchange is waiting for both overworld states, with 12 useful proposals visible.
The sampler now records compact trading status and was verified against the live board.
Monitor the delay beyond the 15-minute minimum interval. No runtime deployment or game
restart was needed. See [the verification](validation/monitor-20260915-0659.json).


## September 15, 07:30 UTC rc17 deployment

Both games, the board, and the coordinator now use rc17 from `646b32b`. Fresh cold
backups were taken and both current saves loaded successfully. Red retained 116
registered entries and Blue retained 119. Both are healthy, unpaused, at unlimited
speed with zero recovery reloads since this deployment. This starts new endurance
intervals. All 12 public endpoint checks passed.

Random fossil and Eevee evolution choices persist for new runs. Existing choices remain
intact. Last-copy sharing is enabled only when the recipient registers a new species.
The board displays last-copy proposals while protecting active parties and projects.
Two previous live exchanges remain recorded, including Machamp and Golem registrations.

The optional Mew gift passed copied-save interruption recovery, duplicate prevention,
and actual PC withdrawal and training from level 5 to level 12. It remains disabled on
the live pair while the user considers rewards requiring varied Championship teams.
No live Mew was delivered. See [the release receipt](validation/release-0.2.0rc17.json).


## September 15, 09:24 UTC legendary route investigation

During 45.2 minutes of unchanged rc20 container starts, Red gained two registrations
and Blue gained three. Two automatic exchanges completed: Bellsprout for Mankey, then
Pinsir for Vileplume. Blue also evolved Mankey into Primeape. Both games stayed healthy
at maximum speed with zero save reloads and container restarts. Local policy replanning
increased by 95 for Red and 126 for Blue. No 24-hour endurance pass is claimed.
See [the interval record](validation/monitor-20260915-0924.json).

The new private reproduction is `data/operations/repros/legendary-routes-20260915`,
the eighth retained case. Blue repeatedly requested Surf at Seafoam B4F's strong-current
stairs. A 36,000-frame replay of the exact rc20 source reproduced the failure. The rc21
candidate loaded the same saved objective, completed the normal boulder pushes, caught
Articuno after 17,646 frames, and continued toward storage. No flags, inventory, or
Pokémon were injected. All 453 tests passed, with one optional test skipped.

The new sampler fields retain legendary retry state and four recent legendary outcomes.
Red's separate Moltres issue remains unresolved. Its copied checkpoint routes between
Victory Road's east pockets while the switch gates have reset. Do not describe restoring
Moltres's encounter as catching it. Continue investigating a valid route to its platform,
and preserve productive live training and trading while testing candidates on copies.

New cold backups use gzip compression. Existing backups and live data were not pruned.


Both live games caught Articuno after rc21 deployment, in Red event 8709 and Blue event
3806. Red reached 125 registrations and Blue reached 128. Both games are healthy at
maximum speed with zero recovery reloads. Automatic trading has seven completed exchanges.
All five Red rewards and six Blue rewards are delivered. The new cold backups passed
compressed-stream integrity checks. See [the rc21 receipt](validation/release-0.2.0rc21.json).
The rollout starts new endurance intervals. Continue with Red's Moltres route and avoid
repeating notifications for the already confirmed Mewtwo and Articuno catches.


## September 15, 10:20 UTC Moltres catch verified

Red completed its ordinary live Moltres expedition on rc21, confirmed by catch event
8753 at 10:10 UTC. Both runs now physically retain Articuno, Zapdos, Moltres, and
Mewtwo. This supersedes the live Moltres blocker above. The forced-target copied
route failure remains preserved as a navigation edge case, but it does not justify
interrupting the successful adventures or claiming that a new route fix was deployed.

Both rc21 container starts are unchanged after about 38 minutes, with healthy workers,
maximum speed, and zero save reloads or container restarts. Both reached 129 registered
entries, four more for Red and one more for Blue since their Articuno catches. The eighth
automatic exchange registered Victreebel for Red and Hitmonchan for Blue. Red evolved
Bellsprout and Squirtle, collected Nugget and TM Mega Kick, and recorded 13 level events.
Blue collected Escape Rope and recorded 13 level events, including CRABRAVE reaching
levels 57 through 59. Red's six and Blue's eight Championship rewards are all delivered.
No runtime change or deployment was performed. See
[the monitoring record](validation/monitor-20260915-1020.json).

The journal appears to report some PC transfers as spare releases. For example, Red event
8737 and Blue event 3818 report Mewtwo releases, while the same unique nicknamed
Mewtwo remain in their boxes. Blue's reported Moltres release also precedes continued
training of CRABRAVE, which remains stored at level 59. Investigate the event confirmation
window on copied saves. Do not infer actual loss from these journal messages alone.

Continue useful collection, training, pickup, reward, and trading checks. Prioritize
accurate PC transfer reporting and bounded storage growth. Available filesystem space
is 6.72 GB, with 90.43 percent used. No images, backups, or saves were removed. Preserve
this live endurance interval and avoid repeating the confirmed legendary notifications.


## September 15, 10:54 UTC PC release correction

The final 42.2-minute sampled rc21 interval retained healthy workers, maximum speed,
zero save reloads, and unchanged starts. Both gained two registrations since the prior
sample. Red completed five training projects and one evolution, while Blue completed
two training projects and one supply project. Local replanning increased by 133 and
120. The ninth automatic exchange registered Kangaskhan for Red and Wartortle for Blue.
See [the interval record](validation/monitor-20260915-1054.json).

A 72,022-frame copied replay reproduced both a genuine Geodude release and a false
Tentacruel release. CRICKET already appeared in the party before the box entry disappeared.
The one-snapshot population check mistook that later removal for a release. The rc22
candidate matches recent party arrivals by species and nickname, persists bounded
arrival records, expires old records, and cancels them on deposit. Opposite-order writes
confirm the matching individual's count. The replay retains only the genuine release.
No Pokémon, release policy, historical journal events, or live saves were edited.

All 458 Python tests passed, with one optional test skipped, and all seven JavaScript
checks passed. The default sandbox stalled an API client test, so its test process was
terminated and the complete suite reran successfully outside the sandbox. Both final
packages passed resource checks. See
[the copied comparison](validation/pc-release-events-0.2.0rc22.json).

Both games, the board, and coordinator now run rc22 from `49403d7`. Fresh compressed
cold backups and current-save load checks passed. All 12 public checks passed. Both
games resumed with 132 registrations, maximum speed, and zero recovery reloads. Ten
automatic trades have completed, and all seven Red and ten Blue rewards are delivered.
This starts new endurance intervals. See
[the deployment receipt](validation/release-0.2.0rc22.json).

Post-rollout filesystem space is 5.71 GB free,
with 91.17 percent used. No original saves, backups, or old images were
removed. Prioritize bounded release storage before additional frequent deployments.
The Dockerfile declares changing release arguments before its system-package layer,
which invalidates that layer's cache for each release. Move metadata after stable image
setup in a future candidate and validate packaging before deployment. Inventory image
references and rollback needs before selecting a bounded retention policy. Continue
checking PC journal accuracy and useful progress without unnecessary restarts.


## September 15, 11:37 UTC release storage maintenance

Both rc22 games retained their start times, healthy workers, maximum speed, and zero
save reloads. Both initially reached 133 registrations. Red completed another training
project, while Blue's partial training outcomes included 13,180 XP for Mewtwo and 4,012
XP with two levels for Primeape. Both retained all four encounter legendaries, and no
new legendary release messages appeared in the sampled rc22 journal. No new coordinated
trade had completed at the first sample, with ten total and ordinary overworld waiting.
See [the progress record](validation/monitor-20260915-1137.json).

Converted all 26 legacy uncompressed cold backups to gzip, retaining every archived
byte. Each replacement verified the decompressed SHA-256 against the source, checked
for source changes, and synced the result before replacing the tar. Together they fell
from 15.64 GB to 1.43 GB,
saving 14.21 GB. The four already compressed rc21 and rc22
backups were untouched. Historical receipt paths ending in `before.tar` now resolve to
`before.tar.gz` in the same directory. No active saves or archived save contents were
removed. The conversion manifest retains all hashes and old-to-new paths.

Removed ten unused monitoring image tags from rc9 through rc19 after checking retained
source archives, revision labels, aliases, and every container reference. Keep current
rc22, rollback rc21 and rc20, the held rc11 image, and earlier legacy images. No global
image, build-cache, or volume pruning was performed. See the ongoing retention policy
in [homeserver.md](homeserver.md#release-storage-retention).

Moved changing release metadata after stable Docker filesystem layers. Two disposable
builds with different revision labels produced identical layers, passed import checks,
and retained the live runtime configuration. Both probe image tags were removed.
The 39 focused backup and release checks passed. This packaging change is committed
for future builds. No runtime deployment or service restart was needed.

Final free filesystem space is 19.48 GB, with
80.97 percent used. Both games remain on rc22 with unchanged starts.
Continue this endurance interval, monitor useful training and trade opportunities,
and apply the documented image retention policy after future validated releases.
See [the storage evidence](validation/release-storage-20260915.json).


## September 15, 12:20 UTC automatic exchanges and reserve training

The 31.98-minute interval preserved both rc22 starts, healthy workers, maximum speed,
and zero save reloads or container restarts. Red reached 136 registrations and Blue
reached 137. Two more automatic exchanges completed, bringing the total to twelve:
Red registered Golem and Hitmonlee, while Blue registered Arcanine and Gengar. The latter
exchange evolved PEBBLE during transfer. Both journals confirm each exchange. Blue also
evolved a reward Charmander into Charmeleon in event 4010.

Red's partial training outcomes include 9,282 XP and one Moltres level, 3,575 XP for
Machamp, and 10,456 XP with two Persian levels. Blue completed two more training projects
and an evolution project, including a five-level Eevee training milestone. The journal
recorded 15 Red level events and 42 Blue level events during the inspected interval.
All eleven Red and fifteen Blue Championship rewards are delivered. Both collections
retain all four encounter legendaries, with no new legendary release messages. No new
pickup event appeared during this interval.

The coordinator is ready with no error. Its two new trades completed about 19.4 minutes
apart. No trading intervention, runtime edit, or deployment was necessary. Free disk
space remains stable at 19.46 GB. Preserve the current endurance interval and continue
monitoring useful gains and exchange latency. No multi-day endurance milestone is
claimed. See [the monitoring record](validation/monitor-20260915-1220.json).


## September 15, 12:52 UTC reward evolution progress

The 31.96-minute interval retained both rc22 starts, healthy workers, maximum speed,
and zero save reloads or container restarts. Red reached 137 registrations after evolving
its new Championship Eevee into Flareon in event 9066. Blue reached 139 after evolving
Eevee into Jolteon in event 4068 and its Wartortle into Blastoise in event 4088. Red also
picked up an Escape Rope in Pokémon Mansion, confirmed by event 9078.

Red completed one training, one evolution, and two supply projects. Blue completed two
training, two evolution, and one supply project. Partial training also gained real XP,
including Blue's Porygon gaining 6,598 XP and two levels. The journal recorded 24 Red and
35 Blue level events. Neither inspected journal contained a legendary release message.

The automatic trade count remains twelve. The coordinator reports ordinary overworld
waiting with no error. Each game has one newly earned Championship reward pending,
with six free box slots each. Both were in battle at the detailed check, so this is a
safe-point wait rather than a storage blockage. Red has fourteen earned and thirteen
delivered rewards. Blue has seventeen earned and sixteen delivered. Verify delivery
in the next interval, and investigate only if the wait persists without safe-point progress.

No runtime change, manual trade cycle, or restart was needed. Disk space remains stable
at 19.48 GB free. Continue the rc22 endurance interval. See
[the monitoring record](validation/monitor-20260915-1252.json).


## September 15, 13:24 UTC reward and trade scheduling

Both games retained healthy rc22 processes, maximum speed, and zero recovery reloads.
Red reached 138 registrations and Blue reached 140. Earlier pending rewards were
delivered, but more League wins built another backlog. The trade count remained twelve,
with more than an hour since the last exchange despite visible useful proposals.
Training continued, including Red's Alakazam gaining 24,262 XP and three levels.
See [the interval record](validation/monitor-20260915-1324.json).

The coordinator always selected rewards first at safe points. A regression with pending
rewards across four fresh coordinator instances reproduced four reward-only attempts.
The rc23 candidate alternates reward and overdue useful trade attempts. It persists the
last attempted operation, including skipped attempts, retains the configured cooldown,
and delivers rewards when proposals are absent or the board cannot be reached. Unsafe
peers are never held to force scheduling. No transaction, release, or Pokémon handling
code changed. All 468 Python tests passed, with one optional test skipped, and seven
JavaScript checks passed. See
[the scheduling evidence](validation/trade-fairness-0.2.0rc23.json).

Only the scoped coordinator was upgraded, to rc23 from `7ccf16e`. A cold private archive
of its state and configuration passed gzip integrity checks. The first preflight missed
a game-data mount in the temporary check, stopped before cutover, and resumed the old
worker. The corrected preflight passed. Both games and the board remain on rc22 with
their original starts. This preserves the game endurance interval, while coordinator
uptime starts anew. A first preparation HTTPError cleared to ordinary overworld waiting
on the next scheduled cycle. The durable last operation is a reward attempt, leaving
an overdue useful trade eligible for the next safe turn.

Do not claim a measured live trade-frequency improvement yet. Confirm subsequent actual
exchanges and continued reward delivery. The sampler now retains coordinator image,
start time, process status, and last operation alongside trade counts. Keep the union of
rollback images needed by each service, currently rc20 through rc23 plus the held rc11
image and earlier legacy images. See
[the coordinator deployment receipt](validation/release-0.2.0rc23.json).


## September 15, 14:46 UTC independent exchange safe points

Across 36.85 minutes with unchanged game starts, Red reached 140 registrations and
Blue reached 142. Red completed three training projects, one evolution, and one supply
project. Blue completed another training project. Red's recent partial training gains
included 13,165 XP and two levels, followed by 3,675 XP and another level. Both games
remained healthy at maximum speed with zero recovery reloads.

The rc23 coordinator completed its second live exchange since deployment, bringing the
total to fourteen. Red registered Charizard and Blue registered Kabuto. Each game also
received four Championship rewards since 14:09. The pending counts declined from four
and three to three and two despite three new wins each. This confirms continued reward
delivery and actual useful trades, while long gaps between overlapping safe samples
still leave room to improve scheduling.

The preserved regression failed on rc23 when API samples showed battle state even
though each game could reach its own safe checkpoint. The rc24 candidate requests
preparation independently within one shared 15-second retry window, retrying only the
explicit overworld-wait response. The game-side safety checks are unchanged. Timeouts
and all other rejections release prepared peers through existing durable cleanup.
An in-flight request retains the existing 20-second transport timeout.

A copied-save rehearsal held Red while Blue's open menu rejected preparation. Ordinary
B input closed Blue's menu, then the coordinator completed a useful Sandshrew and Ekans
exchange. Both games resumed and subsequent saves reloaded. Original source hashes
were unchanged. Tests cover staggered readiness, a shared deadline, abort cleanup,
paused or unhealthy peers, authentication rejection, conflicting holds, and unknown
409 responses. All 478 Python tests passed, with one optional test skipped. Both
JavaScript test files passed. See
[the safe-point evidence](validation/trade-safe-points-0.2.0rc24.json).

Only the coordinator was deployed as rc24 from `d99cdc2`, with a verified compressed
cold backup of its private state and configuration. Game and board starts were
unchanged. The first cycle hit the bounded retry timeout. The next scheduled cycle
completed successfully, confirming that the timeout did not leave a stuck hold.
At 14:54 UTC, a live reward transaction delivered Red's twentieth reward
(Kabuto) and Blue's twenty-fourth (Mew). Both games resumed healthy with no holds,
no active transaction, and zero recovery reloads. The coordinator reported ready
with no error. Red had three pending rewards after another win, and Blue had one.
See [the deployment receipt](validation/release-0.2.0rc24.json).

The next scheduled cycle completed trade fifteen, registering Blastoise for Red and
Gloom for Blue. It began 938.94 seconds after trade fourteen, about 15 minutes
39 seconds against the configured 15-minute minimum. At 14:56 UTC Red had 141
registrations and Blue had 143. Both games were healthy, unpaused, and still at their
original rc22 starts with zero recovery reloads. This verifies one timely rc24 trade
and one reward delivery. It is not yet a sustained frequency or multi-day endurance
claim. Continue measuring safe-point timeout frequency, pending rewards, and useful
trades while preserving the game processes. Free disk space was 18.28 GB after the
new image and compressed backup. Retain rc20 through rc24 to cover the current
services and their rollback images.


## September 15, 15:27 UTC reward queues clear and journal investigation

The 31.59-minute interval preserved both rc22 game starts, maximum speed, zero save
reloads, and zero container restarts. Red reached 143 registrations and Blue remained
at 143. Red completed two supply projects, and Blue completed another training project.
The journals recorded forty Red level events and thirty-one Blue level events. Recent
Blue training outcomes included 5,870 XP and one level, 6,830 XP and one level, and
10,395 XP and three levels. No new ground pickups were observed in this interval.

The rc24 coordinator completed trades sixteen and seventeen. Red registered Gengar,
then Magmar. Blue recovered a missing collection partner, then received a stronger
partner. The new trade intervals were 905.10 and 929.71 seconds, close to the configured
900-second minimum. Red received six Championship rewards and Blue received three.
Both queues were empty at the sample, with 26 Red rewards and 27 Blue rewards earned
and delivered. Five Red box slots and six Blue slots were free at the detailed check.
One additional bounded preparation timeout appeared in the coordinator log. The
coordinator and both games had no active holds when inspected, with no current error.
Free disk space stayed near 18.25 GB. See
[the interval record](validation/monitor-20260915-1527.json).

Repeated Diglett release journal messages prompted a separate copied Red replay. It
reproduced a false Wigglytuff release at frame 53,118, while the cartridge text said
PIXEL was taken out and PIXEL remained in the party. At frame 53,026, the incomplete
party structure temporarily reported 251 HP against a stale maximum of 195. This
invalid snapshot replaced the last valid event baseline. The following valid snapshot
therefore failed to record the arrival before the box entry disappeared.

The candidate retains a recent valid event baseline across at most 120 invalid frames.
Health and policy still receive the actual invalid snapshot, and longer gaps reset
the baseline. The same 54,000-frame replay suppresses the false release, with the same
party and box contents at confirmation. Three integration regressions failed before
the change and pass afterward, including preservation of real release events. All
481 Python tests passed, with one optional skip. Original copied checkpoint hashes
were unchanged. The temporary source is `/tmp/pokesim-director/pc-check-1530`, leaving
the eight retained private reproduction cases unchanged. See
[the comparison](validation/pc-invalid-write-20260915.json).

This journal-only correction is committed for the next necessary game release. No
runtime deployment or restart was performed. Preserve the current endurance interval,
which had reached about four hours and twenty-three minutes at the sample. Continue
monitoring useful progress and recurring transfer messages without treating these
messages alone as evidence that a Pokémon was lost.


## September 15, 16:10 UTC continued progress without intervention

The 42.87-minute comparison retained both rc22 starts, maximum speed, zero recovery
reloads, and zero container restarts. Both games had 143 registrations. Red completed
two training projects, including Blastoise reaching level 40, and Blue completed one.
The journal audit recorded 31 Red level events and 39 Blue level events. Recent partial
training gains included 8,085 XP and three levels in Red and 5,360 XP and three levels
in Blue. No new catches, evolutions, or ground pickups appeared in the journal interval.

Trades eighteen and nineteen completed, with intervals of 942.93 and 936.14 seconds.
Both restored a missing partner in Red and supplied a stronger partner to Blue.
Red received four more Championship rewards and Blue received two. At the sample,
Red had thirty rewards earned and delivered, and Blue had twenty-nine, with no pending
claims. The audit found no duplicate Championship gift titles and six free box slots
in each game. Both retained all four encounter legendaries. The coordinator recorded
two bounded preparation timeouts during the interval, followed by clean operation.
No active transaction or peer hold remained at the detailed check.

The games had passed five hours of uninterrupted runtime, short of the first 24-hour
endurance milestone. Free disk space stayed near 18.24 GB. No runtime edit, deployment,
manual trade cycle, or restart was necessary. The validated journal correction at
`dac1f95` remains queued for the next necessary game release. Release journal messages
remain subject to that known reporting issue. Continue ordinary monitoring without
repeating prior deployment or catch notifications. See
[the interval record](validation/monitor-20260915-1610.json).


## September 15, 16:43 UTC Red healing stall

Blue completed another training and evolution project, evolving Kabuto into Kabutops
in event 4480. Trade twenty-two then registered Kabutops in Red. Both games reached
144 registrations. Blue had 31 rewards earned and delivered, and Red had thirty,
with both queues empty. Three more trades completed during the interval. Both games
were healthy at maximum speed, with unchanged rc22 starts and zero recovery reloads.

Red's local progress nevertheless stalled. Its last non-trade level event was at about
16:19 UTC, while its depleted team repeatedly failed to leave Victory Road 1F to heal.
The recent trade achievement concealed that distinction in the Live summary. A copied
Red checkpoint stayed on 1F for 24,002 frames. Clearing its remembered navigation in a
separate 36,028-frame diagnostic did not find a successful healing route either.

Red had an unused Escape Rope. The rc25 candidate uses the ordinary item menu for one
retreat attempt when a healing trip reaches recovery in Victory Road. The attempt
persists across checkpoints and trades, so a failed attempt cannot repeatedly spend
ropes. The flag clears after full healing. The same copied source escaped and healed
at Saffron after 6,924 frames. A 90,004-frame continuation resumed training in Diglett's
Cave, used one rope, and performed no rewinds or RAM edits. The witness is retained as
`red-escape` within the existing Victory Road reproduction case, leaving eight cases.
This fallback does not claim to solve every route or provide escape without supplies.
All 490 Python tests passed, with one optional skip. Both JavaScript files and package
checks passed. See [the comparison](validation/victory-escape-0.2.0rc25.json).

Only Red was upgraded to rc25 from `a0c3398`. The coordinator stopped briefly, and a
preflight confirmed no active transaction or peer hold. Red's compressed cold backup
passed integrity checks and the new image loaded its latest save. Blue and the board
kept their original starts. The coordinator resumed on rc24. Red's prior uninterrupted
interval ended at 21,086 seconds, about five hours and fifty-one minutes. Its new start
is 16:56:43 UTC. The coordinator's resumed start is 16:56:45 UTC. Do not count these
as recovery reloads or merge Red's endurance intervals.

At the first live follow-up, Red had left Victory Road, spent the one Escape Rope,
and healed. It was on Route 9 with full party HP and restored PP, pursuing Kangaskhan
training. Both games retained 144 registrations, healthy workers, and maximum speed.
Red had thirty rewards earned and delivered, and Blue had thirty-two, with no pending
claims. Trading remained enabled. See [the Red receipt](validation/release-0.2.0rc25.json).

The monitor now records `last_local_progress` from catches, evolutions, levels, trainer
wins, Championships, badges, and ground items separately from trades and reward gifts.
This read-only field makes a recent exchange less likely to conceal a stalled local
adventure. The field was verified against both live journals. Red now includes the
previously validated journal correction. Blue remains on rc22 until its next necessary
upgrade. Retain rc20 through rc25 for the current services and rollback coverage.

The next live sample confirmed renewed local progress. Red's Kangaskhan, GRUNKLE,
gained 15,961 XP and three levels, reaching level 48 in journal event 9489. It then
continued through the Underground Path. The new local-progress timestamp advanced,
independently of trades. Both games were healthy, unpaused, at maximum speed, and
without recovery reloads. The final coordinator check found no active transaction.
Blue retained its original start and continued training. Free disk space after the
new image and backup was about 17.57 GB. The rc25 recovery and restored Red progress
are verified live. Further monitoring should watch for recurring cave stalls when
no Escape Rope is available, without treating the bounded fallback as a universal
navigation repair.


## September 15, PC power ranking and planning assessment

The user requested a way to identify the strongest boxed Pokémon and asked whether
walking and task switching conceal slow progress. A one-hour journal sample found
15 Red level-ups and one Championship, plus 36 Blue level-ups, three Championships,
and one evolution. Four exchanges completed across the pair. Both had 144 registered
species. Ordinary wild wins are not journaled as trainer events, so those counts are
not battle totals. Recent project outcomes nevertheless include partial training
and zero-gain deferrals. The 7,200-frame inactivity deadline is game time, not wall
time. Investigate preparation and travel separately from productive training before
changing the planner. Longer useful sessions and fewer repeated PC trips are the next
priority. Do not extend deadlines merely because coordinates change.

rc26 adds Power as the sum of calculated max HP, Attack, Defense, Speed, and Special.
Stats use current level, species, DVs, and stat experience with cartridge rounding.
The UI supports a strongest-across-all-boxes shortcut, individual stat sorting,
visible scores, and a detailed breakdown. Calculation, API enrichment, sorting,
filtering, pagination, missing values, and bookmarks are covered by tests. All 506
Python tests passed with one optional skip. Both JavaScript test files and package
checks passed. A current Red snapshot was visually checked in the local browser.

The tagged release b04057e was deployed sequentially to both games after each verified
compressed cold backup and saved-game smoke check. The coordinator was stopped for
each deployment boundary and resumed after confirming no active transaction or holds.
Both games resumed healthy at maximum speed with 144 registrations. The board was
unchanged. Red's prior interval ended at 1,444 seconds and Blue's at 22,622 seconds.
New starts are 17:21:16 UTC for Red and 17:22:28 UTC for Blue. Coordinator rc24 resumed
at 17:22:30 UTC. Both games now include the earlier journal correction. No training
policy change was included with the PC ranking. See the
[Red receipt](validation/release-0.2.0rc26-red.json) and
[Blue receipt](validation/release-0.2.0rc26-blue.json).

The post-deployment sample confirmed new local progress independently of trading:
Red leveled Mew to 39 and Blue evolved Squirtle into Wartortle. Both stayed healthy,
unpaused, at maximum speed, with zero recovery reloads and 144 registrations. Red
had 31 rewards delivered and Blue 33, with no pending claims. The coordinator was
running, enabled, and ready, reporting 24 completed exchanges and no error. Public
Red served valid scores for all 234 boxed Pokémon. The public Blue page displayed
its Power ranking and all-box controls in the browser. Free disk space was
16,892,948,480 bytes. The existing monitoring automation now includes rc26 deployment
identities and the training-churn investigation. See
[the follow-up evidence](validation/pc-power-0.2.0rc26.json).
