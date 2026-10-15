# PokeSim 0.5.0 experimental beta

This release changes the emulator under every adventure and adds Yellow, Gold, Silver and Crystal.

- **Rust emulator.** Games now run on PyBoy RS, a Rust port of PyBoy 2.7.0, through
  PokeSim Core 0.7.0 and PyBoy RS 0.1.2. Installation needs no Rust toolchain: PyBoy RS ships as a wheel.
  The Docker image is built from the same wheel.
- **Generation II.** Gold, Silver and Crystal adventures play through Johto, the League,
  Kanto and Red, with breeding, held items, all 251 species, Gen II Cable Club trading and
  the Time Capsule with Red and Blue. They run on the Rust backend only. Fresh Cyndaquil campaigns
  in all three games reached Red and all 16 badges on Core 0.7.0 and PyBoy RS 0.1.2. All three
  Gen II cable pairings and all six Red/Blue Time Capsule pairings passed copied-save checks.
  See the [validation receipt](validation/gen2-rust-beta3.json) for scope and limitations.
- **Pokémon Yellow.** Yellow adventures start with Pikachu, follow Yellow's own story and
  trade with Red and Blue over the Cable Club and with Gold, Silver and Crystal through the
  Time Capsule. A new Yellow game was played to the Champion on the Rust backend, and both
  kinds of trade were completed in the Library.
- **Cartridge clock on game time.** Each Gen II adventure keeps its cartridge clock, which runs at
  the simulation's speed and never goes backward. The Live page shows the in-game day and time. See the
  [Gen II notes](gen2-exploration.md) for what is verified and what is not.
- **Fixes carried over.** The 0.4.20 PP menu fix, a Game Corner prize-menu detection fix, and shiny protection
  after Transform (the wild Pokémon's original DVs are now read by Core).
- **Postgame variety.** Finished Gen II adventures rotate through better-DV hunts, training the best
  copies in ten-level steps, shiny outings and League rematches. Shiny outings check up to 100 wild
  encounters, finish their current battle and give two other activities a turn before another outing.
  An hour of simulated gameplay including travel bounds outings with few encounters.
- **Uncatchable shinies.** A shiny that cannot be caught is logged and fled from when the cartridge
  permits escape. Scripted encounters such as red Gyarados are fought if capture is impossible.
- **First gym preparation.** Gen II teams train a partner to level 12 before challenging Falkner,
  avoiding repeated losses without experience gains.
- **Library cards.** Removed the generic no-progress warning from adventure cards.

## Upgrading is one-way for Gen II

Back up the complete library first, as a copy of the whole data directory, before you
start the new version.

- Red and Blue adventures need no restore. Their checkpoints and manifests still carry the
  `pyboy_version` tag that 0.4.x checks, and the Rust state format is the PyBoy 2.7.0 format.
- Yellow, Gold, Silver and Crystal adventures need 0.5.0 or later, because 0.4.x supports neither
  Yellow nor Gen II.
  Restore your backup or remove them before you roll back.
- A checkpoint saved with a locked clock has no `pyboy_version` tag and 0.4.x refuses it.
  Gold, Silver and Crystal adventures always lock the clock to game time. Red, Blue and Yellow
  adventures use the host clock, so only verification tools lock theirs.

To roll back, stop the app and start the 0.4.20 image or install. Restore the backup only if you have Gen II adventures.
The beta releases provide desktop wheels on GitHub. The Docker quickstart continues to use the
stable release until the final 0.5.0 image is published. Python users can follow the
[installation guide](desktop.md) and the installation command on the selected beta release.

Gameplay remains an experimental beta. See [release status](../RELEASE_STATUS.md).
