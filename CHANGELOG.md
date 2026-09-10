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
