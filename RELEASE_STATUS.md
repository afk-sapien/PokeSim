Experimental beta validation

Version 0.2.0rc2 is the first public source snapshot and downloadable Linux amd64 beta. It updates distribution metadata, installation instructions, and support links from the privately tested 0.2.0rc1 candidate. Gameplay and checkpoint behavior are unchanged. No prior private Git history is imported.

Completed validation before public publication:

- 190 local tests on the locked Python 3.12 environment, including two tests using a privately supplied ROM.
- Hosted Python 3.11 and 3.12 tests, package resource checks, and container builds for the earlier candidate.
- Offline non-root execution with a read-only root filesystem and ROM, checkpoint restart, corrupt-save fallback, cold backup restore, and server-enforced viewer mode.
- Authenticated HTTPS protecting the dashboard, API, controls, feed, screenshots, and stream, with no direct backend host port.
- A ten-minute authenticated stream, graceful shutdown in about six seconds, save resume, and stream reconnection.
- Upgrade from 0.1.0 to 0.2.0rc1 and rollback using the matching cold backup.

The [public CI run](https://github.com/afk-sapien/pokesim-public/actions/runs/34522953662) passed Python 3.11 and 3.12 tests, package checks, and the container build. The [release workflow](https://github.com/afk-sapien/pokesim-public/actions/runs/34523267945) also passed and published v0.2.0rc2.

A fresh installation cloned the public tag with Git credentials disabled and downloaded the image archive without authentication. Its SHA-256 and image ID matched the release manifest. Local data preparation, healthy gameplay, frame and feed endpoints, UID 10001, read-only root and ROM mounts, graceful shutdown, and checkpoint resume after restart all passed. This used a separate data directory and a privately supplied read-only ROM. The sanitized [installation report](docs/validation/public-install-0.2.0rc2.json) records the exact artifact.

Private vulnerability reporting is enabled. The original development repository remains private, and this public repository has no imported private history.

Still in progress:

- A 48-hour soak on the immutable 0.2.0rc1 image started September 10, 2026 at 18:38 UTC and is due September 12 at 18:38 UTC. It measures health, CPU, memory, disk usage, and streaming with zero, one, and four viewers.
- A separate uninterrupted fresh-game campaign is running on that same candidate. Completion has not yet been established. Earlier Champion evidence came from a copied-save debugging campaign with code fixes and restarts.
- Independent installation reports and broader hardware testing are welcome.

Known limits:

- Gameplay is experimental. The policy can get stuck or make poor choices. Completion across every seed, party, or collection route is not guaranteed.
- Linux amd64 and a clean Pokémon Red (USA, Europe) ROM are the current release targets. Blue, ARM, other games, and ROM hacks are not validated release targets.
- Resource measurements are incomplete. The project does not yet publish minimum hardware requirements or long-term storage estimates.
- The application has no built-in authentication. Use the documented proxy or a private network for remote access.
- A running reliability test is not a completed pass. This beta is intended for early feedback, not a claim of production readiness.
