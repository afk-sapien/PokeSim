# Self-hosting PokeSim

## Current application

One manager serves the browser, owns the library, and starts one child process per running adventure. Several Red or Blue games can run inside one container. Cable trading uses an additional temporary paired emulator process. Set capacity according to available CPU, memory, and storage.

Use a published GHCR image as described below, or build and start using the [README instructions](../README.md#in-one-docker-container). The container runs as UID and GID 10001, with a read-only root filesystem. Its `/data` volume contains the complete application. Reference setup writes verified shared assets there on first use.

### Install a published container

The next release will publish a versioned Linux amd64 image at `ghcr.io/afk-sapien/pokesim`.
This candidate is not published yet. Until it is, use the source build in the README.
Older retired releases do not provide this registry installation.

Once a release is published, choose its exact tag from the
[release page](https://github.com/afk-sapien/PokeSim/releases). In a new installation
folder, download that release's configuration. The version below is an example for
the upcoming candidate and will work only after it is published:

For the newest release, `https://github.com/afk-sapien/PokeSim/releases/latest/download/compose.yaml`
and `.../env.example` always resolve to it, so the commands below never go stale. To pin an exact
version instead, name its tag:

```sh
POKESIM_RELEASE=v0.3.8
curl -fL --retry 3 -o compose.yaml "https://github.com/afk-sapien/PokeSim/releases/download/$POKESIM_RELEASE/compose.yaml"
mkdir -p pokesim-app
sudo chown 10001:10001 pokesim-app
docker compose up -d
```

Every setting below has a default inside `compose.yaml`, so a `.env` file is optional. Add one next
to `compose.yaml` to change any of them, and download that release's `env.example` as a starting
point. Settings kept in `.env` survive replacing `compose.yaml` when you upgrade.

Open [localhost:8930](http://localhost:8930) and supply your ROM through the Library.
You need Docker Engine with Compose on a Linux amd64 host, or Docker Desktop
configured for Linux containers on an x86-64 computer. Native ARM64 container
images are not part of this release pipeline. Python installation remains available
for supported ARM64 systems.

The release's Compose and environment files select the exact image version. There
is no floating `latest` tag and no automatic upgrade of an existing installation.
Public image pulls need no GitHub account, access token, Git clone, or local build.

For an upgrade, back up and stop the application, review the release notes, and set
`POKESIM_IMAGE` in your existing `.env` to the new version. Preserve your data path
and other settings. Then run `docker compose pull` and `docker compose up -d`.
Review any Compose changes in the new release before restarting.

The release also retains `image-linux-amd64.tar.gz` for offline image loading.
Download it and `SHA256SUMS` from the same release, verify with
`sha256sum --ignore-missing -c SHA256SUMS`, then run
`docker load -i image-linux-amd64.tar.gz` and `docker compose up -d --pull never`.
The loaded archive has the same versioned GHCR tag. Initial reference preparation
still needs internet access unless the reference archive is supplied locally.

### Settings

| Setting | Purpose |
| --- | --- |
| `DATA_PATH=./pokesim-app` | Persistent application folder containing all adventures |
| `PUBLIC_URL=http://localhost:8930` | Exact browser address, including scheme and port |
| `HTTP_PORT=8930` | Host port mapped to the manager |
| `BIND_ADDRESS=127.0.0.1` | Host interface accepting connections |
| `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.3.8` | Exact published image version, overridden by `compose.build.yaml` for source builds |

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

The previous single-game Compose file remains at `compose.legacy.yaml` and its settings at `.env.legacy.example`. With the new image, its explicit `legacy` command continues to use environment configuration. Existing deployment examples under `deploy/` describe the legacy separate broker and trader. They are not components of the new managed application.

Restore a complete backup into an empty application directory. Recovery needs the registry, adventure files, and interaction decisions together. If a trade had committed before a crash, recovery applies its recorded results instead of rerunning the cable exchange.

### Validation boundary

Native source launch depends on the availability of Python, PyBoy, and its native dependencies for the host. Docker packages those dependencies for a Linux target. Neither the manager nor the simulation protocol requires x86-64. The Python install workflow covers multiple OS and CPU targets, with actual passing results required before claiming support for a release.

## Historical prebuilt release

The instructions below are retained only for existing **v0.2.0rc6** installations.
This release is retired and should not be used for a new installation. Use the
current application instructions above. Keep historical source, images, and
configuration together when recovering an old installation.

## Install the prebuilt v0.2.0rc6 release

The prebuilt release supports **Linux amd64** with Docker Engine and the Compose plugin. Supply your own clean Pokémon Red (USA, Europe) ROM. Pokémon ROMs, sprites, and game datasets are not bundled. The PyBoy dependency includes its own small demo ROM, which cannot replace your Pokémon ROM. Blue and ARM do not yet have equivalent release validation.

Clone the public release source:

```sh
git clone --branch v0.2.0rc6 --depth 1 https://github.com/afk-sapien/PokeSim.git pokesim
cd pokesim
cp .env.example .env
mkdir -p roms data
sudo chown 10001:10001 data
```

Place your ROM at `roms/pokered.gb`. Create a local reference checkout for data preparation:

```sh
git clone https://github.com/pret/pokered .reference/pokered
git -C .reference/pokered checkout a1a22aaf84d1675bcdbaeb194592379d586d838e
```

Download the prebuilt image and verify its checksum. These public downloads require no GitHub account, token, or registry login:

```sh
curl -fL --retry 3 -o image-linux-amd64.tar.gz https://github.com/afk-sapien/PokeSim/releases/download/v0.2.0rc6/image-linux-amd64.tar.gz
curl -fL --retry 3 -o SHA256SUMS https://github.com/afk-sapien/PokeSim/releases/download/v0.2.0rc6/SHA256SUMS
sha256sum --ignore-missing -c SHA256SUMS
```

Confirm that the image archive reports `OK`, then load and start it:

```sh
docker load -i image-linux-amd64.tar.gz
docker compose --profile setup run --rm --pull never prepare-data
docker compose up -d --pull never
docker compose logs --tail=50 pokesim
```

Open [localhost:8930](http://localhost:8930). The archive loads the exact image tag `pokesim:0.2.0rc6`. Releases are distributed as downloadable Docker archives, so there is no `docker compose pull` step. The [release page](https://github.com/afk-sapien/PokeSim/releases/tag/v0.2.0rc6) also provides source packages, Compose files, a dependency inventory, and a manifest with the image ID and source revision.

The setup command parses the pinned source checkout and writes verified game data into `./data`. It does not build or download a ROM. The runtime uses the local data afterward and does not require that source checkout or internet access unless notifications are enabled.

Progress, policy memory, screenshots, and the journal live in `./data`. The container runs as user and group 10001 with a read-only root filesystem and read-only ROM. Do not point two running containers at the same data directory.

## Access and controls

`/pokedex` browses all 151 Kanto entries with types, base stats, the level-up learnset, evolution family, and where each one can be found, next to what this run has registered and everyone waiting in the storage boxes. Entry data comes from your locally prepared game data. Each entry also links out to Bulbapedia, Serebii, and Wikipedia. Portraits use the optional local pack described below and fall back to a neutral placeholder.

The browser displays up to 10 frames per second independently of game speed. It waits for each image to download and decode before requesting another, retains the last good image during a connection failure, and retries automatically. Hidden tabs stop downloading game images. The `/stream` MJPEG endpoint remains available for other clients.

The default port is accessible only on the Docker host. For remote access, use the [authenticated HTTPS proxy recipe](proxy.md) or a private network. The app has no built-in authentication. Anyone who can reach an instance with controls enabled can control, reset, and rewind its game.

Set `VIEWER_ONLY=1` in `.env` to disable every game control endpoint, then recreate the container. This does not authenticate viewers.

## Useful settings

Edit `.env`, then run `docker compose up -d --pull never`.

| Setting | Default | Purpose |
| --- | --- | --- |
| `ROM_FILE` | `./roms/pokered.gb` | ROM path on the host |
| `DATA_PATH` | `./data` | Persistent game and journal data |
| `HTTP_PORT` | `8930` | Browser port |
| `BIND_ADDRESS` | `127.0.0.1` | Interface to listen on |
| `PUBLIC_URL` | `http://localhost:8930` | Links in feeds and notifications |
| `SPEED` | `1` | Game speed, 0 means unlimited |
| `VIEWER_ONLY` | `0` | 1 disables controls |
| `NTFY_URL` | empty | Optional notification destination for this historical single-game release. The current application uses the Library's Notifications page |
| `EVENT_RETENTION_DAYS` | `0` | History retention, 0 keeps everything |
| `KEEP_AUTOSAVES` | `20` | Recent autosave pairs to retain |

Unlimited speed can use a full CPU core. Long-term memory, storage, and viewer bandwidth validation remains incomplete. No minimum hardware specification is established yet.

## Keep your adventure

Back up the complete data directory while the container is stopped. Before an upgrade, preserve that backup and the old image. New autosaves pair the game state with policy memory, a checksum, ROM identity, and the pinned PyBoy version. Startup can fall back to an earlier compatible save if the newest one is corrupt.

See [backup, restore, upgrades, rollback, and troubleshooting](operations.md). Event history and screenshots are kept indefinitely unless you explicitly configure retention.

## Build from source

After preparing the ROM, data directory, and source checkout above:

```sh
docker compose -f compose.yaml -f compose.build.yaml build
docker compose -f compose.yaml -f compose.build.yaml --profile setup run --rm prepare-data
docker compose -f compose.yaml -f compose.build.yaml up -d
```

For native development, follow [CONTRIBUTING.md](../CONTRIBUTING.md).
