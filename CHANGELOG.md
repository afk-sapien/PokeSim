0.2.0rc11 candidate, respect obstacles on remembered routes

- Apply observed solid-object positions to remembered steps on the current map. Preserve distant learned routes until fresh object positions are available.
- Stop walking through a remembered Victory Road route when a boulder has returned to the path.
- Allow the route again when the object moves away or is confirmed hidden.

0.2.0rc10, verify training after PC transfers

- Accept training progress in battle or after returning to the overworld, avoiding temporary level values during PC withdrawals.
- Keep transfers and missing party entries from resetting the training idle timer.
- Preserve project state across reloads and count subsequent experience and level gains normally.

0.2.0rc9, recover routes after Victory Road switches reset

- Ignore remembered steps through currently closed puzzle gates.
- Reach the upper puzzle by ladder when reentry leaves the lower boulder inaccessible.
- Preserve existing saves, parties, and ongoing postgame projects.

0.2.0rc8, persistent postgame projects and varied starters

- Collect nearby reachable ground items during ordinary travel and collection expeditions, including caves. Verify collection, respect bag capacity, and preserve the original project during bounded detours.
- Choose a seeded random starter for new adventures, with a persisted choice and a fixed `STARTER` setting.
- Rotate postgame collection, evolution, training, and exploration projects using persistent recent choices and outcomes.
- Train party and stored partners toward level milestones, with progress measured for the selected partner.
- Increase retry delays for repeated failures and bound the retained planning history.
- Keep old checkpoint compatibility and retain existing Pokémon when configuration changes.

- Register the received Pokémon and any trade evolution in the recipient's Pokédex when staging a save-based exchange. Verified on copied Red and Blue saves. Live trading remains disabled.

0.2.0rc7, continuing adventures and visible progress

- Restore planner timing safely and replan stationary objectives without rewinding the game.
- Clear the loose east-corridor boulder when returning through Victory Road.
- Check every expedition's route and retire unproductive objectives with a retry cooldown.
- Show Live activity and the last achievement with its age.
- Keep playtime announcement history across checkpoint reloads.
- Package the read-only trade board and save-based trade executor.
- Consolidate the deployed Live, Pokédex, PC, journal, nickname, storage, and persistent clock work into a reproducible release.

- Add a `/pokedex` page: all 151 entries with types, base stats, learnsets, evolution families, and Kanto locations, filtered by search, type, record, and availability.
- Show the traveling party and every storage box, with each resident linked to its Pokédex entry.
- Serve entry data from `/api/pokedex` and live records from `/api/pokedex/status`, and link out to Bulbapedia, Serebii, and Wikipedia.
- Add sixteen tests covering the reference data, the live status shape, and the new endpoints.
- Stop planning Pokédex projects that need the PC when storage cannot serve them: with a full party and every box full, the run no longer walks to a PC and cycles its menu.
- Release spare stored duplicates to keep about five storage slots free, so an unattended run never runs out of room. One copy of every species always survives, the lowest-level duplicate goes first, and a current evolution project's partner is never released.
- Answer a release confirmation only while a release is the active goal, and decline it otherwise.
- Record releases in the journal at minimal priority.

0.2.0rc6, unidentified ghost encounters

- Flee wild Pokémon Tower encounters before obtaining the Silph Scope.
- Preserve normal decisions for trainers, identified ghosts, and battles outside the Tower.
- Add ten regression cases and verify escape from a copied stalled checkpoint.

0.2.0rc5, storage withdrawal fix

- Allow an evolution partner to be withdrawn from a full box when the party has space.
- Stop selecting the source box again once it is already active.
- Keep capacity handling for full parties and boxes without the requested partner.
- Add four regression tests and verify the fix against a copied game checkpoint.

0.2.0rc4, reliable game display

- Load and decode one game image at a time, capped at 10 display frames per second independently of game speed.
- Retain the last good image through request failures and invalid frames, with bounded timeouts and automatic recovery.
- Stop hidden-tab frame downloads and remove competing MJPEG reconnect handlers.
- Add browser-controller regression tests for serialization, decode failures, timeouts, and visibility changes.
- Leave emulator behavior, game speed, save formats, and health checks unchanged.

0.2.0rc3, planner reliability fix

- Share one bounded navigation search across collection candidates to prevent repeated route searches from stalling emulation after the League.
- Keep the health threshold unchanged and add regression tests for search reuse, directionality, obstacles, and search limits.
- Preserve failing health details and correct stopped-run statuses in the endurance harness.
- Detect campaign completion from the saved Hall of Fame count after leaving the ceremony.
- Include Docker, Compose, proxy, and validation files in the Python source archive.
- Correct release status claims to disclose the failed earlier endurance run.

0.2.0rc2, experimental public beta

- Start a clean public source history with original code under MIT.
- Publish versioned Docker image archives and source packages with checksums, without requiring registry or GitHub credentials to download.
- Document local game-data preparation, supported platforms, access controls, backup, upgrade, and rollback.
- Provide private vulnerability reporting and explicit beta limitations.
- Preserve the gameplay and checkpoint behavior of the candidate under endurance testing.

The prior engineering candidate established atomic checkpoint recovery, rootless containers, authenticated proxy deployment, dependency notices and emulator source preservation, and local preparation of game content. The first endurance run later stopped on a campaign health failure. See RELEASE_STATUS.md for current results.
