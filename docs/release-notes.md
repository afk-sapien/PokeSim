# PokeSim 0.5.0 experimental beta

This release changes the emulator under every adventure and adds Yellow, Gold, Silver and Crystal.

- **Rust emulator.** Games now run on PyBoy RS, a Rust port of PyBoy 2.7.0, through
  PokeSim Core 0.2. Installation needs no Rust toolchain: PyBoy RS ships as a wheel.
  The Docker image is built from the same wheel.
- **Generation II.** Gold, Silver and Crystal adventures play through Johto, the League,
  Kanto and Red, with breeding, held items, all 251 species, Gen II Cable Club trading and
  the Time Capsule with Red and Blue. They run on the Rust backend only. Full campaigns from a
  new game were played on development builds that used PyBoy 2.7.0 and have not been re-run on
  the Rust backend. Restart, `.sav` export, clock, Time Capsule and Cable Club exchange were
  verified on it for every game.
- **Pokémon Yellow.** Yellow adventures start with Pikachu, follow Yellow's own story and
  trade with Red and Blue over the Cable Club and with Gold, Silver and Crystal through the
  Time Capsule. A new Yellow game was played to the Champion on the Rust backend, and both
  kinds of trade were completed in the Library.
- **Real-time clock.** Each Gen II adventure keeps its cartridge clock. See the
  [Gen II notes](gen2-exploration.md) for what is verified and what is not.
- **Fixes carried over.** The 0.4.20 PP menu fix, a Game Corner prize-menu detection fix, and shiny protection
  after Transform (the wild Pokémon's original DVs are now read by Core).

## Upgrading is one-way for Gen II

Back up the complete library first, as a copy of the whole data directory, before you
start the new version.

- Red and Blue adventures need no restore. Their checkpoints and manifests still carry the
  `pyboy_version` tag that 0.4.x checks, and the Rust state format is the PyBoy 2.7.0 format.
- Yellow, Gold, Silver and Crystal adventures need 0.5.0 or later, because 0.4.x supports neither
  Yellow nor Gen II.
  Restore your backup or remove them before you roll back.
- A checkpoint saved with a locked clock has no `pyboy_version` tag and 0.4.x refuses it.
  Only verification tools lock the clock. Ordinary adventures use the host clock.

To roll back, stop the app and start the 0.4.20 image or install. Restore the backup only if you have Gen II adventures.
Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.5.0` to upgrade with Compose, then run
`docker compose pull` followed by `docker compose up -d --wait`. Keep the existing data
mount and project name. Python users can follow the [installation guide](desktop.md).

Gameplay remains an experimental beta. See [release status](../RELEASE_STATUS.md).
