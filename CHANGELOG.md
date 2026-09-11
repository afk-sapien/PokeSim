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
