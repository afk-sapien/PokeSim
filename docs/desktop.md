# PokeSim on your desktop

Open one PokeSim application to manage a library of independent adventures. Create several Red or Blue games, give each a name, and start or stop them independently. Every running adventure has its own emulator process, save files, journal, and policy state.

Install PokeSim as a Python package to run it on your desktop, or use one Docker container. The `pokesim-desktop` command opens the same Adventure Library in your browser. Docker is optional. Standalone executables and app bundles are outside the release scope.

## First launch

From this source checkout, install [uv](https://docs.astral.sh/uv/getting-started/installation/) and run:

```sh
uv run --python 3.12 --locked pokesim-desktop
```

For an installed command:

```sh
uv tool install --python 3.12 .
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

## Trading

Trading is automatic across all eligible running adventures in the same library. New adventures join automatically. There are no groups to configure or exchanges to choose. Each adventure’s Trading page shows only its own current exchange and recent completed trades, with the adventure navigation kept in place. Its history remains available while stopped. The Library’s Trading page provides an overview across all adventures. Participation requires a compatible game and an eligible boxed Pokémon. Active party members and locked Pokémon are protected.

Games finish battles or menus before preparing for an exchange. Interrupted exchanges recover automatically from their recorded decisions.

Preparation uses normal walking and PC input to retrieve the chosen individual. Both games then enter a temporary paired Cable Club session. The games execute the exchange, evolution, and save. Both verified results must commit before ordinary play resumes. No direct Pokémon record swap is used as a fallback.

The current adapter supports clean English Red and Blue and the Vermilion Pokémon Center. An adventure without a supported route waits or reports a preparation failure. Link battles and trading with another application installation are not implemented.

Championship rewards and the one-time postgame Mew gift are separate optional custom PokeSim features. Enable them per adventure in Settings. They default to off and use an independent local gift transaction, without pausing another adventure or pretending the gift was a cable trade.

## Your files and backups

| System | Default application folder |
| --- | --- |
| Windows | `%LOCALAPPDATA%\PokeSim\library` |
| macOS | `~/Library/Application Support/PokeSim/library` |
| Linux | `$XDG_DATA_HOME/pokesim/library`, or `~/.local/share/pokesim/library` |

The application folder contains its registry, installed assets, all adventure directories, interaction recovery records, and backups.

To use an existing portrait pack, place `1.png` through `151.png` in `assets/sprites` inside this application folder. Every adventure shares these images, including games created later. An adventure's own `sprites` folder can override individual portraits. Packs stay local and are included in whole-application backups.

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

Python 3.11 or newer is required. Python 3.12 is the recommended tested installation version. `uv tool install --python 3.12 .` installs this checkout and its dependencies in an isolated environment and makes `pokesim-desktop` available on your command path. Run `uv tool update-shell` if uv reports that its tool directory is missing from your path, then open a new terminal.

For an ordinary virtual environment, activate it and run `python -m pip install .` from the checkout. Start with `pokesim-desktop` or `python -m pokesim desktop`.

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
