# Current deployment: rc22, accurate PC release messages

The journal now recognizes withdrawals whose party entry appears before the box entry
is removed. Recent arrivals are matched by species and nickname, survive checkpoint
restart, expire after a bounded interval, and are canceled when the partner is deposited.
The opposite write order confirms the matching individual's population instead of the
whole collection. This changes journal detection only. Release and trading policies,
Pokémon, resources, and historical journal records remain intact.

A 72,022-frame copied Red replay previously reported two releases. The candidate retains
the genuine Geodude release and suppresses the false Tentacruel release. CRICKET is in the
party, and the game explicitly says it was taken out. Both replays used normal saved
policy controls, the live observation cadence, maximum speed, and zero rewinds. See
[the comparison](docs/validation/pc-release-events-0.2.0rc22.json).

All 458 Python tests passed, with one optional test skipped. Both JavaScript test files
passed. The full suite ran outside the sandbox after its local API client stalled
inside the sandbox. Package builds and runtime resource checks passed.

Both games, the board, and coordinator now run `pokesim:0.2.0rc22-49403d7` from
`49403d76fd169b2c106d3de908807f48bfc1635f`. Fresh compressed cold backups passed integrity
checks and both latest saves loaded successfully. All 12 public checks passed. Both
games are healthy at maximum speed with zero recovery reloads and 132 registrations.
Ten automatic trades have completed. All seven Red rewards and ten Blue rewards are
delivered. The deployment starts new endurance intervals. See
[the release receipt](docs/validation/release-0.2.0rc22.json).

# Previous deployment: rc21, complete Articuno's current puzzle

Articuno expeditions prepare the Seafoam boulder puzzle before using Surf. The planner
clears space, pushes both designated boulders into their holes, and then returns to the
standing encounter. It preserves completed drops after reentry and never plans a walk
into a hole. A Strength partner is required. Strong-current refusals clear the pending
Surf action instead of repeating the rejected menu.

The same copied Blue checkpoint previously spent a 36,000-frame test repeating Surf.
The candidate solved the puzzle and caught Articuno after 17,646 frames, then continued
toward storage. Both tests used zero rewinds. No puzzle flags, Pokémon, or resources
were injected. All 453 Python tests passed, with one optional test skipped.
See [the copied-save comparison](docs/validation/articuno-current-0.2.0rc21.json).

The monitor now retains legendary retry state and the last four legendary outcomes.
The homeserver guide reflects the current image, compressed backups, rewards, and coordinator settings.
Red's earlier Moltres path failure has a copied reproduction preserved. Its live
expedition subsequently succeeded without another runtime change. The live rc20 interval gained two automatic trades,
two Red registrations, and three Blue registrations without save reloads or restarts.

Both games, the board, and coordinator run `pokesim:0.2.0rc21-339d9a0`, tagged commit
`339d9a0d840f87a5b829955743d9124174d9ed8b`. Fresh compressed cold backups passed gzip
integrity checks and both current saves loaded before rollout. The two backups total
117,561,751 bytes. No old backups or live data were removed. All 12 public checks passed.

Both live games then caught Articuno, confirmed by Red event 8709 and Blue event 3806.
Red reached 125 registrations and Blue reached 128. Both are healthy, unpaused, at maximum
speed, with zero recovery reloads. Automatic trading remains enabled with seven completed
exchanges and no coordinator error. Red's five Championship rewards and Blue's six are
all delivered. This begins a new endurance interval.
See [the release receipt](docs/validation/release-0.2.0rc21.json).

At the 10:20 UTC followup, Red had caught Moltres in event 8753 and both games held all
three legendary birds and Mewtwo. Both reached 129 registrations with unchanged container
starts and zero reloads. Eight automatic exchanges completed. All six Red rewards and
eight Blue rewards were delivered. No further runtime change or deployment was needed.
The monitor now follows continued progress, PC transfer journal accuracy, and storage growth.
See [the followup record](docs/validation/monitor-20260915-1020.json).

# Previous deployment: rc20, preserve missed legendary encounters

A failed Articuno, Zapdos, Moltres, or Mewtwo encounter now returns after leaving its
room and a persistent retry delay. The repair clears only its encounter-finished and
hidden-object bits. Spent items, damage, money, party, boxes, and adventure progress
stay intact. Previously missed encounters are eligible. Registered legendaries remain
resolved after trading or release. Only verified Red and Blue ROMs receive repairs.

Empty balls, full storage, and a 50-attempt capture limit cause retreat. Planned
legendary interactions require room and at least five Ultra Balls or a Master Ball.
Shopping targets twenty Ultra Balls, with ordinary healing, storage, and objective
backoff retained. Repeat failures wait longer. Repairs create journal entries and a
fresh checkpoint. Pending delays and attempt counts survive checkpoint restarts.

