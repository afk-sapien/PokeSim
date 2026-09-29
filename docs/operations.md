# Operating PokeSim

These instructions cover the current Adventure Library. Older single-game instructions
are preserved in the [legacy operations archive](history/operations-legacy.md).
For installation, ports, permissions, and remote access, use [self-hosting](self-hosting.md).

## Start and stop

Desktop: run the launch command printed by the installer, or `pokesim-desktop` after
setting up PATH. Choose **Save and quit** to save all adventures and close the application.
Closing the browser tab leaves the application running.

Docker: run commands from the installation folder containing your Compose file:

```sh
docker compose up -d --wait
docker compose ps
docker compose logs --tail=100 pokesim
docker compose stop
```

Use the same Compose files and project name every time. One manager owns the complete
library and starts one child process for each running adventure. Never run two managers
against the same library or remove their lock files while they are running.

## Where your data lives

The [desktop guide](desktop.md#your-files-and-backups) lists platform-specific application folders.
Docker stores the entire library under `/data` inside the container:

- The new quick-start file uses a persistent named volume, normally `pokesim_pokesim-data` when your installation folder is named `pokesim`.
- The original Compose file uses the host folder `./pokesim-app` by default.
- An explicit `DATA_PATH` in `.env` overrides either default.

Keep the registry, installed ROMs, shared assets, all adventures, and interaction records
together. Do not copy one trading participant's saves in isolation. Renaming the Compose
project can select a different volume and make an existing library appear empty.
`docker compose down` keeps the volume. `docker compose down --volumes` deletes it.

## Back up and restore

Open **Settings and backups** in the Library, create a backup, then download the ZIP to
another location. The application coordinates saving and captures a consistent library.
A backup left only inside the application's data storage does not protect against losing
that storage. Backups contain your private ROMs, saves, and notification settings. Keep
them private and do not attach them to issue reports.

For a cold copy of a host folder, stop the whole application first, then copy the entire
folder. Pausing an adventure is not equivalent to stopping the manager. For a named volume,
use the Library's downloadable backup instead of looking for a host `./data` folder.

Restore a downloaded ZIP into a new, empty application directory with the application
stopped:

```sh
pokesim restore "/path/to/backup.zip" --data-dir "/path/to/restored-library"
pokesim-desktop --data-dir "/path/to/restored-library"
```

The restore command checks the archive and refuses a nonempty destination. Keep the
original library and backup until the restored adventures, journal, and progress have
been verified. Use the matching application version for the first recovery boot.
For Docker, the same `pokesim restore` command runs in a temporary container with the
backup mounted read-only and a fresh writable destination. See the
[recovery guidance](self-hosting.md#migration-and-recovery).

## Continue in another emulator

Choose **Download Save** on the adventure's Library card. Start the adventure
first if it is stopped. Standalone instances keep **Download .sav** on the Live
page. Export outside battles, dialogue, and trades. If a screen is changing,
wait a moment and retry.
The download contains the current party, PC collection, and cartridge progress.
Load it with the same English Red or Blue ROM in another emulator, using that
emulator's import-save option or matching the save's filename to the ROM.

PokeSim opens the native Save menu on a private copy of the current checkpoint,
then boots the resulting 32 KiB cartridge save and verifies Continue restores
the collection and progress. The live adventure keeps playing. The ROM is not
included in the download.

A cartridge save does not contain PokeSim's journal, statistics, marathon records,
trade receipts, or extended play clock. Use a full Library backup to preserve those.
Exported saves are for continuing elsewhere, not for replacing one participant
in a running PokeSim trading library.

## Performance

Each running adventure has its own emulator process. At Max pace, it deliberately
uses available CPU to advance as quickly as possible. Optimizations increase
progress per CPU second, so total CPU utilization can remain high at Max.

PokeSim renders only when a viewer needs a frame or an observation needs a fresh
journal picture. It also encodes live frames only while a viewer is watching.
These savings do not change the configured simulation speed or policy cadence.

## Library resource readings

Each adventure card shows its worker's CPU usage, resident memory, and actual speed. CPU is
measured over the interval between samples. 100% means one fully used logical
core, and a process using several cores can exceed 100%. Memory excludes the
shared library process and is shown in MiB. These are current readings, not
cumulative totals or the whole container's usage.

Actual speed measures simulated seconds per real second over the latest worker
health-check interval, normally about three seconds. For example, 2.3× means
2.3 seconds of game time per real second, even if the selected limit is 4×.
Max has no fixed target. Paused or held workers settle to 0.0×. Cable Club work
runs separately and is not included in this worker reading. Loading a checkpoint
does not count restored frames as new work. Readings older than 15 seconds become
Unavailable, and a restarted worker needs two fresh samples.

The first CPU reading says Measuring until a second sample is available.
Unavailable means the process could not be measured. Stopped adventures say
Not running. Samples are reused for at least two seconds across browser requests.

Recent activity shows the last three observed location changes, with local times.
It is a compact overview, not the full journal or a raw diagnostic log. Every
managed simulation page links back to the Library through the PokeSim logo.
The adventure selector switches between games without returning to the Library.

## Update and roll back

Create and download a backup, then stop the app. For a native installation, follow
[desktop updates](desktop.md#update-or-remove). For Docker, follow
[container updates](self-hosting.md#back-up-update-and-remove). Preserve your selected data
mount, project name, and `.env` settings. Release image tags and wheel URLs pin versions,
so pulling or upgrading the same URL does not automatically select the newest release.

A rollback may require both the previous application version and its matching backup.
Do not run an older version against a library modified by a newer version unless that
release explicitly supports it. Restore into a separate location to preserve current progress.

## Health, storage, and recovery

The manager's `/health/ready` endpoint reports readiness. Docker checks it automatically.
Inspect individual adventure failures in the Library and startup failures in the container
logs. Docker marks failed health checks as unhealthy, but that alone does not restart a
still-running container.

Check free disk space when saving or setup fails. Keep the complete application and
interaction records together after an interrupted trade, then restart to let the manager
finish its recorded decision. Never bypass a committed trade by restoring only one game.

Container logs rotate at three files of 10 MB each. Backups and adventure history can
still consume disk space, so keep an eye on storage and move downloaded backups to your
normal backup destination. Phone notifications are configured in the Library and are
included in full backups. Disable them when running a test copy to avoid duplicate alerts.
