# PokeSim

### A little Pokémon adventure that keeps going while you're away.

Leave Kanto running on your desktop or server. Come back to a new catch, an evolved teammate, or a gym badge you weren't there to see. PokeSim plays Pokémon Red for you, with a live browser view that lets you follow the journey and take the controls whenever you feel like it.

Pick a favorite. Question its battle decisions. Get surprisingly attached to a Lapras named PICKLES.

**Desktop or server · Automatic play · Browser controls · Your own ongoing adventure**

[Take a look](#a-window-into-kanto) · [Make-it-yours options](#your-adventure-your-pace) · [Run your own](#run-your-own-adventure)

![PokeSim running Pokémon Red, with the live game, six teammates, current goal, and all eight badges](docs/images/live-adventure.jpg)

*The live adventure: the game, the team, and the plan (allegedly), all in one place.*

## A window into Kanto

PokeSim is something to check in on over coffee, keep open on a second screen, or leave exploring while you get on with your day.

- **Watch a team find its way.** Follow battles, catches, evolutions, and the journey toward the Pokémon League. See what the automatic player is trying to do next.
- **Jump in whenever you want.** Take over with keyboard or touch controls, then let automatic play continue. Slow things down to watch a battle or speed up the journey.
- **Get to know your Pokémon.** See your party's nicknames, levels, health, moves, and stats. There is a whole PC full of partners to browse beyond the traveling six.
- **Keep chasing the next discovery.** Collection, evolution, training, and exploration projects continue after the Hall of Fame.
- **Catch up on what you missed.** The Journal records milestones with screenshots. Subscribe in your feed reader, or add optional ntfy phone notifications for the moments you care about.

Game decisions run locally. There is no AI subscription, model API key, or per-move bill.

## The collection is part of the fun

Browse all 151 Kanto species, search by name or type, and see who's registered, who's been spotted, and who's still out there. Open an entry for moves, evolutions, and places to look.

![The Pokédex showing collection progress, search and filter options, and the original Kanto starters](docs/images/pokedex.jpg)

*One more entry. One more reason to check back.*

The PC lets you search your party and every storage box together, find your strongest Pokémon, and inspect each partner's stats and training.

<details>
<summary><strong>Look inside the PC</strong></summary>

![PC storage with all-box search, sorting options, and the strongest party and boxed Pokémon](docs/images/pc-storage.jpg)

*Yes, that Mewtwo is called CORNWIZARD.*

</details>

## Your adventure, your pace

| In the mood for… | Make it yours |
| --- | --- |
| Watching every little moment | Set playback to **1×**, or slow it to **0.5×**. |
| Checking back after a burst of progress | Choose **2× to 16×**, or **Max** speed. |
| Being the trainer for a while | Choose **Take control**, then **Let AI play** when you're done. |

The automatic player balances the badge journey with collecting and evolution projects, then keeps exploring after the Champion. Playback speed changes how fast the game runs. You can also pick Bulbasaur, Charmander, or Squirtle for a new adventure in the server settings, or leave the starter as a surprise.

Want two adventures growing together? Experimental Blue support and optional [automatic trading between trusted instances](docs/automatic-trading.md) let separately hosted games exchange Pokémon, including trade evolutions. Trading takes extra setup and is off by default.

**Still an experimental beta.** Runs have reached the Hall of Fame, but the automatic player can get stuck. A complete campaign, all 151 registrations, and uninterrupted long-term progress are not guaranteed. See [current progress and known limits](RELEASE_STATUS.md).

*Screenshots show a running v0.2.0rc28 adventure with an optional, locally supplied portrait pack. Portraits are not bundled. Public source and release downloads can lag behind this development version.*

## Run your own adventure

### On your desktop

The desktop launcher opens a local setup page in your browser. Choose your own clean **Pokémon Red (USA, Europe) ROM**, pick a starter, and let PokeSim prepare the adventure. Later launches resume your game. Blue support is experimental.

From this source checkout, install [uv](https://docs.astral.sh/uv/getting-started/installation/) and run:

```sh
uv run --python 3.12 --locked pokesim-desktop
```

For a persistent launch command, run `uv tool install --python 3.12 .` from the checkout, then launch with `pokesim-desktop` from any folder. Docker and a separate server are optional. First setup downloads verified reference data, then play works offline. Your ROM stays on your computer.

Close a browser tab to leave the game running. Choose **Desktop → Save and quit** to stop it. Your computer must stay awake for the adventure to advance.

Standalone desktop builds bundle Python and dependencies. The [v0.2.0rc31 release](https://github.com/afk-sapien/PokeSim/releases/tag/v0.2.0rc31) includes Windows x86-64, macOS Intel and Apple Silicon, and Linux x86-64 and ARM64 downloads. All five targets passed native build and bundled-runtime checks. See the [desktop installation and download guide](docs/desktop.md) for setup, save locations, and troubleshooting.

### On an always-on server

The commands below describe the Linux server setup using **Docker Engine with Compose, Git, and your own ROM**. Linux x86-64 is the existing tested prebuilt-image target. This is a release validation boundary, not a requirement for all PokeSim installations. Docker Desktop can also provide Linux containers on Mac and Windows, with host-specific setup adjustments.

A ROM is the game file you supply yourself. PokeSim does not include or download Pokémon ROMs.

The steps below build the source you check out. The first build needs internet access and can take a few minutes. After setup, the adventure runs locally without internet access unless you enable notifications.

### 1. Get PokeSim and add your game

```sh
git clone https://github.com/afk-sapien/PokeSim.git pokesim
cd pokesim
cp .env.example .env
sed -i 's/^POKESIM_IMAGE=.*/POKESIM_IMAGE=pokesim:local/' .env
mkdir -p roms data
sudo chown 10001:10001 data
```

Put your ROM at **`roms/pokered.gb`**. These steps are for a new installation. If you already have an adventure, [back it up before upgrading](docs/operations.md).

### 2. Prepare the adventure and start it

This one-time setup prepares the map and Pokédex information from a pinned reference checkout. It does not create a ROM.

```sh
git clone https://github.com/pret/pokered .reference/pokered
git -C .reference/pokered checkout a1a22aaf84d1675bcdbaeb194592379d586d838e
docker compose -f compose.yaml -f compose.build.yaml build
docker compose --profile setup run --rm --pull never prepare-data
docker compose up -d --pull never
```

### 3. Open your window into Kanto

On the same machine, open **[localhost:8930](http://localhost:8930)**. The adventure starts automatically and saves its progress in `data`. You can close the browser and come back later while the server keeps playing.

For a server in another room, or access away from home, follow the [authenticated HTTPS setup](docs/proxy.md). The default address is only reachable on the server itself. PokeSim has no built-in login, so protect remote access before sharing a link. Anyone with access to enabled controls can change or restart the game.

<details>
<summary><strong>A few useful server settings</strong></summary>

Edit `.env`, then run `docker compose up -d --pull never` to apply changes.

| Setting | What it does |
| --- | --- |
| `STARTER=bulbasaur` | Choose `bulbasaur`, `charmander`, `squirtle`, or `random` for a new run. |
| `SPEED=1` | Set the starting playback speed. `0` means unlimited. |
| `VIEWER_ONLY=1` | Disable game controls for spectators. This does not add a login. |
| `NTFY_URL=` | Add an ntfy topic URL for phone notifications. |
| `PUBLIC_URL=http://localhost:8930` | Set the address used in feed and notification links. |
| `HTTP_PORT=8930` | Choose the local browser port. |
| `DATA_PATH=./data` | Choose where the adventure and journal live. Use a separate directory for each game. |

Unlimited speed can use a full CPU core. Journal history and screenshots grow over time. Back up the complete data directory while the container is stopped. See [storage, backups, and maintenance](docs/operations.md) for the details.

</details>

Prefer a prebuilt image? Follow the [v0.2.0rc31 installation instructions](docs/self-hosting.md) for the Linux amd64 download.

## Follow along or help it grow

If this sounds like your kind of background adventure, star the project and check back for updates. Found a strange decision or have an idea that would make it more fun? [Open an issue](https://github.com/afk-sapien/PokeSim/issues).

- [Documentation index](docs/README.md)
- [Gameplay and feature guide](docs/guide.md)
- [PC views, trading offers, and Pokémon locks](docs/pc-trading.md)
- [Backups, updates, and troubleshooting](docs/operations.md)
- [Development and bug-reporting guide](CONTRIBUTING.md)
- [Security and private reporting](SECURITY.md)

## A small note on game content

PokeSim is an unofficial fan project, unaffiliated with Pokémon's rights holders. Original code is [MIT licensed](LICENSE). Pokémon ROMs, portrait packs, and generated game datasets are supplied locally and are not included in the distribution. To use your own portraits, place PNGs at `data/sprites/1.png` through `151.png`. Otherwise, the dashboard uses a neutral placeholder.

AI coding assistance was used during development and testing. The automatic player uses local rules. See [third-party notices](THIRD_PARTY_NOTICES.md) and [dependency licensing](docs/licensing.md).
