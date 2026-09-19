# Self-hosting reference

For standalone computer downloads, start with [Run your own adventure](../README.md#run-your-own-adventure).

The prebuilt instructions below target the **v0.2.0rc31** experimental release.
Keep its image and configuration together. No PokeSim source checkout is needed.

## Install the prebuilt v0.2.0rc31 release

The prebuilt release supports **Linux amd64** with Docker Engine and the Compose plugin. Supply your own clean Pokémon Red (USA, Europe) ROM. Pokémon ROMs, sprites, and game datasets are not bundled. The PyBoy dependency includes its own small demo ROM, which cannot replace your Pokémon ROM. Blue and ARM do not yet have equivalent release validation.

Create a new installation directory:

```sh
mkdir pokesim
cd pokesim
mkdir -p roms data
sudo chown 10001:10001 data
```

The release configuration downloaded below selects `pokesim:0.2.0rc31` automatically.

Place your ROM at `roms/pokered.gb`. Create a local reference checkout for data preparation:

```sh
git clone https://github.com/pret/pokered .reference/pokered
git -C .reference/pokered checkout a1a22aaf84d1675bcdbaeb194592379d586d838e
```

Download the prebuilt image and verify its checksum. These public downloads require no GitHub account, token, or registry login:

```sh
curl -fL --retry 3 -o image-linux-amd64.tar.gz https://github.com/afk-sapien/PokeSim/releases/download/v0.2.0rc31/image-linux-amd64.tar.gz
curl -fL --retry 3 -o SHA256SUMS https://github.com/afk-sapien/PokeSim/releases/download/v0.2.0rc31/SHA256SUMS
curl -fL --retry 3 -o compose.yaml https://github.com/afk-sapien/PokeSim/releases/download/v0.2.0rc31/compose.yaml
curl -fL --retry 3 -o env.example https://github.com/afk-sapien/PokeSim/releases/download/v0.2.0rc31/env.example
sha256sum --ignore-missing -c SHA256SUMS
cp env.example .env
```

Confirm that the image archive, Compose file, and environment example all report
`OK`, then load and start it:

```sh
docker load -i image-linux-amd64.tar.gz
docker compose --profile setup run --rm --pull never prepare-data
docker compose up -d --pull never
docker compose logs --tail=50 pokesim
```

Open [localhost:8930](http://localhost:8930). The archive loads the exact image tag `pokesim:0.2.0rc31`. Releases are distributed as downloadable Docker archives, so there is no `docker compose pull` step. The [release page](https://github.com/afk-sapien/PokeSim/releases/tag/v0.2.0rc31) also provides source packages, Compose files, a dependency inventory, and a manifest with the image ID and source revision.

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
| `NTFY_URL` | empty | Optional notification destination |
| `EVENT_RETENTION_DAYS` | `0` | History retention, 0 keeps everything |
| `KEEP_AUTOSAVES` | `20` | Recent autosave pairs to retain |

Unlimited speed can use a full CPU core. Long-term memory, storage, and viewer bandwidth validation remains incomplete. No minimum hardware specification is established yet.

## Keep your adventure

Back up the complete data directory while the container is stopped. Before an upgrade, preserve that backup and the old image. New autosaves pair the game state with policy memory, a checksum, ROM identity, and the pinned PyBoy version. Startup can fall back to an earlier compatible save if the newest one is corrupt.

See [backup, restore, upgrades, rollback, and troubleshooting](operations.md). Event history and screenshots are kept indefinitely unless you explicitly configure retention.

## Build from source

Use a source checkout containing the updated setup command. Create `.env` from
`.env.example` for a new installation, add your ROM, and prepare the data directory
as shown in the [README](../README.md#run-your-own-adventure). Then run:

```sh
docker compose -f compose.yaml -f compose.build.yaml build
docker compose -f compose.yaml -f compose.build.yaml --profile setup run --rm prepare-data
docker compose -f compose.yaml -f compose.build.yaml up -d
```

For native development, follow [CONTRIBUTING.md](../CONTRIBUTING.md).

The updated source setup service uses `pokesim-prepare-data --download`. It downloads
the same pinned, checksum-verified reference archive as the desktop launcher.
Subsequent setup runs reuse valid prepared data without accessing the network.
Setup writes only the generated game-data bundle and preserves saves and the journal.
The source image must be built before using the updated Compose file. Published
rc31 images still need the original reference-checkout setup documented above.

For offline first setup, transfer the pinned archive described in the
[desktop guide](desktop.md#troubleshooting), then supply it read-only:

```sh
docker compose --profile setup run --rm --pull never \
  -v "$PWD/reference.zip:/reference.zip:ro" prepare-data \
  python -m pokesim.prepare_data --reference-archive /reference.zip
```

The original native command `pokesim-prepare-data /path/to/pokered` still accepts a
clean Git checkout at the pinned revision. Existing prepared adventures do not need
to regenerate data when moving to the new setup command.