The game-data parser now preserves an unused numeric toggle-object entry. Existing
verified bundles are normalized without changing their files. This fixes shifted
visibility flags for Mewtwo, Articuno, and items in later maps.

All 448 Python tests passed, with one optional test skipped. Both JavaScript test
files passed. Copied saves reproduced both knockout and empty-ball failures, retained
pending recovery through a restart, and continued without recovery rewinds. A guided
return selected the restored Mewtwo after the normal retry wait, then ordinary policy
navigation and battle controls caught it. The empty-ball run instead continued through
League rematches. See [the replay evidence](docs/validation/legendary-recovery-0.2.0rc20.json).

Both games, the board, and the coordinator run `pokesim:0.2.0rc20-39f409b`, tagged
commit `39f409be5754b1ed7c6f44503a1e7047a1b514f8`. Fresh cold backups and current-save
load checks passed. Both games and the board are healthy, with the games unpaused at
maximum speed and zero recovery reloads. All 12 public checks passed. The coordinator
runs with automatic trading and Championship rewards enabled and no reported error.
Its Compose configuration now disables the inherited HTTP probe because this worker
has no web server. Monitor its public status and transaction records instead.

Red retained 122 registrations and Blue retained 124, including both Mewtwo catches.
Red's previously missed Moltres was restored automatically, confirmed by journal event
8655, after the pending retry in event 8653. Neither game was rewound. Reward ledgers
remain at three delivered for Red and five for Blue, with no pending claims. The existing
monitor follows future legendary attempts and resource exhaustion. This rollout starts
a new endurance interval. See [the deployment receipt](docs/validation/release-0.2.0rc20.json).

# Previous deployment: rc19, complete legendary expeditions

Mewtwo remains a normal Cerulean Cave encounter. Legendary targets now have a distinct
postgame priority and a longer bounded expedition budget. Route progress and completed
route battles prevent false idle cancellations. These trips reserve capture resources,
skip incidental catches and optional detours, prepare Ultra Balls and Repels, and use
a strong lead. Crowded bags may sell expendable battle boosters to make supply space.

Missing legendaries receive status moves and balls, without damaging attacks. Mewtwo's
Barrier had made ordinary damage estimates look safe even when a critical hit could
ignore the defensive boost and knock it out. Sleep may be reapplied after waking.
Unexpected move menus cannot issue damaging attacks against a missing legendary.
Resolved encounters stop the objective instead of repeated interaction with an empty spot.

All 433 Python tests passed, with one optional test skipped. Both JavaScript test
files passed, and built packages passed runtime resource checks.

A full copied Red expedition caught Mewtwo and continued the adventure. Blue's reproduced
failed encounter succeeded from the copied approach checkpoint using sleep and six Ultra
Balls. Both checks used normal gameplay with zero rewinds and no Pokémon or encounter
injection. See [the replay evidence](docs/validation/mewtwo-expeditions-0.2.0rc19.json).

Both games, the board, and the coordinator run `pokesim:0.2.0rc19-1ba1fbb`, tagged commit
`1ba1fbb878002608adae646c771fcff92d078ef3`. Fresh cold backups and current-save load
checks passed. All 12 public checks passed. Both games are healthy, unpaused, at maximum
speed, with zero recovery reloads since deployment. Automatic trading and Championship
rewards remain enabled. Red retained two delivered rewards and Blue retained four.

Both live games caught level-70 Mewtwo after deployment. Red reached 120 registered
entries, confirmed by journal event 8597. Blue reached 123, confirmed by event 3731.
Both catches occurred in Cerulean Cave B1F with zero recovery reloads. The existing
monitor now specifically follows legendary expeditions and confirmed captures. This deployment begins a new endurance interval.
See [the release receipt](docs/validation/release-0.2.0rc19.json).

# Previous deployment: rc18, repeatable Championship rewards

Every newly observed League victory earns one uniformly random level-5 Bulbasaur,
Charmander, Squirtle, Eevee, Omanyte, Kabuto, Aerodactyl, or Mew. Claims persist through
rewinds and interrupted delivery. A full PC keeps the claim pending. The scoped
coordinator delivers rewards without a roster requirement, reward cooldown, trade
proposal, or individual approval. The first victory observed after upgrading begins
the ledger. Earlier victories are not backfilled.

League rematches remain postgame options even with plenty of money. The initial Eevee
evolution remains random and persistent. Later Eevees can fill missing forms.
The board displays rewards separately from exchanges. Existing saves and trading
protections remain intact. The older one-time Mew policy should stay disabled.

