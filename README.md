# PokeSim

### A little Pokémon adventure that keeps going while you're away.

Leave Kanto running on your desktop or server. Come back to a new catch, an evolved teammate, or a gym badge you weren't there to see. PokeSim plays Pokémon Red and Blue for you, with a live browser view that lets you follow the journey and take the controls whenever you feel like it.

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

The PC lets you search your party and every storage box together, sort by DV star rating, and inspect each partner's stats and training. Four stars mark perfect DVs. The Pokédex keeps track of species with three-star or better partners.

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

The automatic player balances the badge journey with collecting and evolution projects, then keeps exploring after the Champion. Playback speed changes how fast the game runs. You can also pick Bulbasaur, Charmander, or Squirtle for a new adventure when creating an adventure, or leave the starter as a surprise. Simulation pace is shared across the library.

Keep several adventures in one library, including multiple Red and Blue games. Each has independent saves and controls. The application coordinates eligible games through real Cable Club trading, including game-driven trade evolution. See the [desktop and trading guide](docs/desktop.md).

**Still an experimental beta.** Runs have reached the Hall of Fame, but the automatic player can get stuck. A complete campaign, all 151 registrations, and uninterrupted long-term progress are not guaranteed. See [current progress and known limits](RELEASE_STATUS.md).

*Screenshots show a running v0.2.0rc28 adventure with an optional, locally supplied portrait pack. Portraits are not bundled. Screenshots are illustrative. Older release downloads contain the previous single-game application.*

## Run your own adventure

### Python package on your desktop

Launch the Adventure Library, add your own clean **Pokémon Red or Blue (USA, Europe) ROM**, and create one or more named adventures. Start and stop each game independently. Your ROM stays on your computer.

From this source checkout, install [uv](https://docs.astral.sh/uv/getting-started/installation/) and run:

```sh
uv run --python 3.12 --locked pokesim-desktop
```

For a command available from any folder, install with `uv tool install --python 3.12 .`, then run `pokesim-desktop`. Docker and an always-on server are optional. First setup downloads verified reference data, then prepared games work offline.

[Optional Numba acceleration](docs/desktop.md#optional-navigation-acceleration) can speed up repeated path searches at the cost of more memory and startup work. The normal installation uses the Python backend.

The Library opens directly without a sign-in or owner key. Desktop launch and the default Docker port are local-only. For remote access, use an authenticated reverse proxy or a trusted private network. Anyone who can reach the Library can manage its adventures.

Closing a browser tab keeps the games running. Use **Save and quit** to save and stop the application. Your computer must stay awake for games to advance.

Python installation and Docker are the supported distribution paths. The Python install checks target Windows x86-64, macOS Intel and Apple Silicon, and Linux x86-64 and ARM64. Successful CI runs establish platform validation. Older releases do not contain this new library. See the [desktop installation guide](docs/desktop.md) for installation, data locations, import, and troubleshooting.

### In one Docker container

The server runs the same library and child-process architecture. One persistent application folder contains its independent adventures and shared assets. This is development source, so build this checkout rather than using an older public image.

```sh
git clone https://github.com/afk-sapien/PokeSim.git pokesim
cd pokesim
cp .env.example .env
mkdir -p pokesim-app
sudo chown 10001:10001 pokesim-app
docker compose -f compose.yaml -f compose.build.yaml build
docker compose up -d --pull never
```

Open [localhost:8930](http://localhost:8930) and create adventures in the Library. No sign-in or owner key is required. Setup accepts your own ROMs and prepares the pinned reference data. No ROMs are bundled or downloaded.

The default port is reachable only on the host. For remote access, configure `PUBLIC_URL` to match the external address and use HTTPS. See [self-hosting](docs/self-hosting.md) for configuration and migration.

**Existing installations:** Stop and back up each old adventure before importing it into a fresh application folder. The original single-game launch is available as `pokesim legacy`, with its Compose configuration preserved in `compose.legacy.yaml`. Never attach the legacy trading coordinator and the new manager to the same adventures.

## Follow along or help it grow

If this sounds like your kind of background adventure, star the project and check back for updates. Found a strange decision or have an idea that would make it more fun? [Open an issue](https://github.com/afk-sapien/PokeSim/issues).

- [Gameplay and feature guide](docs/guide.md)
- [Backups, updates, and troubleshooting](docs/operations.md)
- [Development and bug-reporting guide](CONTRIBUTING.md)
- [Security and private reporting](SECURITY.md)

## A small note on game content

PokeSim is an unofficial fan project, unaffiliated with Pokémon's rights holders. Original code is [MIT licensed](LICENSE). Pokémon ROMs, portrait packs, and generated game datasets are supplied locally and are not included in the distribution. To use your own portraits, place `1.png` through `151.png` in the application's `assets/sprites` folder. Every adventure shares the pack. Legacy single-game mode uses `data/sprites`. Without a supplied image, the dashboard uses a neutral placeholder.

AI coding assistance was used during development and testing. The automatic player uses local rules. See [third-party notices](THIRD_PARTY_NOTICES.md) and [dependency licensing](docs/licensing.md).
