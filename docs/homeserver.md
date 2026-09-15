# Homeserver deployment

Updated September 15, 2026 UTC.

| Edition | URL | Container on `servarr` | Port | Data directory |
| --- | --- | --- | --- | --- |
| Red | https://pokesim-red.tynet.app | `pokesim` | 8930 | `/docker/pokesim/data` |
| Blue | https://pokesim-blue.tynet.app | `pokesim-blue` | 8940 | `/docker/pokesim-blue/data` |

The old https://pokesim.tynet.app address remains a Red alias. Each game retains its own
ROM, saves, party, boxes, journal, and notification configuration. Both games run at
unlimited speed, with `SPEED=0` saved in their deployment configurations.

Both games run `pokesim:0.2.0rc28-bfba9fa` from tagged commit
`bfba9faa8c9f8f837675612b6ee47b3f5becf06f`. The image ID is
`sha256:0a5bc6563b31b9c57d9a0b989b1cf37a71ab96aea15179549cfce62c1ffe09ad`.
The source archive is unpacked at `/docker/pokesim/releases/0.2.0rc28-bfba9fa`.
PyBoy remains at version 2.7.0. Game data and sprites remain separate mounts.

Training projects now separate preparation from active work, favor nearby or already
available partners, and continue productive sessions toward their level targets.
Live distinguishes preparation from training. Both games passed saved-game loading
and resumed healthy at maximum speed with existing registrations. Verified private
cold backups are `/docker/pokesim/backups/20260915T175745Z-rc28/before.tar.gz` and
`/docker/pokesim-blue/backups/20260915T175917Z-rc28/before.tar.gz`.
Red's new endurance interval began at 2026-09-15T17:58:12.57887649Z and Blue's at
2026-09-15T17:59:28.091462413Z. The board remains on rc22 with its original start.
Coordinator rc24 resumed at 2026-09-15T17:59:31.05231564Z.
See the [Red receipt](validation/release-0.2.0rc28-red.json) and
[Blue receipt](validation/release-0.2.0rc28-blue.json).

The scoped coordinator runs `pokesim:0.2.0rc24-d99cdc2` from tagged commit
`d99cdc2dfd9afc13fae042eb49aa6cdc001ce804`. Its image ID is
`sha256:9f4a98a9096d658db78ed2b77612ad7c1767aa210af8f0d8239fd4f79758b461`.
The source archive is `/docker/pokesim/releases/0.2.0rc24-d99cdc2`. This coordinator-only
update lets each game prepare at its own safe point within a shared retry window.
At the coordinator rollout, games and the board retained their rc22 processes. Both games were subsequently upgraded to rc28 as described above. The private
coordinator backup is `/docker/pokesim-trading/backups/20260915T145218Z-rc24/before.tar.gz`.
It contains state and configuration and must not be published. See
[the coordinator receipt](validation/release-0.2.0rc24.json).

The release includes persistent playtime, the four-page interface, stall recovery,
bounded collection objectives, and return paths through Victory Road. Live displays
activity and the last achievement. Health and adventure progress are separate signals.
The rc8 upgrade adds persistent postgame project rotation, level training, random
starters for new adventures, and confirmed ground-item detours. Existing adventures
retain their Pokémon and continue from their latest autosaves.