All 422 Python tests passed, with one optional test skipped. Both JavaScript test
files passed. Built packages passed runtime resource verification.

Using simulated earned claims, a copied pair each received six rewards, recovered a committed delivery after both
emulators restarted, and reloaded subsequent checkpoints. All preexisting party and
boxed Pokémon, items, badges, and registrations survived each delivery. A seventh
claim remained pending when storage filled. See
[the rehearsal](docs/validation/championship-rewards-0.2.0rc18.json).

Both games, the board, and the coordinator run `pokesim:0.2.0rc18-2b7365b`, tagged commit
`2b7365b583dc0b2f9c1eba0214658400e194e3ef`. Both current saves passed cold-backup and
load checks. Rewards and automatic last-copy trading are enabled. The one-time Mew
event is disabled. All 12 public endpoint checks passed, and the browser board displays
the new policy. Both games are healthy, unpaused, at maximum speed, with zero recovery
reloads since deployment. This starts a new endurance interval.

The resumed coordinator completed a third automatic exchange. Both games received
Alakazam, bringing Red to 117 registered entries and Blue to 120. No new Championship
had occurred at the verification sample, so live reward counters were still zero.
The existing monitor now watches earned, delivered, and pending reward claims.
See [the release receipt](docs/validation/release-0.2.0rc18.json).

# Previous deployment: rc17, varied choices and last-copy trades

The deployed release adds persisted random fossil and Eevee evolution choices for new runs.
Existing choices remain intact. Optional last-copy trades require a new Pokédex entry
for the recipient and continue protecting active parties and projects. An optional
one-time postgame Mew event uses the existing scoped coordinator, backed-up checkpoints,
staged inventory checks, and durable recovery.

All 416 Python tests and seven JavaScript tests passed, with one optional checkpoint
test skipped. The packages built and runtime resources passed verification. A copied
pair recovered a Mew distribution after an interruption following durable commitment,
then completed a last-copy Hitmonchan and Hitmonlee trade. Repeated delivery and a
pointless return exchange were rejected. Subsequent autosaves reloaded successfully.
See [the rehearsal](docs/validation/choices-events-trading-0.2.0rc17.json).
A subsequent copied gameplay check withdrew Mew, trained it from level 5 to level 12,
and completed its training objective. See [the gameplay check](docs/validation/mew-training-0.2.0rc17.json).

Both games, the board, and the coordinator run `pokesim:0.2.0rc17-646b32b`, tagged commit
`646b32b4be0f4671d32ded62963836e654af612f`. Both current saves loaded successfully after
fresh cold backups. Red retained 116 registered entries and Blue retained 119. Both are
healthy and unpaused at unlimited speed. All 12 public endpoint checks passed.
Last-copy sharing is enabled and the board displays its proposals. The Mew event is
supported but disabled while a harder Championship reward design is discussed.
See [the release receipt](docs/validation/release-0.2.0rc17.json).

# Previous deployment: rc16, automatic trading enabled

Red, Blue, the board, and the coordinator use `pokesim:0.2.0rc16-caa092b`, tagged commit
`caa092bf76d3b73ce892575ece41480b5a455d80`. Both adventures are healthy at unlimited
speed, with zero observed save reloads. Fresh cold backups and current-save checks
passed. Red has 115 registered entries and Blue has 118 after their first automatic
exchange. Red received MOCHI the Vulpix and evolved it into Ninetales. Blue received
DIRTNAP the Machoke, which evolved into Machamp during the exchange.

The scoped coordinator runs as UID 10001 with all capabilities dropped and no Docker
socket. Private tokens authorize only trade controls. It can stage, verify, journal,
and recover useful spare exchanges while protecting active teams, current projects,
last copies, and best retained partners. Its interval is 15 minutes.

All 406 Python tests and seven JavaScript tests passed, with one optional checkpoint
test skipped. Packages built and runtime resources passed verification. Five copied
exchanges passed, including a coordinator crash and both game restarts with durable
holds. See [the scoped rehearsal](docs/validation/scoped-trading-0.2.0rc16.json).

All 12 public endpoint checks passed. See [the release receipt](docs/validation/release-0.2.0rc16.json).

The owner explicitly approved live automatic trading on September 15, 2026 UTC.
Both private and public policies are enabled for useful spare exchanges every 15
minutes. Individual trades need no further approval. The first automatic exchange
completed at 06:32 UTC. Both games journaled it exactly once, released their holds,
and retained the trade marker in subsequent autosaves. Neither container restarted.
See [the first live exchange record](docs/validation/monitor-20260915-0659.json).

