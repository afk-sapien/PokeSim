# PokeSim on your desktop

Open one PokeSim application to manage a library of independent adventures. Create several Red or Blue games, give each a name, and start or stop them independently. Every running adventure has its own emulator process, save files, journal, and policy state.

Install PokeSim as a Python package to run it on your desktop, or use one Docker container. The `pokesim-desktop` command opens the same Adventure Library in your browser. Docker is optional. Standalone executables and app bundles are outside the release scope.

## Install

One command with [pipx](https://pipx.pypa.io/stable/installation/), which also needs Git:

```sh
pipx install git+https://github.com/afk-sapien/PokeSim.git
```

That builds the current default branch. Add `@v0.3.6` to the URL to pin a release, or install a
released wheel without Git:

```sh
pipx install https://github.com/afk-sapien/PokeSim/releases/download/v0.3.6/pokesim-0.3.6-py3-none-any.whl
```

Without pipx, use `python -m pip install git+https://github.com/afk-sapien/PokeSim.git` inside a
virtual environment. Upgrade with `pipx upgrade pokesim`, which installs a newer version number, or
`pipx reinstall pokesim` to rebuild the current default branch. Remove it with `pipx uninstall pokesim`.

From a source checkout, [uv](https://docs.astral.sh/uv/getting-started/installation/) runs it
without installing: `uv run --python 3.12 --locked pokesim-desktop`, or
`uv tool install --python 3.12 .` for an installed command.

## First launch

```sh
pokesim-desktop
```

1. PokeSim opens your Adventure Library directly in the default browser. No sign-in or owner key is needed.
2. Choose **New adventure**, enter a name, select your own clean Pokémon Red or Blue (USA, Europe) ROM, and choose a starter.
3. Setup verifies the ROM and downloads a small pinned reference archive to prepare maps and Pokédex information. ROMs are never downloaded.
4. Start the adventure. Create another game whenever you want, including another copy of the same version.

Prepared adventures run offline. Adding another adventure can reuse an installed ROM and verified reference data. Each adventure keeps separate cartridge memory, even when several games share the same ROM file.

## Everyday use

- The Library lists running, stopped, starting, and failed adventures. Each game has a stable bookmarked address under `/games/<adventure-id>`.
- Closing a browser tab leaves the application running. Choose **Save and quit** in the application to save and stop all games.
- Opening PokeSim twice reopens the same application. The application and each adventure have exclusive process locks.
- A stopped adventure uses no emulator process. Starting it resumes from its saved checkpoint.
- Keep the computer awake to advance the games. Sleeping or powered-off computers do not accumulate simulated progress.
- Desktop launch uses an available loopback port, accessible only from your computer. The Library has no account or owner-key step. For remote access, use an authenticated reverse proxy or a trusted private network as described in [self-hosting](self-hosting.md). Anyone who can reach the Library can manage its adventures.

## Notifications

Choose **Notifications** in the Library to get milestones on your phone through [ntfy](https://ntfy.sh). Generate a random topic, subscribe to it in the ntfy app, send a test, and save. No account is needed. The page also chooses which adventures notify and which kinds of news are sent, and changes apply to running adventures right away. See the [guide](guide.md#notifications) for the full list.

## Simulation pace

Set the pace for all adventures in Library Settings. The default and recommended pace is 1×, so adventures unfold gradually and produce fewer notifications per hour. The live screen and individual adventure settings do not change pace. Newly created and restarted adventures inherit the global setting, which also applies to new Cable Club sessions. A cable session already in progress finishes at its starting pace.

The numbered choices go up to 16×, an application setting limit. Max removes deliberate waiting and runs as fast as the computer can handle. Its actual rate depends on gameplay, available CPU time, and the number of running adventures. Max is intended for testing. Taking manual control still runs that game at 1× until autonomous play resumes.

## Trading

Trading is automatic across all eligible running adventures in the same library. New adventures join automatically. There are no groups to configure or exchanges to choose. Each adventure’s Trading page shows only its own current exchange and recent completed trades, with the adventure navigation kept in place. Its history remains available while stopped. The Library’s Trading page provides an overview across all adventures. Participation requires a compatible game and an eligible boxed Pokémon. Active party members and locked Pokémon are protected.

Games finish battles or menus before preparing for an exchange. Interrupted exchanges recover automatically from their recorded decisions.

Preparation routes each adventure to a reachable Pokémon Center, using normal movement, battles, field moves, and PC input to retrieve the chosen individual. Games can use different centers. When the active box is full, preparation uses another box with space for a safe party reserve. Both games then enter a temporary paired Cable Club session. The games execute the exchange, evolution, and save. Both verified results must commit before ordinary play resumes. No direct Pokémon record swap is used as a fallback.

If every box and the party are full, preparation uses the existing duplicate cleanup rules to release one unprotected spare through the PC. The selected trade offer and locked Pokémon are protected. If there is no safe duplicate to release, the attempt stops and reports the storage problem.

The current adapter supports clean English Red and Blue at all twelve Cable Club centers, including the Indigo Plateau lobby. Each cartridge returns to its own original center after trading. An adventure without a supported route waits or reports a preparation failure. Trading pages show recent failed attempts and their reasons alongside completed exchanges. Link battles and trading with another application installation are not implemented.

Championship rewards and the one-time postgame Mew gift are enabled by default for new adventures. You can disable either feature in the adventure's Settings while it is stopped. Existing adventures keep their saved settings. These custom PokeSim gifts use an independent local gift transaction. League rewards apply to future victories while enabled. The Mew gift can catch up once if its original milestone was missed. Mew is excluded from repeatable League rewards. Having previously owned Mew permanently closes the event claim for that adventure, including after a checkpoint restore.

Each completed Elite Four and Champion run awards one random level-5 Pokémon with a random nickname,
with equal chances among the species this adventure has unlocked:

| Reward Pokémon | Requirement |
| --- | --- |
| Bulbasaur, Charmander, Squirtle | Complete a League run with rewards enabled |
| Eevee | Previously acquire Eevee or one of its evolutions |
| Omanyte, Kabuto, Aerodactyl | Previously acquire any fossil Pokémon or its evolution |
| Hitmonlee, Hitmonchan | Beat the Fighting Dojo's Karate Master |
| Mr. Mime | Previously acquire Mr. Mime |
| Jynx | Previously acquire Jynx |

Unlocks are per adventure and survive trading away a Pokémon or restoring a
checkpoint. Existing progress counts toward unlocks. This does not award gifts
for past League wins. The Library and live screen show total League wins,
including wins earned with rewards disabled, independently of reward counts.

## Your files and backups

| System | Default application folder |
| --- | --- |
| Windows | `%LOCALAPPDATA%\PokeSim\library` |
| macOS | `~/Library/Application Support/PokeSim/library` |
| Linux | `$XDG_DATA_HOME/pokesim/library`, or `~/.local/share/pokesim/library` |

The application folder contains its registry, installed assets, all adventure directories, interaction recovery records, and backups.

Adding a ROM decodes all 151 front portraits from it into `assets/sprites` inside this
application folder, so the collection pages are illustrated straight away. Every adventure shares
these images, including games created later. To use different artwork, place `1.png` through
`151.png` there yourself: an existing file is never overwritten. An adventure's own `sprites`
folder still overrides individual portraits. Everything stays local and is included in
whole-application backups.

Use **Settings and backups** for a consistent backup. The application coordinates saving before capturing the library. Alternatively, stop the application and copy its entire folder. Do not copy one participant's save files alone during a trade. Restore into an empty directory so an existing library cannot be overwritten accidentally.

To choose another application folder:

```sh
pokesim-desktop --data-dir "/path/to/my-library"
```

To import an older single-game installation, stop it first and back it up. Keep its matching ROM available. With the destination application stopped:

```sh
pokesim import "/path/to/old-data" --stopped --rom "/path/to/pokered.gb" --data-dir "/path/to/my-library"
```

The importer copies the adventure and reports its new ID. The original folder remains available. For the previous desktop launcher, supply the folder containing `rom.gb`, `settings.json`, and `adventure`. Never run old and new launchers against the same mutable files.

## Python installation and platform support

Python 3.11 or newer is required. Python 3.12 is the recommended tested installation version. pipx
and `uv tool install --python 3.12 .` both install PokeSim and its dependencies in an isolated
environment and put `pokesim-desktop` on your command path. Run `pipx ensurepath` (or
`uv tool update-shell`) if the tool directory is missing from your path, then open a new terminal.

Installing from a Git URL needs Git and builds the package locally. A released wheel needs neither.
For an ordinary virtual environment, activate it and run `python -m pip install .` from a checkout.
Start with `pokesim-desktop` or `python -m pokesim desktop`.

### Optional navigation acceleration

To try compiled pathfinding, install the optional extra from the checkout:

```sh
pipx install 'pokesim[acceleration] @ git+https://github.com/afk-sapien/PokeSim.git'
```

From a checkout, use `uv tool install --python 3.12 '.[acceleration]'`.
For an activated virtual environment, use `python -m pip install '.[acceleration]'`.
For a checkout launched directly with uv, use
`uv run --python 3.12 --locked --extra acceleration pokesim-desktop`.

The extra installs Numba and enables a compiled search loop. It preserves the
Python movement rules and route ordering. Compilation happens during game startup
and is cached on disk when possible. Each game uses more memory, and cold searches
can be slower even when repeated searches improve. See the
[decision benchmark guide](decision-benchmark.md) for measured results.

The ordinary installation continues to work without Numba. An unavailable or
failing compiled backend falls back to Python. Set the environment variable
`POKESIM_NAVIGATION_BACKEND=python` before launch to force the Python backend even
when Numba is installed. Restart the application after changing this setting.

The [Python install workflow](https://github.com/afk-sapien/PokeSim/actions/workflows/python-install.yml) builds and installs the wheel in a fresh environment on Windows x86-64, Intel macOS, Apple Silicon, and Linux x86-64 and ARM64. It checks the installed launcher and actual native worker processes using PyBoy's demonstration ROM. A successful run establishes validation for that platform. Other CPUs require compatible native dependencies and are not covered by this matrix.

This overhaul is development work. Older public releases do not contain the new library. Install this checkout until a package release containing it is published.

## Troubleshooting

- **No browser opens:** Run `pokesim-desktop --no-browser` and open the reported address. The Library opens directly.
- **Reference setup fails:** Retry with internet access. For offline setup, pass `--reference-archive "/path/to/reference.zip"`. Use the pinned [reference ZIP](https://codeload.github.com/pret/pokered/zip/a1a22aaf84d1675bcdbaeb194592379d586d838e), with SHA-256 `d651b4495b353b1521b42494e635aae2ffe9c89c3609f8cf166975c0bc723fcc`.
- **A game fails to start:** Inspect its error in the Library. Check available disk space and permissions. Other running games have independent processes.
- **An interaction needs recovery:** Keep both adventures and the application's interaction records together. Restart the application so it can finish the recorded decision. Never manually reload an older checkpoint to bypass a committed trade.
- **An old installation no longer starts:** Use `pokesim legacy` to explicitly run the old environment-configured single-adventure mode. Import it into the library when ready.

## Build and verify the Python package

```sh
uv sync --python 3.12 --locked --extra dev
uv run --locked python tools/prepare_test_data.py
uv build
uv run --locked python tools/check_package.py
uv run --locked python tools/check_python_install.py
```

The install check creates a temporary isolated environment, installs the built wheel and its dependencies, and launches the installed `pokesim-desktop` command outside the checkout. It verifies the Library, static assets, duplicate launch, CSRF protection, and clean shutdown. It then launches two actual worker processes and checks private credentials, independent save files, and shutdown when their parent closes its pipe.

These checks need no Pokémon ROM. Reference preparation and dependency installation require network access unless their inputs are already cached. Private ROM gameplay and cable-trading tests remain separate qualification requirements for each platform. Packages exclude private ROMs, saves, generated datasets, and portrait packs.

## Pokédex catch counts

Each species shows **Caught**, the number of successful captures recorded in this adventure, and **Have**, the number currently in the party and PC boxes. The entry details separate party and PC totals. The page summary adds up captures across all species.

Duplicate captures and Pokémon sent directly to the PC count. Gifts, trades, evolutions, failed throws, and the catching tutorial do not. Releasing, trading, or evolving a Pokémon does not subtract its original capture. Counts persist independently of journal retention and checkpoint restores. Replaying the exact same saved capture completion does not add a second receipt. An explicit adventure restart clears the counts for the new run.

Existing adventures begin tracking when the updated version first runs and display the tracking date. Older totals cannot be reconstructed reliably from Pokédex flags or the journal. Capture tracking uses verified English retail Red and Blue cartridge routines. Other ROMs display an unavailable catch count while still showing current ownership.

Automatic trade selection remembers which individual Pokémon have already belonged to each campaign. Returning an individual must unlock a new Pokédex entry, rather than repeat a previous quality upgrade. Among equally useful exchanges, the scheduler favors species traded less often in each adventure's last eight completed exchanges. It compares all eligible game pairs while preserving party, last-copy, project, and locked-Pokémon protections.
