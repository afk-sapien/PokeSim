# Self-hosting PokeSim

## Current application

One manager serves the browser, owns the library, and starts one child process per running adventure. Several Red or Blue games can run inside one container. Cable trading uses an additional temporary paired emulator process. Set capacity according to available CPU, memory, and storage.

The container runs as UID and GID 10001, with a read-only root filesystem. Its `/data`
volume contains the complete application. Reference setup writes verified shared assets
there when you start your first adventure.

### First installation

Install [Docker Engine with Compose](https://docs.docker.com/engine/install/) on Linux,
or [Docker Desktop](https://docs.docker.com/desktop/) on Windows or macOS, and start it.
Check both commands before continuing:

```sh
docker version
docker compose version
```

The published image targets **Linux amd64**. Docker Desktop must use Linux containers.
For Apple Silicon and Linux ARM64, the [native installer](desktop.md) is the recommended
path. ARM64 container images are not currently published. There is no established minimum
hardware specification. Start with one adventure at 1× and add more as resources allow.

Create a new installation folder, then download the quick-start configuration:

```sh
mkdir pokesim
cd pokesim
curl -fL --retry 3 -o compose.yaml https://github.com/afk-sapien/PokeSim/releases/latest/download/compose.quickstart.yaml
docker compose up -d --wait
```

On Windows PowerShell, use `curl.exe` for that download. Open
[localhost:8930](http://localhost:8930) **on the Docker host** and supply your ROM in the
Library. Docker pulls the public, versioned image without a registry login or source build.
The first download can take several minutes. `--wait` reports startup or health failures.

The quick-start file uses a Docker-managed `pokesim-data` volume. Docker initializes its
ownership from the image, so you do not need `mkdir`, `chown`, or administrator access to
prepare a data folder. Keep the installation directory and its name stable. Compose uses
that name to select the volume. Renaming it or changing `--project-name` selects a different
library. `docker compose down` preserves the volume. **Do not use `down --volumes` or prune
this volume if you want to keep your saves.**

The latest-download URLs select the newest completed stable release. Its installers and
Compose files pin that release's wheel and image. To pin a configuration yourself, replace
`latest/download` with `download/v0.4.8` in the download URL. Draft releases stay hidden
until all their downloads are verified, so preparing the next version does not interrupt
these install commands.

### Existing installations and custom data folders

The original `compose.yaml` still defaults to `./pokesim-app`. Keep using it for existing
bind-mount libraries. Replacing it with the quick-start file without setting `DATA_PATH`
would open an empty Docker volume instead of your existing library.

For a new bind-mount installation, download the original release configuration:

```sh
curl -fL --retry 3 -o compose.yaml https://github.com/afk-sapien/PokeSim/releases/latest/download/compose.yaml
mkdir -p pokesim-app
sudo chown 10001:10001 pokesim-app
docker compose up -d --wait
```

Those ownership commands are for a regular Linux Docker Engine installation. Docker
Desktop, rootless Docker, and SELinux hosts have different bind-mount permission rules.
Use the quick-start named volume for a new library if you do not need a host folder.
Do not recursively change ownership of unrelated folders or use world-writable permissions.

### Configure ports and remote access

Settings are optional. Put overrides in a `.env` file beside `compose.yaml`. For example,
if port 8930 is busy, use:

```dotenv
HTTP_PORT=8931
```

The configurations in this checkout derive the default local `PUBLIC_URL` from `HTTP_PORT`.
With an older release configuration, also set `PUBLIC_URL=http://localhost:8931`.
Open [localhost:8931](http://localhost:8931) after `docker compose up -d --wait`.

On a remote server, localhost refers to the server. An SSH tunnel keeps the default
local-only binding. Run this on the computer with your browser:

```sh
ssh -L 8930:127.0.0.1:8930 user@your-server
```

Then open [localhost:8930](http://localhost:8930) on that computer. For a trusted LAN,
set both `BIND_ADDRESS=0.0.0.0` and `PUBLIC_URL=http://YOUR_SERVER_IP:8930`, then recreate
the container. Anyone who can reach that address can manage the library. Use authenticated
HTTPS for broader access. Setting `PUBLIC_URL` alone does not expose the listening port.

### Back up, update, and remove

Use **Settings and backups** in the Library to download a consistent backup, then stop
the app with `docker compose stop`. Keep the backup outside the container and volume.
Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:NEW_VERSION` in `.env`, preserving your other
settings, then run:

```sh
docker compose pull
docker compose up -d --wait
docker compose logs --tail=50 pokesim
```

Choose a real version from the [release page](https://github.com/afk-sapien/PokeSim/releases).
The configuration pins its image version. Pulling alone does not select a newer release.
Review release notes and configuration changes before updating. Do not replace your
`.env` with `env.example`, which would reset your data path and other settings.

To remove the service while retaining its library, run `docker compose down`.
For backup and restore details, see [operations](operations.md).

### Build the current source

From a source checkout, use both files for building and starting:

```sh
docker compose -f compose.quickstart.yaml -f compose.build.yaml up -d --build --wait
```

This builds locally and initializes a named volume. There is no separate `prepare-data`
service for the current application. Add your ROM in the Library. For an existing
bind-mount installation, use `compose.yaml` instead of `compose.quickstart.yaml` in both
commands. Use the same file arguments for subsequent stop, logs, and update commands.

### Offline image loading

The release retains `image-linux-amd64.tar.gz` for offline loading. Download it and
`SHA256SUMS` from the same release, verify the image checksum with
`sha256sum --ignore-missing -c SHA256SUMS`, then run
`docker load -i image-linux-amd64.tar.gz` and `docker compose up -d --pull never --wait`.
The loaded archive has the same versioned GHCR tag. Initial reference preparation
still needs internet access unless the reference archive is supplied locally.

### Troubleshooting startup

Run `docker compose ps -a` and `docker compose logs --tail=100 pokesim` from your
installation folder. Include those outputs, your OS and CPU, and `docker compose version`
in a [support request](../SUPPORT.md). Remove private paths or tokens before sharing.

- **Cannot connect to the Docker daemon:** Start Docker Desktop or the Docker service. On Linux, check your user's access to Docker according to its installation guide.
- **Unknown `compose` or `--wait`:** Install or update the Docker Compose v2 plugin. The old `docker-compose` v1 command is not the supported path.
- **No matching manifest for ARM64:** Use the native installer. The published container is amd64 only.
- **Permission denied under `/data`:** For a new installation, use the named-volume quick start. For an existing bind mount, check ownership for container UID 10001 and any SELinux or rootless mapping rules.
- **Port is already allocated:** Change `HTTP_PORT` as shown above and recreate the container.
- **Library works on the server but not another computer:** Use the SSH tunnel or configure both the bind address and public URL.
- **Host or Origin rejected:** Open the exact `PUBLIC_URL`, including its hostname and port. `localhost` and `127.0.0.1` are different hosts.
- **An empty Library appears after an update:** Stop the service and check your Compose project name and `DATA_PATH`. Restore the original mount before creating any new adventures.
- **ROM upload asks for prepare-data:** Update to 0.4.6 or newer and retry the upload. Earlier versions could try to generate portraits before automatic reference setup.
- **First adventure setup fails:** Starting the first adventure downloads a pinned reference archive and generates portraits. Check connectivity and the error shown in the Library. Prepared adventures can run offline.

### Settings

| Setting | Purpose |
| --- | --- |
| `DATA_PATH` | Quick start defaults to named volume `pokesim-data`. Original Compose defaults to host folder `./pokesim-app` |
| `PUBLIC_URL=http://localhost:8930` | Exact browser address, including scheme and port |
| `HTTP_PORT=8930` | Host port mapped to the manager |
| `BIND_ADDRESS=127.0.0.1` | Host interface accepting connections |
| `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.4.8` | Exact published image version, overridden by `compose.build.yaml` for source builds |

Phone notifications need no setting here. Open the Library, choose **Notifications**, generate a topic, and subscribe to it in the [ntfy](https://ntfy.sh) app. See the [guide](guide.md#notifications). `NTFY_URL`, `NTFY_TOKEN`, `NTFY_MIN_PRIORITY`, and `NTFY_MUTE` are still read from the environment as defaults until notifications are saved in the Library.

The Library opens directly without a sign-in or owner key. Its default published port is local-only. Anyone who can reach the Library can manage adventures, so remote access belongs behind an authenticated HTTPS reverse proxy or on a trusted private network. Point an existing authenticated proxy at the manager and preserve the Host matching `PUBLIC_URL`, which must be the browser-facing address. The application checks Host and Origin and protects browser writes against cross-site requests. These protections do not authenticate remote users. Worker credentials and private ports remain internal.

The Compose service uses an init process to reap children and allows 90 seconds for orderly shutdown. Keep a single manager process per application folder. Do not add Uvicorn workers or share one application volume between containers.

A native server uses the same application:

```sh
pokesim serve --data-dir /path/to/library --host 127.0.0.1 --port 8000
```

Start and stop adventures in the browser. A command-line client is also available while the manager is running:

```sh
pokesim adventures list --data-dir /path/to/library
pokesim adventures create --data-dir /path/to/library --name "Red orchard" --rom /path/to/pokered.gb --start
pokesim backup --data-dir /path/to/library
```

### Migration and recovery

Stop both the source adventure and destination application. Back up the original files, then import into a fresh application root:

```sh
pokesim import /path/to/old-data --stopped --rom /path/to/pokered.gb --name "Original Red" --data-dir /path/to/library
```

For a container import, run the same command in a temporary container with the application volume, a stopped backup copy of the source folder, and the ROM mounted. The importer needs writable lock files in the source directory, while the ROM can remain read-only. It does not change source saves or database contents. Do not bind the old adventure folder directly as the new application root.

An individually imported adventure with legacy trades remains playable, but its trading stays blocked until its peers are reconciled. Import the resolved Red and Blue pair together when the original coordinator evidence is available:

```sh
pokesim import-pair --red /path/to/old-red --blue /path/to/old-blue --red-rom /path/to/pokered.gb --blue-rom /path/to/pokeblue.gb --coordinator-root /path/to/old-trader --stopped --data-dir /path/to/library
```

Stop both legacy adventures, their coordinator, and the destination application first. The paired import verifies exact matching completion history, latest trade barriers, verified checkpoints, and retained coordinator evidence before registering either copied adventure. Missing or mismatched evidence fails the import and cannot be bypassed by clearing a protection flag. Source saves, databases, and coordinator evidence remain unchanged. The importer opens coordination lock files, so use writable backup copies when the originals must remain read-only. Keep those original services stopped after migration to avoid running duplicate ownership histories.

The previous single-game Compose file remains at `compose.legacy.yaml`. Its settings are documented in the [legacy operations archive](history/operations-legacy.md). With the new image, its explicit `legacy` command continues to use environment configuration. Existing deployment examples under `deploy/` describe the legacy separate broker and trader. They are not components of the new managed application.

Restore a complete backup into an empty application directory. Recovery needs the registry, adventure files, and interaction decisions together. If a trade had committed before a crash, recovery applies its recorded results instead of rerunning the cable exchange.

### Validation boundary

Native source launch depends on the availability of Python, PyBoy, and its native dependencies for the host. Docker packages those dependencies for a Linux target. Neither the manager nor the simulation protocol requires x86-64. The Python install workflow covers multiple OS and CPU targets, with actual passing results required before claiming support for a release.

Historical instructions for retired v0.2.0rc6 installations are kept in the [archive](history/self-hosting-rc6.md).