The earlier root coordinator proposal was rejected and replaced. No privileged
coordinator was started. The currently deployed service has access only to the two
configured data directories, read-only ROMs and game data, and its recovery directory.

# Previous deployment: both games on rc14

Both adventures run `pokesim:0.2.0rc14-1473f1d`, tagged commit
`1473f1daf16acf6f66ef8a9067bef0eda16fb5ff`. PC now sorts across selected or all boxes
by level, total DVs, total stat experience, experience, Pokédex number, species,
nickname, or box order. Totals appear on every card and in the detail view.

All 388 Python tests passed, with one optional test skipped. All three PC JavaScript
tests and the screen suite passed. Packages built offline and runtime resources passed
verification. All 12 public endpoint checks passed, and the six public PC assets match
the tagged source. Browser checks verified rankings and the detail totals.

Both latest saves loaded successfully before startup, with cold backups recorded.
Red retained 112 registered entries and Blue retained 116. Both run at `SPEED=0`,
with healthy workers and zero save reloads after startup. The release includes the
previously queued partial-training accounting fix. These checks do not establish
multi-day endurance. See [the release receipt](docs/validation/release-0.2.0rc14.json).

# Previous deployment: Red rc13, Blue rc12

Red runs `pokesim:0.2.0rc13-17cd997` from tagged commit
`17cd9973f3fbcfef2cfb3838f02f0d2e759b7b75`. Its current save loaded successfully
before startup, and its party and 111 registered entries were preserved. Blue remains
on rc12 without a restart. Both services are healthy and all 12 public checks passed.
See [the deployment receipt](docs/validation/release-0.2.0rc13.json).

Reserve training now recognizes the partner first reaching a stable party snapshot as
a one-time preparation milestone. This starts a fresh idle window, survives reloads,
and retains the overall expedition deadline. All 387 tests passed, with one optional
checkpoint test skipped. The 40 release checks passed, both packages built, and all
61 packaged runtime files match the release commit.

The two-hour Red comparison gained six levels in each version. The candidate also
picked up two items and won six trainer battles, including a League rematch. It used
33 local policy recoveries versus 38 for the baseline. Neither run caught a new species.
Blue's Seafoam regression was unchanged. See
[the comparison](docs/validation/training-preparation-0.2.0rc13.json).

Blue caught a level-25 Kangaskhan in the live Safari Zone, reaching 116 registered
entries. Both live reload counters remain zero. Red's new release has only startup
verification so far. Sustained collection and multi-day endurance remain open.

## Partial training accounting, included in rc14

The idle-abandon path now records selected-partner experience as partial progress,
matching the overall timeout path. A live project gained 524 XP but was incorrectly
marked deferred. The fix retains the idle deadline and ordinary retry delay, while
avoiding an escalating failure penalty for a productive attempt. Existing history
is preserved. All 388 tests pass, with one optional test skipped.

A 72028-frame replay matches the deployed baseline's gameplay, reaching full HP and PP
after 10536 frames at Indigo Plateau and then training another reserve. The fix is
included in rc14 on both live games. See [the evidence](docs/validation/partial-training-20260915.json).

# rc12 deployment record

Blue runs `pokesim:0.2.0rc12-66b226f`, built from tagged commit
`66b226f6d2a565c5281692a285d419d79fabaf2f`. It has a fresh cold backup, and its latest
save loaded successfully before startup. Red continues on `pokesim:0.2.0rc10-6a23720`
without a restart. Both services are healthy, and all 12 public endpoint checks passed.
See [the deployment receipt](docs/validation/release-0.2.0rc12.json).

Blue had exhausted its attacking PP while repeatedly falling through Seafoam floor
holes and being swept downstairs by the current. Routine navigation now avoids those
holes and uses the ladders, including when an old learned step records a fall. This
release excludes the held rc11 obstacle experiment.

Validation:

- 386 tests passed, with one optional checkpoint test skipped. The 41 release and focused checks passed. The lock resolves offline, packages build, and all 61 packaged
  runtime files match the committed source without private game artifacts.
- The old copied Blue save made no experience or dex progress in 72026 frames.
- The fix restored the whole party's HP and PP after 7632 frames at Fuchsia Pokémon
  Center. Over 144014 frames it picked up Full Restore and gained a level. Its dex stayed
  at 115, and it used two local policy recoveries. Rewinds were disabled.
- Red's 180020-frame regression reproduced the baseline's mode totals and final party
  exactly. No Red maintenance restart was needed for this active Blue failure.
- The live Blue run has already left Seafoam and restored its main team's PP. The first
  post-deployment sample placed it on Route 11 with zero save reloads. A later
  sample recorded PEACH reaching level 32 in the live adventure.

