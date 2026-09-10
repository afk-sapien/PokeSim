# PokeSim

A Pokémon Red adventure that plays itself on your server. Watch the game in your browser, follow the party and collection, take over the controls, and subscribe to an Atom feed of catches and milestones. Optional ntfy notifications bring those events to your phone.

Game decisions run locally through a rule-based policy. No model service or API key is required.

**Experimental beta:** the policy can get stuck, and a complete campaign is not guaranteed. The 48-hour reliability test and fresh-game campaign are still running. See [validation and known limits](RELEASE_STATUS.md).

## Install with Docker Compose

The prebuilt release supports **Linux amd64** with Docker Engine and the Compose plugin. Supply your own clean Pokémon Red (USA, Europe) ROM. ROMs, sprites, and game datasets are not bundled. Blue and ARM do not yet have equivalent release validation.

Clone the public release source:

```sh
git clone --branch v0.2.0rc2 --depth 1 https://github.com/afk-sapien/PokeSim.git pokesim
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
curl -fL --retry 3 -o image-linux-amd64.tar.gz https://github.com/afk-sapien/PokeSim/releases/download/v0.2.0rc2/image-linux-amd64.tar.gz
curl -fL --retry 3 -o SHA256SUMS https://github.com/afk-sapien/PokeSim/releases/download/v0.2.0rc2/SHA256SUMS
sha256sum --ignore-missing -c SHA256SUMS
```

Confirm that the image archive reports `OK`, then load and start it:

```sh
docker load -i image-linux-amd64.tar.gz
docker compose --profile setup run --rm --pull never prepare-data
docker compose up -d --pull never
docker compose logs --tail=50 pokesim
```

Open [localhost:8930](http://localhost:8930). The archive loads the exact image tag `pokesim:0.2.0rc2`. Releases are distributed as downloadable Docker archives, so there is no `docker compose pull` step. The [release page](https://github.com/afk-sapien/PokeSim/releases/tag/v0.2.0rc2) also provides source packages, Compose files, a dependency inventory, and a manifest with the image ID and source revision.

The setup command parses the pinned source checkout and writes verified game data into `./data`. It does not build or download a ROM. The runtime uses the local data afterward and does not require that source checkout or internet access unless notifications are enabled.

Progress, policy memory, screenshots, and the journal live in `./data`. The container runs as user and group 10001 with a read-only root filesystem and read-only ROM. Do not point two running containers at the same data directory.

## Access and controls

The default port is accessible only on the Docker host. For remote access, use the [authenticated HTTPS proxy recipe](docs/proxy.md) or a private network. The app has no built-in authentication. Anyone who can reach an instance with controls enabled can control, reset, and rewind its game.

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

Unlimited speed can use a full CPU core. Long-term memory, storage, and viewer bandwidth measurements are still in progress. No minimum hardware specification is established yet.

## Keep your adventure

Back up the complete data directory while the container is stopped. Before an upgrade, preserve that backup and the old image. New autosaves pair the game state with policy memory, a checksum, ROM identity, and the pinned PyBoy version. Startup can fall back to an earlier compatible save if the newest one is corrupt.

See [backup, restore, upgrades, rollback, and troubleshooting](docs/operations.md). Event history and screenshots are kept indefinitely unless you explicitly configure retention.

## Build from source

After preparing the ROM, data directory, and source checkout above:

```sh
docker compose -f compose.yaml -f compose.build.yaml build
docker compose -f compose.yaml -f compose.build.yaml --profile setup run --rm prepare-data
docker compose -f compose.yaml -f compose.build.yaml up -d
```

For native development, follow [CONTRIBUTING.md](CONTRIBUTING.md).

## Feedback and licensing

Please report installation problems and reproducible gameplay issues through [GitHub issues](https://github.com/afk-sapien/PokeSim/issues). Include the release version, operating system, architecture, ROM hash, and sanitized logs. Do not upload ROMs, saves, screenshots containing private details, or tokens. Security issues should use [private vulnerability reporting](https://github.com/afk-sapien/PokeSim/security/advisories/new).

Original code is [MIT licensed](LICENSE). Game content is supplied locally and has separate rights. The dashboard uses an original neutral portrait by default. Optional user-supplied PNG portraits can go in `data/sprites/1.png` through `151.png`. They are never fetched automatically.

This project is unofficial and unaffiliated with Pokémon's rights holders. AI coding assistance was used during development and testing. Runtime game decisions use local rules rather than an AI service.

- [Detailed features and policy guide](docs/guide.md)
- [Security and support policy](SECURITY.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [Dependency source and modification instructions](docs/licensing.md)
