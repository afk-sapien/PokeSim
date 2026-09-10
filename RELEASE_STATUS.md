Experimental beta validation

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
- A fresh 48-hour soak and a separate fresh-game campaign started September 10, 2026 at 21:04:25 UTC on published image `sha256:e457c235f49e52dfd66f9bb2995eaa9053b7770d40f11de403ec6dcabb3b59ad`. The soak is due September 12 at 21:04:25 UTC. Both began healthy. Completion is not yet established.

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