See [the copied-save evidence](docs/validation/seafoam-exit-0.2.0rc12.json). Articuno's
boulder puzzle solver, better collection budgeting, and multi-day endurance remain open.

# rc10 release record

The rc10 rollout put both games on `pokesim:0.2.0rc10-6a23720`, built from tagged commit
`6a23720ec5f6eb97fd581c0721cb51c5f64a1c44`. Each adventure has a fresh cold backup,
and each latest autosave loaded successfully in the new image before startup. Both
services are healthy. All 12 public endpoint checks passed. See the
[deployment receipt](docs/validation/release-0.2.0rc10.json).

The rc9 monitoring interval confirmed live level gains in both games with zero observed
save reloads. Red also picked up Max Revive before this deployment. Memory stayed near
112 MB per process. These observations do not establish multi-day endurance.

Release rc10 fixes false training completion during PC withdrawal. The game briefly
combines the new partner's species and experience with the previous party slot's level.
Training now accepts progress during battle or after returning to the overworld. Missing
party entries also no longer reset the training idle timer.

Validation:

- 383 tests passed, with one optional supplied-checkpoint test skipped. The lock resolves
  offline, both packages built, and all 61 packaged runtime files match the committed code.
- The baseline withdrawal incorrectly completed a level-50 Graveler project at frame 1662,
  when the party slot briefly displayed level 100 with only 71833 experience.
- With the fix, a 72002-frame replay kept that project active, gained 8088 experience,
  and recorded the actual level 44. Blue's current-save replay also gained levels over
  144012 frames. Both copied dex counts remained unchanged.
- Replays disable rewinds and do not validate the live save-recovery guard. Red used seven
  local policy recoveries and Blue used nine. Collection efficiency remains open.
- The earlier duplicate-species hypothesis was incorrect. Historical director outcomes
  remain preserved and may include inflated pre-rc10 training completions.

See [the transfer regression evidence](docs/validation/training-transfer-0.2.0rc10.json)
and [the monitoring plan](docs/operations-monitor.md).


## Held rc11 experiment, not deployed

Commit `6de8c1b` applies observed solid-object collisions to remembered steps on the
current map. A saved Victory Road route demonstrably crossed an occupied boulder square.
All 386 tests pass, but longer copied-save comparisons do not support deploying this
candidate on its own. Red's dex stayed at 111 in both runs. The candidate used 42 local
recoveries versus 43 for rc10, but produced fewer level gains, trainer victories, and
pickups. Blue's comparison remained unchanged. Both games stayed on rc10 after that comparison. The later Seafoam fix was released
separately as rc12. The experiment is retained on `codex/held-navigation-candidate`.

The rc11 packages are local candidate artifacts. No rc11 tag or deployment exists.
An earlier, broader candidate image `pokesim:0.2.0rc11-54569f0` was built but is unused.
It does not contain the final narrower candidate. Do not deploy that image.
See [the comparison evidence](docs/validation/navigation-candidate-0.2.0rc11.json).

# Previous deployment: 0.2.0rc9

Red and Blue run `pokesim:0.2.0rc9-8ca0271`, built from tagged commit
`8ca0271dd4f76d8fb74574efaa464b4bbf90ac43`. Fresh cold backups retain both adventures.
Each latest autosave loaded in the new image before startup. Both services are healthy,
and all 12 public endpoint checks passed. See the
[deployment receipt](docs/validation/release-0.2.0rc9.json).

The first rc8 monitoring check found Blue progressing at 115 owned entries, with no
save reloads. Red remained at 111 with exhausted attacking PP. Its copied checkpoint
reproduced a route through reset Victory Road gates that the game no longer allowed.
The fix rejects those remembered steps and takes a reachable ladder to the upper puzzle.

Validation:

- 380 tests passed, with one optional supplied-checkpoint test skipped. After the version
  update, all 38 release and soak regressions passed. The lock resolves offline.
- The source archive and wheel built successfully. All 61 packaged runtime files match
  the committed source, and neither package includes private game artifacts.
- Red's 432028-frame replay gained four levels, won two trainer battles, and collected
  TM Explosion. Its dex stayed at 111. It used 25 local policy recoveries.
- Blue's 144020-frame regression replay gained experience and won a trainer battle.
  Its copied dex stayed at 112. It used 13 local policy recoveries.
- These replays disable rewinds and do not validate the live save-recovery guard.
  Collection efficiency and multi-day endurance remain open. The monitoring record also
  identified a training identity issue involving duplicate species for followup.

[Red evidence](docs/validation/red-progress-0.2.0rc9.json),
[Blue evidence](docs/validation/blue-progress-0.2.0rc9.json), and
[the stalled baseline](docs/validation/red-stall-baseline-0.2.0rc9.json).

