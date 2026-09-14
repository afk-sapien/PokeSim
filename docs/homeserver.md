# Homeserver deployment

Updated September 13, 2026 (America/Los_Angeles).

| Edition | URL | Container on `servarr` | Port | Data directory |
| --- | --- | --- | --- | --- |
| Red | https://pokesim-red.tynet.app | `pokesim` | 8930 | `/docker/pokesim/data` |
| Blue | https://pokesim-blue.tynet.app | `pokesim-blue` | 8940 | `/docker/pokesim-blue/data` |

The old https://pokesim.tynet.app address remains a Red alias. Each game retains its own
ROM, saves, party, boxes, journal, and notification configuration. Red runs at speed 1,
and Blue retains its existing unlimited speed setting.

Both instances run `pokesim:clock-20260913`, image ID
`sha256:80446bb567d926c6847bcce6dac13d16636e855aa71ffdc384b86aab2e512416`.
The Live clock now tracks persistent simulated playtime beyond the cartridge limit.
Red migrated as a lower bound because its cartridge clock was already capped. Blue
migrated from its still-running cartridge clock.
The image was built from the current workspace, including the four-page navigation, team and goal on Live, all 151 Pokédex entries
in one list, and the expanded funny nickname pool for new catches. PyBoy remains at version 2.7.0.
Local game data and all 151 sprites are installed separately under each data directory.
The app runs as UID and GID 10001, with matching ownership on those data directories.

## Routing

Nginx Proxy Manager on `proxy` (`192.168.2.140`) manages both routes. Host 55 serves Red
and its old alias. Host 57 serves Blue. Both forward to `servarr` (`192.168.2.147`) and
use the existing wildcard certificate, certificate ID 10. Streaming and TLS settings
match the original Red route. The hostnames resolve through the existing home DNS setup.

Nginx runs as UID 1000 on this proxy. Configuration tools must preserve that ownership
for new log files. A root-owned log file can pass a root configuration check but prevent
the running service from reloading.

## Backups and rollback

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

Both copied saves loaded in the new image before deployment and retained eight badges
and six party members. Both live containers resumed their existing autosaves and passed
health checks. All six pages, the Pokédex status API, PNG sprites, and edition-specific
Atom feed URLs were checked over HTTPS. The original hostname still serves Red.
