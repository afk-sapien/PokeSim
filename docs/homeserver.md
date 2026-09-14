# Homeserver deployment

Updated September 14, 2026 (America/Los_Angeles).

| Edition | URL | Container on `servarr` | Port | Data directory |
| --- | --- | --- | --- | --- |
| Red | https://pokesim-red.tynet.app | `pokesim` | 8930 | `/docker/pokesim/data` |
| Blue | https://pokesim-blue.tynet.app | `pokesim-blue` | 8940 | `/docker/pokesim-blue/data` |

The old https://pokesim.tynet.app address remains a Red alias. Each game retains its own
ROM, saves, party, boxes, journal, and notification configuration. Red runs at speed 1,
and Blue retains its existing unlimited speed setting.

Blue runs `pokesim:0.2.0rc12-66b226f` from commit
`66b226f6d2a565c5281692a285d419d79fabaf2f`. Its image ID is
`sha256:8d2e402895f59e9493269244f95d55db49c5d907a0291f4f2028415831ef1f11`. The source archive is unpacked at
`/docker/pokesim/releases/0.2.0rc12-66b226f`.

Red runs `pokesim:0.2.0rc13-17cd997`, commit
`17cd9973f3fbcfef2cfb3838f02f0d2e759b7b75`. Its image ID is
`sha256:6da126690a9b7484af2b2f39b2c60a3c3e3da561f2118c268312bdcae11861a2`.
The source archive is at `/docker/pokesim/releases/0.2.0rc13-17cd997`.
Blue was not restarted during the reserve preparation fix deployment.
PyBoy remains at version 2.7.0. Game data and sprites remain separate mounts.

The release includes persistent playtime, the four-page interface, stall recovery,
bounded collection objectives, and return paths through Victory Road. Live displays
activity and the last achievement. Health and adventure progress are separate signals.
The rc8 upgrade adds persistent postgame project rotation, level training, random
starters for new adventures, and confirmed ground-item detours. Existing adventures
retain their Pokémon and continue from their latest autosaves.