# Previous deployment: 0.2.0rc8

The rc8 release added persisted starter selection, postgame project rotation,
training toward level milestones, and increasing retry delays for repeated failures.
It includes the previously committed trade registration correction. Automatic trading
and planner integration with external trade requests remain future work.

Red and Blue now run image `pokesim:0.2.0rc8-addfb73`, built from commit
`addfb736bd14818ac8a32357aac09ce24d7c382f`. Both latest saves loaded in the image before
deployment, both services resumed with their existing parties and dex counts, and all
12 public endpoint checks passed. Fresh cold backups retain the previous rc7 deployment.
See [the deployment receipt](docs/validation/release-0.2.0rc8.json) and
[monitoring process](docs/operations-monitor.md). Multi-day live endurance is outstanding.

Candidate validation:

- 378 Python tests passed, with one optional supplied-checkpoint test skipped.
- The locked dependencies resolve offline. The rc8 source archive and wheel build and
  pass the package resource and private-artifact checks. Existing rc7 artifacts are retained.
- The ground-item followup collected Max Revive and TM47 Explosion in an unmodified
  copied Red checkpoint. Both inventory counts increased by one and both pickups
  appeared as confirmed journal events. The 120000-frame replay disabled rewinds and
  used three local policy recoveries. [Pickup evidence](docs/validation/ground-pickups-0.2.0rc8.json).
- The longer postgame and first-gym records below were made at commit `d016ac4`, before
  the ground-item followup. They do not validate the subsequent detours over those budgets.
- Two simulated hours on a copied Red checkpoint produced a Moltres catch, growing the
  dex from 111 to 112, three trainer victories, and several level gains. The replay used
  34 local policy recoveries. [Red evidence](docs/validation/red-progress-0.2.0rc8.json).
- Two simulated hours on a copied Blue checkpoint produced level gains, a completed
  League rematch, and travel to Cerulean Cave. The dex remained at 113 entries and the
  replay used 36 local policy recoveries. [Blue evidence](docs/validation/blue-progress-0.2.0rc8.json).
- Both copied-save replays disable rewinds, so their zero rewind counts do not validate
  the live recovery guard. They demonstrate bounded gameplay progress only.
- All three starters received the Pokédex in automated opening tests. Separate seed 1
  runs with the default thorough pace earned Brock's badge with all three choices and
  no save reloads. Bulbasaur required a longer frame budget. The runs had one, one, and
  two blackouts for Bulbasaur, Charmander, and Squirtle respectively. These are first-gym
  checks, not complete campaign passes. [Starter evidence](docs/validation/starters-0.2.0rc8.json).

## Previous deployment: 0.2.0rc7

September 14, 2026. The current release consolidates the deployed four-page interface,
Pokédex and PC views, persistent play clock, storage fixes, and the new expedition and
Victory Road return-path fixes. PyBoy remains pinned to 2.7.0.

Copied-save checks reproduce Blue's stale planning timestamp and Red's restricted
Victory Road loop. The revised policy has produced new trainer victories in Red and
resumed collecting in Blue. Replay evidence and the deployment receipt are recorded under `docs/validation`
and in `docs/homeserver.md`. The live release is tag `v0.2.0rc7`, commit `ca32f70`. Two simulated hours
are a bounded regression check. Multi-day live endurance remains outstanding.

The trade board is read-only. No live exchange has been approved or executed by this
release. A subsequent committed executor correction and copied-save trade rehearsal
are documented in `docs/trade-review.md`. That correction is not active in the live games. Historical release notes below describe earlier versions and their limits.

Experimental beta validation

Version 0.2.0rc6 fixes repeated attempts to fight unidentified wild ghosts in Pokémon Tower before obtaining the Silph Scope. The battle policy follows the original game condition for unidentified ghosts and chooses escape. Trainer battles, identified ghosts, and encounters outside the Tower keep normal battle decisions. All 214 Python tests passed, including ten new regression cases.

The ongoing rc3 soak first recorded automatic checkpoint recoveries at 07:09, 07:25, 07:40, and 07:55 UTC on September 11 after the 900-second battle timeout. Service health and monitoring continuity remained intact. The first recovery was in a trainer battle and its specific cause has not been established. Later repeated recoveries occurred in an unidentified wild ghost encounter on Pokémon Tower 3F. A copied checkpoint remained in battle after 1,818 frames with the old policy. The corrected policy escaped in 174 frames with unchanged party HP and inventory. The [recovery report](docs/validation/ghost-recovery-0.2.0rc6.json) records this bounded check.