The trade board runs as `pokesim-broker` on
[servarr port 8950](http://192.168.2.147:8950). It polls both games and mounts only game
data and the coordinator's redacted public status read-only. It cannot access saves,
ROMs, or peer tokens. The scoped coordinator is `pokesim-trading`, configured under
`/docker/pokesim-trading`. It runs as UID 10001 with no Docker socket or root identity.
Private peer credentials are configured and the trading policy is enabled under the
owner's explicit authorization for ongoing automatic exchanges. Last-copy sharing is
enabled for new Pokédex registrations. Every newly observed Championship earns a random
starter, Eevee, fossil Pokémon, or Mew. The older one-time Mew event remains disabled.
The coordinator has no HTTP server, so its Compose file disables the image's inherited
web-server health probe. Monitor its public status and transaction records.
See [automatic trading](automatic-trading.md).

## Release storage retention

Keep each service's current deployed release and its two most recent successful rollback images.
Also retain every image referenced by a running or stopped container, any held experiment,
and legacy images created before this monitoring workflow. Before removing an older
monitoring image, verify its exact tag, source revision label, retained source directory,
and all container references. Remove its tag without force. Do not use a global image,
build-cache, or volume prune. The current retained release set is rc20, rc21, rc22, rc23, rc24, rc25, rc26, rc27, and rc28,
covering both the games and the separately upgraded coordinator. The held rc11 experiment is also preserved. Older source archives remain available
for rebuilding historical releases.

Cold backups now use gzip compression. Historical `before.tar` paths in earlier receipts
have been converted to `before.tar.gz` in the same directories. Every replacement was
verified by comparing the decompressed SHA-256 with the original tar bytes before the
original tar file was removed. No archived save contents were discarded. The current
rc21 and rc22 backups were already compressed and were left intact.

Use `python tools/compress_release_backups.py BACKUP_ROOT` to review legacy candidates.
Add `--apply` to compress them individually with integrity verification. The tool only
scans recognized release directories for `before.tar`, refuses existing compressed
destinations, and preserves the source on failure. A leftover partial file after a
process crash needs inspection before retrying. It never scans active game data.

The Dockerfile now places changing version and revision metadata after the filesystem
layers. Two validation builds with different revision labels produced identical layers
and the same runtime settings as rc22. This packaging change applies to future builds.
The live games were not redeployed for storage maintenance.

## Routing

Nginx Proxy Manager on `proxy` (`192.168.2.140`) manages both routes. Host 55 serves Red
and its old alias. Host 57 serves Blue. Both forward to `servarr` (`192.168.2.147`) and
use the existing wildcard certificate, certificate ID 10. Streaming and TLS settings
match the original Red route. The hostnames resolve through the existing home DNS setup.

Nginx runs as UID 1000 on this proxy. Configuration tools must preserve that ownership
for new log files. A root-owned log file can pass a root configuration check but prevent
the running service from reloading.

## Backups and rollback

The current rc22 deployment retained compressed cold backups and passed current-save load checks:

- Red: `/docker/pokesim/backups/20260915T110422Z-rc22/before.tar.gz`.
- Blue: `/docker/pokesim-blue/backups/20260915T110504Z-rc22/before.tar.gz`.
- Previous image: `pokesim:0.2.0rc21-339d9a0`.

See [the rc22 release receipt](validation/release-0.2.0rc22.json). Older deployments below
are historical records, not descriptions of the currently running services.

The rc16 deployment verified both current saves and retained these cold backups:

- Red: `/docker/pokesim/backups/20260915T045935Z-rc16/before.tar`.
- Blue: `/docker/pokesim-blue/backups/20260915T045901Z-rc16/before.tar`.

See [the rc16 release receipt](validation/release-0.2.0rc16.json).

The rc14 deployment updated both games after loading each latest save successfully:

- Red: `/docker/pokesim/backups/20260915T040744Z-rc14/before.tar`. Previous image: `pokesim:0.2.0rc13-17cd997`.
- Blue: `/docker/pokesim-blue/backups/20260915T040653Z-rc14/before.tar`. Previous image: `pokesim:0.2.0rc12-66b226f`.

See [the rc14 deployment receipt](validation/release-0.2.0rc14.json).

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

The current rc21 code passed 453 tests, with one optional checkpoint test skipped.
Red resumed with 124 registrations and Blue with 127. Both subsequently caught Articuno,
reaching 125 and 128, and retained Mewtwo. Red's Moltres route remains under investigation. Both games and all 12
public checks passed. No multi-day pass is claimed. The per-release receipts above
preserve the exact validation and images.

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
