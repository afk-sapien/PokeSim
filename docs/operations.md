Operating pokesim

Use one process and one container per data directory. Sharing a data directory between active instances is unsupported. The examples below assume the default `./data` directory. Substitute the actual `DATA_PATH` for a customized installation.

**Permissions and startup**

The image runs as user and group 10001. Create the bind mount before starting it. For an existing installation, stop the app and back up its data before adjusting ownership:

```sh
docker compose stop
sudo chown -R 10001:10001 ./data
docker compose up -d
```

Apply this only to pokesim's data directory. Do not change ownership of your ROM library. The container needs read access to its one mounted ROM file.

Compose reads `.env`. The source command reads environment variables directly and uses `ROM_PATH` and `DATA_DIR` instead of Compose's host settings `ROM_FILE` and `DATA_PATH`. Native source mode defaults to port 8000 and localhost. Set `HOST` deliberately for another interface.

The primary tested ROM SHA-1 is `ea9bcae617fdf159b045185467ae58b2e4a48b9a` for Red (USA, Europe). Blue's recognized SHA-1 is `d7037c83e1ae5b39bde3c30787637ba1d4c48ce2`, with experimental support. Check your own file using `sha1sum roms/pokered.gb`. No ROM download is provided.

**Backup and restore**

A backup must include the entire data directory. New autosaves consist of a `.state` file and matching `.json` manifest. The manifest carries policy and run memory paired with that exact state. The `game-data` directory holds the locally generated dataset and source manifest. Keep it in the backup too. SQLite stores event history and compatibility data for older saves. Screenshots and event states live in separate directories.

For a cold backup using the default directory:

```sh
docker compose stop
sudo tar -czf pokesim-backup.tar.gz data
cp .env pokesim-backup.env
chmod 600 pokesim-backup.env
docker compose start
```

Move the backup and its settings to your normal backup destination. Do not commit either file. Settings can contain a notification token. Stop the app even if the game is paused so all files form one consistent backup.

Restore into a new directory without overwriting the original:

```sh
mkdir restored
sudo tar -xzf pokesim-backup.tar.gz -C restored
sudo chown -R 10001:10001 restored/data
```

Point `DATA_PATH` at `./restored/data` and use the matching previous image for the first boot. Confirm the expected game, policy state, journal, and screenshots before resuming an upgrade. Disable `NTFY_URL` in a test copy to avoid duplicate notifications. A backup rehearsal should use a separate Compose project and port.

**Upgrades and rollback**

For source builds, use the additional `-f compose.build.yaml` file and `--build`. Make a backup and record the current Git commit. Preserve the currently running image before rebuilding:

```sh
docker image tag pokesim:local pokesim:before-upgrade
docker compose stop
```

Take the backup, check out the desired reviewed revision, and run `docker compose -f compose.yaml -f compose.build.yaml up -d --build`. For release images, download and verify the desired version archive using the README instructions, load it with `docker load`, set that exact tag in `POKESIM_IMAGE`, then run `docker compose up -d --pull never --no-build`. There is no public registry dependency.

Rollback can require both the previous image and its matching data backup. A database or save-state format may have changed. Point `DATA_PATH` at a restored backup and set `POKESIM_IMAGE=pokesim:before-upgrade`, then run `docker compose up -d --no-build`. Never use `--build` when starting an old image for rollback.

Legacy autosaves without manifests remain readable, but their ROM identity and paired policy memory cannot be verified. Keep the original data backup when migrating. Newly written checkpoints require the same ROM hash, PyBoy version, and policy name. Application checkpoint format 1 is the current compatibility boundary. Event rewinds from legacy event saves retain current learned policy memory and the existing journal.

**Access and reverse proxies**

The default published port binds to localhost. This works for a proxy running on the same host. A proxy in another container needs a deliberately configured shared network or access to the host's chosen LAN address. Do not assume that its localhost points at pokesim.

For remote control, place authentication and TLS in front of the entire service. Protect the API, stream, event pages, and screenshots as well as the homepage. Do not expose the backend port separately. Feed readers and notification links must be able to authenticate through the same access boundary.

`VIEWER_ONLY=1` denies every request to `/api/control` and hides game controls. It also denies `/api/states`. Viewing remains unauthenticated unless protected by your proxy. Limit traffic and simultaneous streams in the proxy before exposing a viewing instance to a large audience.

MJPEG streaming needs response buffering disabled and a long read timeout. The app sends `X-Accel-Buffering: no`. Configure the equivalent options in your proxy and test with an active browser stream. Use the [authenticated Caddy recipe](proxy.md) for a complete deployment example.

**Health and recovery**

`/healthz` returns 200 while the emulator thread is alive and recently active. A deliberate pause is healthy. A stopped worker or stale activity returns 503. Ten consecutive loop failures stop the worker, and the server exits unsuccessfully so the container restart policy can act. A Docker unhealthy status alone does not trigger `restart: unless-stopped`.

If startup rejects a save, inspect `docker compose logs --tail=100 pokesim`. The app tries older compatible autosaves and fails if none can be loaded. Restore a backup, use the matching PyBoy version and ROM, or choose a new data directory if you intentionally want a new adventure. Do not delete the only copy of an incompatible save.

Controls that reset the game require confirmation in the UI. Restart keeps the event journal but clears rotating autosaves. Keep an external backup if you want to retain the old run.

**Storage and outbound traffic**

Autosaves rotate according to `KEEP_AUTOSAVES`. Their manifests rotate with them. Event history, screenshots, and event states grow without a limit when `EVENT_RETENTION_DAYS=0`. Positive retention permanently deletes expired entries and their attachments during autosaving, so links to those events eventually return 404. Recent autosaves are retained separately.

Compose caps container logs at three files of 10 MB each. Monitor available disk space and back up before experimenting with retention. An interrupted write leaves a complete old checkpoint available. A full disk can still prevent new progress from being saved.

ntfy is the optional outbound application integration. When enabled, it sends event titles, descriptions, priorities, screenshots, and links to the configured destination. Tokens stay in local settings. Without ntfy, the runtime does not require a model service or a notification account. Offline acceptance testing is tracked in the release status.

**Moving from 0.1.0 to 0.2.0rc3**

Version 0.1.0 bundled game data in the image. Version 0.2.0rc3 reads a generated bundle from the data volume. Before upgrading, stop and back up the old installation. Prepare the source checkout from the README, select the new image, then run `docker compose --profile setup run --rm prepare-data` before starting the new app. This adds game data without replacing saves or the journal. The old PyBoy 2.7.0 checkpoints remain compatible.

For rollback, stop the new app and restore the complete pre-upgrade backup into a separate directory, then start the preserved 0.1.0 image against it. Do not rely on downgrading against a mutated data directory. Legacy bundled assets are for private regression testing only and are not part of the new release artifact.