The rc3 soak continues on its original image. It has automatic gameplay recoveries and cannot establish uninterrupted gameplay. It does not validate rc6, rc5, or the rc4 polling viewer. No completed 48-hour pass is claimed for rc6.

Version 0.2.0rc5 fixes repeated switching between a full evolution source box and a box with free space. The capacity rule now permits withdrawal when the party has a free slot and the requested partner is in the active box. In an isolated replay of a private checkpoint with a seeded Metapod evolution objective, the previous policy switched boxes 41 times over 12,024 frames without withdrawing. The fixed policy withdrew Metapod after 468 frames without switching boxes. All 204 Python tests pass, including four new regressions covering withdrawal, full-party capacity handling, missing partners, and exiting the box selector. The save format is unchanged.

The existing rc3 endurance run continues unchanged. It does not validate the rc5 policy fix or the rc4 browser polling behavior. No 48-hour pass is claimed for rc5.

Version 0.2.0rc4 updates the browser viewer. Frames are downloaded and decoded sequentially at up to 10 per second, failed downloads retain the last good image, and hidden tabs suspend frame downloads. The emulator and backend behavior are unchanged from 0.2.0rc3. Four JavaScript controller tests pass alongside the 200 Python tests. Chromium and Firefox checks verified slow-frame handling, invalid-frame recovery, and one request at a time.

The existing 48-hour run continues on the exact 0.2.0rc3 image below. It measures that backend and the MJPEG endpoint, not the new browser viewer. It has not completed yet.

Version 0.2.0rc3 shares a bounded navigation search across collection candidates, removing repeated whole-world route searches from one policy decision. Health thresholds are unchanged. The source archive now includes the Docker and Compose files required by its installation instructions. The test harness preserves failing health evidence and recognizes the saved Hall of Fame count after the game leaves the ceremony.

Current release validation:

