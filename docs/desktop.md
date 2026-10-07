# PokeSim on your desktop

Open one PokeSim application to manage a library of independent adventures. Create several Red or Blue games, give each a name, and start or stop them independently. Every running adventure has its own emulator process, save files, journal, and policy state.

Install PokeSim as a Python package to run it on your desktop, or use one Docker container. The `pokesim-desktop` command opens the same Adventure Library in your browser. Docker is optional. Standalone executables and app bundles are outside the release scope.

## Install

### Package-manager setup (recommended)

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) using your
platform's package manager. uv installs PokeSim in its own environment and manages
Python 3.12 for it. Internet access is required.

Windows, using [WinGet](https://learn.microsoft.com/en-us/windows/package-manager/winget/):

```powershell
winget install --id astral-sh.uv --exact
```

macOS, with [Homebrew](https://brew.sh/) installed:

```sh
brew install uv
```

Linux, with [pipx](https://pipx.pypa.io/stable/installation/) installed through your
distribution's package manager:

```sh
pipx install uv
pipx ensurepath
```

Open a new terminal so it can find uv. Install the current public PokeSim release:

```sh
uv tool install --python 3.12 --managed-python https://github.com/afk-sapien/PokeSim/releases/download/v0.4.20/pokesim-0.4.20-py3-none-any.whl
uv tool update-shell
```

Open another terminal and run `pokesim-desktop`. Your browser opens the Adventure
Library. Install and run PokeSim as your normal user, without sudo or an
administrator terminal. No system Python, Git, Docker, or ROM is needed during
this package installation.

PokeSim's package comes from this project's [GitHub releases](https://github.com/afk-sapien/PokeSim/releases).
Do not use `pip install pokesim` from PyPI, which is not this project's release channel.
On Windows, the Python package installation creates the `pokesim-desktop.exe`
launcher. There is no separate PokeSim EXE download in this installation flow.

### Other Python package managers

With pipx and Python 3.12 already installed, you can install PokeSim directly:

```sh
pipx install --python python3.12 https://github.com/afk-sapien/PokeSim/releases/download/v0.4.20/pokesim-0.4.20-py3-none-any.whl
pipx ensurepath
```

On Windows, replace `python3.12` with the full path to your Python 3.12 `python.exe`.
Open a new terminal after PATH setup. A released wheel needs no Git.

Without uv or pipx, create a virtual environment with Python 3.12, activate it,
and use `python -m pip install` with the wheel URL above. Avoid installing into
system Python.

### Advanced: installer scripts

The optional scripts bootstrap uv, managed Python 3.12, the released PokeSim
package, and its dependencies. They execute downloaded code. The package-manager
instructions above are the recommended desktop path.

macOS and Linux:

```sh
curl -fsSL https://github.com/afk-sapien/PokeSim/releases/latest/download/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://github.com/afk-sapien/PokeSim/releases/latest/download/install.ps1 | iex"
```

To review a script first, download
[the released install.sh](https://github.com/afk-sapien/PokeSim/releases/latest/download/install.sh)
or [the released install.ps1](https://github.com/afk-sapien/PokeSim/releases/latest/download/install.ps1),
read it, then run `sh install.sh` or
`powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1`.
The PowerShell execution-policy option applies to that process only.

The scripts reuse uv if installed. Otherwise they install it in `~/.local/bin`,
with no shell-profile changes. They check the installed launcher and print its
full path. Follow the printed `uv tool update-shell` command and open a new
terminal to use `pokesim-desktop`, or use the full launch command printed by the
installer. Installation does not start a server.

### Update or remove

Choose **Save and quit** before updating, and keep a backup from **Settings and backups**.
For a uv or pipx installation,
run `uv tool install --python 3.12 --managed-python --upgrade NEW_WHEEL_URL` or
`pipx install --force NEW_WHEEL_URL`, using the wheel from the desired
[release](https://github.com/afk-sapien/PokeSim/releases).
A wheel URL pins a version. `pipx upgrade pokesim` or `uv tool upgrade pokesim` alone
does not select a new GitHub release URL. If you used an optional installer
script, rerun the script from the desired release to install its selected version.

Remove the installed application with `uv tool uninstall pokesim` or `pipx uninstall pokesim`,
matching the installer you used. Your library and saves remain in the application folder.

### From source

To work on the current checkout, see [CONTRIBUTING.md](../CONTRIBUTING.md).
With uv, run `uv run --python 3.12 --locked pokesim-desktop` from the checkout, or
`uv tool install --python 3.12 .` for an installed command. Git URL installs build the
current default branch and require Git, so the released wheel is simpler for ordinary use.

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

Choose **Notifications** in the Library to receive milestones through ntfy, Discord or Telegram. Select a provider, enter its destination, send a test, and save. Choose which adventures notify and which kinds of news are sent. Changes apply to running adventures right away. See the [setup guide](guide.md#notifications).

## Simulation pace

Open an adventure's **Settings** in the Library to set its own simulation speed.
Changes apply while it runs and survive restarts. New adventures default to 1×.
Upgrading copies the previous global speed into every existing adventure once.
There is no global speed control or application limit on running adventures.
Start and stop whichever games you want.

Choices range from 0.5× to 16×, plus Max. Max runs as fast as the computer can
handle. The Library's actual-speed reading shows the achieved rate, which can be
lower than the requested speed when resources are busy. Manual control temporarily
runs that game at 1×. Settings are frozen during a reserved trade. Cable Club
sessions use the slower participant's selected speed, with Max treated as
unlimited. Both games retain their own settings afterward.

## Trading

Trading is automatic across all eligible running adventures in the same library. New adventures join automatically. There are no groups to configure or exchanges to choose. Each adventure’s Trading page shows only its own current exchange and recent completed trades, with the adventure navigation kept in place. Its history remains available while stopped. The Library’s Trading page provides an overview across all adventures. Participation requires a compatible game and an eligible boxed Pokémon. Active party members and locked Pokémon are protected.

Games finish battles or menus before preparing for an exchange. Interrupted exchanges recover automatically from their recorded decisions.

Preparation routes each adventure to a reachable Pokémon Center, using normal movement, battles, field moves, and PC input to retrieve the chosen individual. Games can use different centers. When the active box is full, preparation uses another box with space for a safe party reserve. Both games then enter a temporary paired Cable Club session. The games execute the exchange, evolution, and save. Both verified results must commit before ordinary play resumes. No direct Pokémon record swap is used as a fallback.

If every box and the party are full, preparation uses the existing duplicate cleanup rules to release one unprotected spare through the PC. The selected trade offer and locked Pokémon are protected. If there is no safe duplicate to release, the attempt stops and reports the storage problem.

The current adapter supports clean English Red and Blue at all twelve Cable Club centers, including the Indigo Plateau lobby. Each cartridge returns to its own original center after trading. An adventure without a supported route waits or reports a preparation failure. Trading pages show recent failed attempts and their reasons alongside completed exchanges. Link battles and trading with another application installation are not implemented.

League rewards grant a random level-5 starter after each new victory while enabled.
Mew's first custom gift follows becoming Champion. Another Mew requires a million
new steps and then another League victory. Eevee, fossil expeditions, dojo rematches,
and supported NPC exchanges return through separate walking requirements.

Stop an adventure to change reward intervals and fossil or dojo preferences in
Library settings. Journal Stats shows progress. See [Walking rewards and return
visits](step-rewards.md) for defaults, eligibility, and restore behavior.

The Library and live screen show total League wins, including wins earned with
rewards disabled, independently of reward counts.

## Your files and backups

| System | Default application folder |
| --- | --- |
| Windows | `%LOCALAPPDATA%\PokeSim\library` |
| macOS | `~/Library/Application Support/PokeSim/library` |
| Linux | `$XDG_DATA_HOME/pokesim/library`, or `~/.local/share/pokesim/library` |

The application folder contains its registry, installed assets, all adventure directories, interaction recovery records, and backups.

Starting an adventure decodes all 151 front portraits from its ROM into `assets/sprites`
after automatic reference setup. Every adventure shares
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

## Troubleshooting

- **`pokesim-desktop` or `uv` is not recognized:** Use the full path printed by the installer. Run its `uv tool update-shell` command and open a new terminal. For pipx, use `pipx ensurepath`.
- **An executable already exists from another installer:** Keep using that installer, or uninstall its PokeSim package before switching between pipx and uv. Uninstalling the package keeps your library and saves.
- **Python version, compiler, or PyBoy build error:** Use the automatic installer or the manual uv command above to select Python 3.12. A newer system Python may lack compatible dependency wheels on your platform. Include your OS, CPU, and the complete error in a [support request](../SUPPORT.md).
- **`externally-managed-environment`:** Use the installer, uv, pipx, or a virtual environment. Do not use sudo pip or override your system's package protections.
- **Download or certificate error:** Check your connection and any proxy configuration, then retry. Do not disable TLS verification.

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

Each species shows **Caught**, the number of successful captures and custom reward gifts recorded in this adventure, and **Have**, the number currently in the party and PC boxes. The entry details separate party and PC totals. The page summary adds up captures across all species.

Duplicate captures, Pokémon sent directly to the PC, committed League reward gifts, and the custom Mew gift count. Saved custom reward journal entries are backfilled once. Ordinary cartridge gifts, trades, evolutions, failed throws, and the catching tutorial do not count. Releasing, trading, or evolving a Pokémon does not subtract its original capture. Counts persist independently of journal retention and checkpoint restores. Replaying the exact same saved capture completion does not add a second receipt. An explicit adventure restart clears the counts for the new run.

Existing adventures begin tracking when the updated version first runs and display the tracking date. Missing wild-capture totals cannot be reconstructed reliably from Pokédex flags or journal summaries. Capture tracking uses verified English retail Red and Blue cartridge routines. Other ROMs display an unavailable catch count while still showing current ownership.

Automatic trade selection remembers which individual Pokémon have already belonged to each campaign. Returning an individual must unlock a new Pokédex entry, rather than repeat a previous quality upgrade. Among equally useful exchanges, the scheduler favors species traded less often in each adventure's last eight completed exchanges. It compares all eligible game pairs while preserving party, last-copy, project, and locked-Pokémon protections.
