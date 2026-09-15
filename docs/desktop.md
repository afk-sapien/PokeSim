# PokeSim on your desktop

Open one PokeSim application to manage a library of independent adventures. Create several Red or Blue games, give each a name, and start or stop them independently. Every running adventure has its own emulator process, save files, journal, and policy state.

The same application runs on a desktop or in one Docker container. A standalone desktop download includes Python and native dependencies. Docker is optional.

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

1. PokeSim opens your Adventure Library in the default browser and signs you in locally.
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
- Desktop launch uses an available loopback port. For access from another computer, follow [self-hosting](self-hosting.md).

## Trading

The application's Trading page coordinates eligible adventures in the same library. Participation requires a compatible game and an eligible boxed Pokémon. Active party members and locked Pokémon are protected.

Preparation uses normal walking and PC input to retrieve the chosen individual. Both games then enter a temporary paired Cable Club session. The games execute the exchange, evolution, and save. Both verified results must commit before ordinary play resumes. No direct Pokémon record swap is used as a fallback.

The current adapter supports clean English Red and Blue and the Vermilion Pokémon Center. An adventure without a supported route waits or reports a preparation failure. Link battles and trading with another application installation are not implemented.

Championship rewards and the one-time postgame Mew gift are separate optional custom PokeSim features. Enable them per adventure in Settings. They default to off and use an independent local gift transaction, without pausing another adventure or pretending the gift was a cable trade.

## Your files and backups

| System | Default application folder |
| --- | --- |
| Windows | `%LOCALAPPDATA%\PokeSim\library` |
| macOS | `~/Library/Application Support/PokeSim/library` |
| Linux | `$XDG_DATA_HOME/pokesim/library`, or `~/.local/share/pokesim/library` |

The application folder contains its registry, installed assets, all adventure directories, interaction recovery records, backups, and `owner.token`. Keep the owner credential private. It authorizes management of the application.

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

## Desktop downloads

This overhaul is development work. Older public releases do not contain the new library. Use a build from this checkout or a successful [Desktop builds workflow](https://github.com/afk-sapien/PokeSim/actions/workflows/desktop.yml). GitHub may require sign-in for workflow artifacts.

| Computer | Archive | Executable |
| --- | --- | --- |
| Windows x86-64 | `PokeSim-windows-amd64.zip` | `PokeSim/PokeSim.exe` |
| Mac with Apple Silicon | `PokeSim-darwin-arm64.zip` | `PokeSim.app` |
| Mac with an Intel processor | `PokeSim-darwin-x86_64.zip` | `PokeSim.app` |
| Linux x86-64 | `PokeSim-linux-x86_64.tar.gz` | `PokeSim/PokeSim` |
| Linux ARM64 | `PokeSim-linux-aarch64.tar.gz` | `PokeSim/PokeSim` |

Extract the entire archive and keep its supporting files together. Windows and macOS packages are unsigned and not notarized. The workflow declares these targets, but only a completed passing run verifies a particular build. Native Windows ARM64 and other architectures are not current packaging targets.

## Troubleshooting

- **No browser opens:** Run `pokesim-desktop --no-browser`, open the reported address, and sign in using the value in the application's `owner.token` file.
- **Reference setup fails:** Retry with internet access. For offline setup, pass `--reference-archive "/path/to/reference.zip"`. Use the pinned [reference ZIP](https://codeload.github.com/pret/pokered/zip/a1a22aaf84d1675bcdbaeb194592379d586d838e), with SHA-256 `d651b4495b353b1521b42494e635aae2ffe9c89c3609f8cf166975c0bc723fcc`.
- **A game fails to start:** Inspect its error in the Library. Check available disk space and permissions. Other running games have independent processes.
- **An interaction needs recovery:** Keep both adventures and the application's interaction records together. Restart the application so it can finish the recorded decision. Never manually reload an older checkpoint to bypass a committed trade.
- **An old installation no longer starts:** Use `pokesim legacy` to explicitly run the old environment-configured single-adventure mode. Import it into the library when ready.

## Build and verify

Build on the operating system and architecture of the intended download:

```sh
uv sync --python 3.12 --locked --extra dev --extra desktop-build
uv run --locked python tools/build_desktop.py
uv run --locked python tools/smoke_desktop.py dist/desktop/PokeSim/PokeSim
uv run --locked python tools/check_desktop_runtime.py dist/desktop/PokeSim/PokeSim
```

Use the platform-specific executable path from the table. The first smoke test checks the library, assets, duplicate launch, authorization, and clean shutdown. The second checks native dependencies, then launches two real bundled worker processes with PyBoy's demonstration ROM and verifies authenticated readiness, isolated saves, and shutdown when their parent closes its pipe.

These checks need no Pokémon ROM. Private ROM gameplay and cable-trading tests remain separate qualification requirements for each platform. Bundles contain notices and dependency sources, and exclude private ROMs, saves, generated datasets, and portrait packs.