- 200 local tests passed in the locked Python 3.12 environment, including two tests with a privately supplied ROM. Package resource and content-exclusion checks, extracted source-document links, and JavaScript syntax checks passed.
- A three-minute diagnostic replay of the copied pre-completion checkpoint completed with 60 healthy samples, maximum sampled activity age of 0.6 seconds, zero container restarts, and no out-of-memory kill. Shutdown completed in 0.89 seconds with exit code 0. The earlier replay reached 32.7 seconds of stale activity. Health thresholds were not relaxed.
- A separate replay with stack tracing enabled exited with code 139 during a traceback dump. Its cause is unconfirmed. The replay without tracing completed normally. This limitation is retained in the [candidate replay report](docs/validation/planner-replay-0.2.0rc3.json), which identifies the exact development image and changed runtime file hashes.
- This was a resumed diagnostic replay. It does not count as a fresh campaign or a 48-hour endurance pass.
- [Public CI](https://github.com/afk-sapien/PokeSim/actions/runs/34529764557) and the [release workflow](https://github.com/afk-sapien/PokeSim/actions/runs/34529764863) passed. An anonymous installation of the published `v0.2.0rc3` image passed checksum verification, local data preparation, healthy gameplay, frame and feed checks, non-root and read-only checks, graceful shutdown in 0.44 seconds, and checkpoint resume. The [installation report](docs/validation/public-install-0.2.0rc3.json) identifies the published artifact.
- The published source archive was checked for the Docker and Compose files. All 11 image layers were inspected, with no new findings beyond the previously reviewed dependency demo ROM, system file, and scanner false positives. The changed runtime files match the tested candidate hashes.
- A fresh 48-hour soak and a separate fresh-game campaign started September 10, 2026 at 21:04:25 UTC on published image `sha256:e457c235f49e52dfd66f9bb2995eaa9053b7770d40f11de403ec6dcabb3b59ad`. The soak is due September 12 at 21:04:25 UTC and remains in progress. The separate campaign reached the Hall of Fame at 22:57:30 UTC on September 10, confirmed by the final saved checkpoint and 109 healthy samples. It required one automatic checkpoint reload after the battle timeout guard reached 900 seconds, so this is not an uninterrupted campaign pass. The campaign container then exited cleanly with zero container restarts and no out-of-memory kill. The [campaign report](docs/validation/campaign-0.2.0rc3.json) records the exact tested image and limitations.

Earlier release validation:

Version 0.2.0rc2 is the first public source snapshot and downloadable Linux amd64 beta. It updates distribution metadata, installation instructions, and support links from the privately tested 0.2.0rc1 candidate. Gameplay and checkpoint behavior are unchanged. No prior private Git history is imported.

Completed validation before public publication:

- 190 local tests on the locked Python 3.12 environment, including two tests using a privately supplied ROM.
- Hosted Python 3.11 and 3.12 tests, package resource checks, and container builds for the earlier candidate.
- Offline non-root execution with a read-only root filesystem and ROM, checkpoint restart, corrupt-save fallback, cold backup restore, and server-enforced viewer mode.
- Authenticated HTTPS protecting the dashboard, API, controls, feed, screenshots, and stream, with no direct backend host port.
- A ten-minute authenticated stream, graceful shutdown in about six seconds, save resume, and stream reconnection.
- Upgrade from 0.1.0 to 0.2.0rc1 and rollback using the matching cold backup.

The [public CI run](https://github.com/afk-sapien/PokeSim/actions/runs/34522953662) passed Python 3.11 and 3.12 tests, package checks, and the container build. The [release workflow](https://github.com/afk-sapien/PokeSim/actions/runs/34523267945) also passed and published v0.2.0rc2.

A fresh installation cloned the public tag with Git credentials disabled and downloaded the image archive without authentication. Its SHA-256 and image ID matched the release manifest. Local data preparation, healthy gameplay, frame and feed endpoints, UID 10001, read-only root and ROM mounts, graceful shutdown, and checkpoint resume after restart all passed. This used a separate data directory and a privately supplied read-only ROM. The sanitized [installation report](docs/validation/public-install-0.2.0rc2.json) records the exact artifact.

Private vulnerability reporting is enabled. The original development repository remains private, and this public repository has no imported private history.

Endurance result and outstanding validation:

- The planned 48-hour run on image `sha256:789963c656dfe8f47ddc954773e6bd2dfbd1540331181017376d9ccc87a20318` started September 10, 2026 at 18:38:02 UTC and stopped at 20:13:52 UTC after the campaign reported unhealthy. Both isolated containers exited cleanly with zero container restarts and no out-of-memory kill. This is a failed endurance run, not a completed pass.
- The fresh-game campaign log records Champion and Hall of Fame entry at 20:12:20 UTC. Later saved policy metadata also records completion. The monitor stopped before recording a successful campaign result, so this evidence does not establish a completed healthy campaign validation.
- A Docker health probe received HTTP 503 at 20:12:58 UTC. The next probe succeeded at 20:13:29 UTC. The original harness discarded the failing API health details, so the exact cause cannot be established from that run alone. Raw logs and checkpoints are preserved privately.
- A diagnostic replay from a copy of the pre-completion checkpoint reproduced two health failures. The worker stayed alive while activity aged to 30.9 and 32.7 seconds. Thread dumps repeatedly located the worker in collection candidate selection calling navigation route search. The diagnostic container also exceeded its 20-second shutdown allowance and was killed with exit code 137, without an out-of-memory kill. This reproduced the planner stall in the earlier image. Version 0.2.0rc3 addresses the repeated searches, with replacement endurance validation still required. A resumed diagnostic replay does not count as a fresh uninterrupted campaign.
- Independent installation reports and broader hardware testing are welcome.

Known limits:

- Gameplay is experimental. The policy can get stuck or make poor choices. Completion across every seed, party, or collection route is not guaranteed.
- Linux amd64 and a clean Pokémon Red (USA, Europe) ROM are the current release targets. Blue, ARM, other games, and ROM hacks are not validated release targets.
- Resource measurements are incomplete. The project does not yet publish minimum hardware requirements or long-term storage estimates.
- The application has no built-in authentication. Use the documented proxy or a private network for remote access.
- The failed endurance run has not been replaced by a completed pass. This beta is intended for early feedback, not a claim of production readiness.

Distribution audit, September 10, 2026:

- The active repository is public `afk-sapien/PokeSim`. The previous repository is private and archived. The local active Git history contains only the reviewed public history.
- Anonymous downloads through the canonical repository name passed manifest checksum checks. The inspected published image archive matches SHA-256 `123e9be0fee2f6aad913131fcd9ccec6e2ba398f3d9d8a4c564cc8f25ef6290f`.
- Inspection of the public history, release Python packages, and all 11 published image layers found no Pokémon ROMs, game saves, generated Pokémon datasets, or project credentials. This is a scoped artifact audit, not a guarantee that all security defects have been found. The PyBoy dependency includes its own 32 KiB demo ROM, titled `DEFAULT-ROM`, which is not a Pokémon game.
- The published Python source archive omitted the Docker build and Compose files referenced by its README. The source manifest and package check now include those files and the referenced validation documents. Version 0.2.0rc3 includes this correction. For the existing beta, use the documented Git clone installation.
- The endurance harness now preserves failing API health details and marks stopped runs instead of leaving their status as running. The runtime fix is separate from these reporting changes.
- The published `v0.2.0rc2` tag and downloadable binaries remain unchanged. Current documentation records the failure and limitations, and future runtime fixes require a new version.
