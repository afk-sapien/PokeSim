# PokeSim on your desktop

PokeSim can run on your own computer with a local browser dashboard. The desktop launcher manages first-run setup, save locations, and shutdown. Docker, Git, and a separate Python installation are not needed when using a standalone desktop download.

## Desktop downloads

Download the standalone archives and their checksums from the [v0.2.0rc31 release](https://github.com/afk-sapien/PokeSim/releases/tag/v0.2.0rc31). All five targets passed native build, launcher, and bundled-runtime checks in the [release validation run](https://github.com/afk-sapien/PokeSim/actions/runs/35045201890). Older releases, including v0.2.0rc6, do not contain the desktop launcher.

The workflow builds these targets and tests each bundle on its own operating system:

| Computer | Download name | Open after extracting |
| --- | --- | --- |
| Windows, Intel or AMD 64-bit | `PokeSim-windows-amd64.zip` | `PokeSim/PokeSim.exe` |
| Mac with Apple Silicon | `PokeSim-darwin-arm64.zip` | `PokeSim.app` |
| Mac with an Intel processor | `PokeSim-darwin-x86_64.zip` | `PokeSim.app` |
| Linux x86-64 | `PokeSim-linux-x86_64.tar.gz` | `PokeSim/PokeSim` |
| Linux ARM64 | `PokeSim-linux-aarch64.tar.gz` | `PokeSim/PokeSim` |

Extract the entire download. Keep its supporting files together. GitHub workflow artifacts add an outer ZIP, which you extract first. macOS and Windows bundles currently have no publisher signing or notarization, so the operating system may block or warn about opening them. Use the source installation if your device policy requires signed applications.

The workflow configuration is not proof that every target has passed. Check the associated workflow result before distributing a build. Native Windows ARM64 and other CPU architectures are not build targets yet. Linux bundles should be built on a distribution no newer than the oldest one you intend to support, because the system C library is not bundled.

## First launch

1. Open PokeSim. It opens a private setup page in your default browser.
2. Choose your own clean Pokémon Red (USA, Europe) `.gb` file. Pokémon Blue is experimental. Extract ZIP files first. Modified ROMs are not accepted by desktop setup.
3. Pick a starter, or choose **Surprise me**.
4. Select **Start my adventure**. Setup downloads about 2 MB of pinned reference source, verifies its SHA-256 checksum, and generates maps and Pokédex information locally. A ROM is never downloaded.
5. The live adventure opens when ready.

PokeSim keeps a copy of the ROM in its data folder, so moving the original does not break later launches. Prepared adventures start without internet access. The desktop launcher keeps automatic trading off. Use the server deployment for multi-instance trading.

## Everyday use

- Open PokeSim again to resume. A second launch reopens the existing launcher and does not start another emulator against the same saves.
- Closing a browser tab keeps the adventure running. Return to the app by launching PokeSim again.
- Select **Desktop** in the live dashboard, then **Save and quit**, to save and stop the process.
- Keep the computer awake if you want the game to keep playing. Sleep pauses execution. PokeSim does not invent progress for time spent asleep or powered off.
- The app chooses an available local port automatically. Only this computer can reach the desktop service. Use the server setup for remote access.

## Install from Python source

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), download or clone this version of the source, and open a terminal in that folder:

```sh
uv run --python 3.12 --locked pokesim-desktop
```

This uses the repository's locked dependencies. To install a command you can run from any directory:

```sh
uv tool install --python 3.12 .
pokesim-desktop
```

The tool installation resolves dependencies from package metadata. The checkout command uses the lockfile. Python users can also install the checkout with `python -m pip install .` inside a Python 3.11 or newer virtual environment. Python 3.12 is the desktop build target.

First-run reference setup uses a verified archive, so Git is not required after obtaining the PokeSim source. The existing `pokesim` and `python -m pokesim` commands continue to run the environment-configured service for server deployments.

## Your files

| System | Default data folder |
| --- | --- |
| Windows | `%LOCALAPPDATA%\PokeSim` |
| macOS | `~/Library/Application Support/PokeSim` |
| Linux | `$XDG_DATA_HOME/pokesim`, or `~/.local/share/pokesim` |

The launcher shows the exact location under **Your files & troubleshooting**. This folder contains `settings.json`, `rom.gb`, generated `game-data`, an `adventure` folder with saves and SQLite, and rotating `desktop.log` files. Updating the program does not replace this folder.

Back up the entire folder after **Save and quit** completes. It contains private game files, so do not attach it to public bug reports. Directory metadata flushing is unavailable through Python on Windows. File contents are flushed before atomic replacement, but crash durability can differ from Unix. Keep backups on every platform.

For another independent adventure or a custom location:

```sh
pokesim-desktop --data-dir "/path/to/another-adventure"
```

The desktop folder layout differs from the server's data volume. Do not point the launcher directly at an existing server data folder. To migrate, stop both instances, back up the server data, copy its contents into the desktop folder's `adventure` subfolder, and supply the same ROM through desktop setup. Existing checkpoint compatibility checks still apply.

## Troubleshooting

- **The browser did not open:** Run `pokesim-desktop --no-browser` and open the printed local address. For a standalone bundle, pass the same option to its executable.
- **Setup could not download reference data:** Check your internet connection and retry. Setup verifies a pinned archive. If the provider changes that archive, installation will stop until the checksum is reviewed and updated.
- **Offline setup:** Transfer the ZIP at `https://codeload.github.com/pret/pokered/zip/a1a22aaf84d1675bcdbaeb194592379d586d838e` from an online computer. Pass `--reference-archive "/path/to/reference.zip"`. It must match SHA-256 `d651b4495b353b1521b42494e635aae2ffe9c89c3609f8cf166975c0bc723fcc`. Once preparation succeeds, subsequent launches do not need this ZIP.
- **Already running:** Launching twice usually reopens the existing page. If it is still starting or saving, wait a moment and retry. The operating system releases the process lock after a crash. Do not delete the lock file while PokeSim is running.
- **A save or startup failed:** The launcher keeps the error visible and writes details to `desktop.log`. Fix disk space or file permissions before retrying. A failed save is not reported as a successful save.

## Build a standalone application

Build on the operating system and CPU architecture that will run the download:

```sh
uv sync --python 3.12 --locked --extra dev --extra desktop-build
uv run --locked python tools/build_desktop.py
```

Downloads appear in `dist/desktop`. On macOS, packaging uses `ditto` to preserve bundle links and executable permissions. Bundles include dependency notices, the pinned PyBoy source archive, and project source needed for inspection and rebuilding. They exclude user-supplied ROMs, game datasets, saves, and portraits. PyBoy's own demonstration ROM remains part of that dependency.

Verify a Linux bundle with:

```sh
uv run --locked python tools/smoke_desktop.py dist/desktop/PokeSim/PokeSim
```

Use the corresponding executable path from the table on Windows or macOS. The smoke test uses a temporary data folder and no Pokémon ROM. It checks setup, assets, duplicate launch handling, request protection, and clean shutdown. Private ROM testing is still needed to validate gameplay, save, and resume on each target.

The workflow also runs the bundle with `--check-runtime`. This checks verified reference setup, dependency metadata, the database, web resources, and the native emulator using PyBoy's own demo ROM in a temporary folder. It accepts `--reference-archive` for an offline diagnostic.