The read-only trade board runs as `pokesim-broker` on
[servarr port 8950](http://192.168.2.147:8950). Its compose directory is
`/docker/pokesim-broker`, with a local `.env` setting the game-data path. It mounts only
read-only game data and polls the two games through the host gateway. It has no ROM or
save mounts and cannot execute trades. See [trade-review.md](trade-review.md) for the
copied-save rehearsal and the still-required approval of a specific live exchange.

## Routing

Nginx Proxy Manager on `proxy` (`192.168.2.140`) manages both routes. Host 55 serves Red
and its old alias. Host 57 serves Blue. Both forward to `servarr` (`192.168.2.147`) and
use the existing wildcard certificate, certificate ID 10. Streaming and TLS settings
match the original Red route. The hostnames resolve through the existing home DNS setup.

Nginx runs as UID 1000 on this proxy. Configuration tools must preserve that ownership
for new log files. A root-owned log file can pass a root configuration check but prevent
the running service from reloading.

## Backups and rollback

The rc13 deployment updated Red only:

- Red: `/docker/pokesim/backups/20260914T233110Z-rc13/before.tar`
- Previous Red image: `pokesim:0.2.0rc10-6a23720`.
- Blue remains on rc12 and retains its existing cold backup below.

Red's latest save loaded successfully before startup. See the
[rc13 deployment receipt](validation/release-0.2.0rc13.json).

The rc12 deployment updated Blue only:

- Blue: `/docker/pokesim-blue/backups/20260914T224357Z-rc12/before.tar`
- Previous Blue image: `pokesim:0.2.0rc10-6a23720`.
- Red remains on rc10 and retains its existing cold backup below.

Blue's latest save loaded successfully before startup. See the
[rc12 deployment receipt](validation/release-0.2.0rc12.json).

The rc10 deployment retains fresh cold backups:

- Red: `/docker/pokesim/backups/20260914T211056Z-rc10/before.tar`
- Blue: `/docker/pokesim-blue/backups/20260914T211200Z-rc10/before.tar`
- Previous image: `pokesim:0.2.0rc9-8ca0271`.

Both latest saves loaded successfully before startup. See the
[rc10 deployment receipt](validation/release-0.2.0rc10.json).

The rc9 deployment retains fresh cold backups:

- Red: `/docker/pokesim/backups/20260914T202947Z-rc9/before.tar`
- Blue: `/docker/pokesim-blue/backups/20260914T203028Z-rc9/before.tar`
- Previous image: `pokesim:0.2.0rc8-addfb73`.

Both latest saves loaded successfully before startup. See the
[rc9 deployment receipt](validation/release-0.2.0rc9.json).

The rc8 deployment has fresh cold backups of both data directories and compose files:

- Red: `/docker/pokesim/backups/20260914T194434Z-rc8/before.tar`
- Blue: `/docker/pokesim-blue/backups/20260914T194332Z-rc8/before.tar`
- Previous image: `pokesim:0.2.0rc7-ca32f70`.

Both latest saves loaded successfully in the rc8 image before their live processes
started. The deployment receipt is [release-0.2.0rc8.json](validation/release-0.2.0rc8.json).

The final progress release has cold backups of both complete data directories and
compose files:

- Red: `/docker/pokesim/backups/20260914T184015Z-rc7-final/before.tar`
- Blue: `/docker/pokesim-blue/backups/20260914T183932Z-rc7-final/before.tar`
- Image before the final fallback: `pokesim:0.2.0rc7` at commit `ca76c83`.

The first deployment of this release also retained the previous clock revision:

- Red: `/docker/pokesim/backups/20260914T183341Z-rc7/before.tar`
- Blue: `/docker/pokesim-blue/backups/20260914T183256Z-rc7/before.tar`
- Image before this release: `pokesim:clock-20260913`.


The app-clock revision has fresh cold backups:

- Red: `/docker/pokesim/backups/20260914T034421Z-clock/before-clock.tar`
- Blue: `/docker/pokesim-blue/backups/20260914T034421Z-clock/before-clock.tar`
- Image before this revision: `pokesim:watch-20260913`

The live-layout revision has fresh cold backups:

- Red: `/docker/pokesim/backups/20260914T032900Z-watch/before-watch.tar`
- Blue: `/docker/pokesim-blue/backups/20260914T032900Z-watch/before-watch.tar`
- Image before this revision: `pokesim:gui-20260913`

The earlier migration backups below remain available.

Full cold backups were created before migration. Each archive contains the data directory
and deployment configuration. Existing ROM mounts were preserved.

- Red: `/docker/pokesim/backups/20260914T030357Z/before-gui.tar.gz`
- Blue: `/docker/pokesim-blue/backups/20260914T030357Z/before-gui.tar.gz`
- Proxy database and prior Red route: `/docker/npm/data/pokesim-url-backup-20260914` on `proxy`
- Prior application image: `pokesim:ascent-20260913`

To roll back a game, stop its container and make a fresh backup first. Restore its old
compose configuration and the complete matching data archive, then start that compose
project. Restoring the archive reverts progress made since the backup. Keep the current
data separately so that progress remains recoverable. Do not mix the Red and Blue archives.
Proxy changes should be reverted per host through Proxy Manager. Avoid restoring its
entire database over unrelated configuration changes.

## Verification

The current rc13 code passed 387 tests, with one optional checkpoint test skipped.
Red resumed with 111 registered entries. Blue remained running and reached 116 after
catching Kangaskhan. Both services and all 12 public checks passed. No multi-day pass
is claimed. The per-release receipts above preserve the exact validation and images.

### Historical rc8 verification

The rc8 suite passes 378 tests with one optional supplied-checkpoint test skipped.
Both live services resumed with eight badges and their existing dex counts, 111 for
Red and 113 for Blue. Startup and subsequent samples were healthy with no save reloads.
All 12 public page, health, and sprite checks passed across the two sites.

Monitoring continues every 30 minutes through the task heartbeat. The private durable
sample history lives at `data/operations/live-samples.json`. An initial sample caught
Red's planned deployment downtime, before the post-deployment baseline. This is recorded
as an interruption and is not an endurance failure after startup. See
[operations-monitor.md](operations-monitor.md) for the monitoring and improvement process.
No multi-day rc8 endurance pass is claimed yet.

### Historical rc7 verification

The release suite passes 350 tests, with one optional supplied-checkpoint test skipped.
The browser controller test and package resource checks pass. Both copied saves loaded
in the release image with eight badges and six party members.

Two simulated hours on the final policy produced five new trainer-victory events in Red.
Blue's fresh plateau checkpoint returned to Viridian, with trainer victories and level
gains. Both replays prohibit rewinds. They still record local policy recoveries, so these
results do not prove that every objective succeeds or replace multi-day endurance.
See the per-game progress records under `docs/validation`.

Live observation passed the former ten-minute recovery interval for both games. Every
sample remained healthy, both runs advanced frames and positions, and both reported
zero save reloads. Blue produced a new level-up event after deployment. The observation
record is `docs/validation/live-progress-0.2.0rc7.json`. Multi-day endurance remains open.


Both copied saves loaded in the new image before deployment and retained eight badges
and six party members. Both live containers resumed their existing autosaves and passed
health checks. All six pages, the Pokédex status API, PNG sprites, and edition-specific
Atom feed URLs were checked over HTTPS. The original hostname still serves Red.
