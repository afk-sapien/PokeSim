# Homeserver deployment

Updated September 14, 2026 (America/Los_Angeles).

| Edition | URL | Container on `servarr` | Port | Data directory |
| --- | --- | --- | --- | --- |
| Red | https://pokesim-red.tynet.app | `pokesim` | 8930 | `/docker/pokesim/data` |
| Blue | https://pokesim-blue.tynet.app | `pokesim-blue` | 8940 | `/docker/pokesim-blue/data` |

The old https://pokesim.tynet.app address remains a Red alias. Each game retains its own
ROM, saves, party, boxes, journal, and notification configuration. Red runs at speed 1,
and Blue retains its existing unlimited speed setting.

Both adventures run `pokesim:0.2.0rc7-ca32f70`, built from release tag `v0.2.0rc7`
and commit `ca32f704db74e794a9a6f4a03ba6ba15259f23e2`. The image ID is
`sha256:21aaf503ad5965fc0c3aecb40471c2e0ca8aba58438f9f5c06508a81833103a3`.
The exact source archive is unpacked at `/docker/pokesim/releases/0.2.0rc7-ca32f70`.
PyBoy remains at version 2.7.0. Game data and sprites remain separate mounts.

The release includes persistent playtime, the four-page interface, stall recovery,
bounded collection objectives, and return paths through Victory Road. Live displays
activity and the last achievement. Health and adventure progress are separate signals.

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
