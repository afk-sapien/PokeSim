# PokeSim 0.4.5 experimental beta

Easier installation on your computer or home server.

## Install with one command

The macOS/Linux shell installer and Windows PowerShell installer set up uv, Python 3.12,
and PokeSim for your user account. No Git, pipx, or system Python installation is needed.
Each installer prints the full launch command and checks that the launcher loads.
See the [installation guide](https://github.com/afk-sapien/PokeSim#running-it).

## Docker without the ownership step

New installations can use `compose.quickstart.yaml`, which stores the library in a
persistent Docker volume. No manual data-folder creation or `chown` is needed.
Custom local HTTP ports now update the default browser URL automatically.
The authenticated proxy recipe supports the same volume and preserves existing libraries.

## Clearer instructions and tested release downloads

Desktop setup, updates, backups, remote access, and troubleshooting instructions now
describe the current Adventure Library. Retired single-game instructions are archived.
Installer scripts and the quick-start Compose file are included in the checksummed release
downloads. The release remains a draft until all downloads are verified.

## Upgrading

Back up the complete library, stop PokeSim, and select version 0.4.5. Keep your existing
Docker data mount and project name. The quick-start configuration is for new libraries.
No game-data or save-format migration is introduced by this release.

Docker images remain Linux amd64. Use the native Python installer on supported ARM64 systems.
