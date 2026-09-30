# PokeSim 0.4.15 experimental beta

Faster adventures, independent simulation speeds, and more long-term goals.
This release also includes the Journal Stats and type-color changes from the
unpublished 0.4.13 and 0.4.14 candidates.

- Choose a speed for each adventure. Run as many as your hardware can support.
  Library cards show actual speed, CPU use, memory use, and recent activity.
- Spend less CPU time rebuilding collection and training data. Evolution training
  now reuses its destinations. Navigation and training caches retain less memory.
- Download a standard `.sav` from the Library to continue in another emulator.
  Click the PokeSim logo to return home. Fullscreen preserves the complete image.
- Follow Journal Entries and Stats for collection power, DVs, catches, steps,
  battles, marathons, and long-term trends. Type badges have consistent colors.
- Revisit legendary encounters after walking milestones. Repeat Eevee, dojo,
  fossil, and supported NPC exchanges unlock after 100,000 new steps by default.
- League wins award random starters. After the initial Champion Mew gift, another
  Mew requires 1,000,000 new steps followed by a new League victory.
- Track marathon times and personal bests. Custom gifts count as catches, and
  automatic trades protect the last copy of each legendary Pokémon.
- Improved Victory Road return routing, restored input handling, and individual
  League victory attribution. Installation docs now lead with Docker and desktop
  package managers.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.4.15`
in Compose, then run `docker compose pull` and `docker compose up -d --wait`.
Keep your existing data mount and project name. Follow the
[desktop installation guide](desktop.md) for a package-based installation.

Existing adventures inherit the old global speed once. Change each game's speed
in its Library settings. New adventures default to 1×. There is no running-game
limit. For a rollback across this settings migration, restore the pre-upgrade
library backup along with the old image.

New walking opportunities start fresh without a historical reward backlog.
Earlier statistics gaps remain unknown. See [walking rewards](step-rewards.md)
and [adventure statistics](adventure-statistics.md) for details.

Core remains at 0.1.2. Docker images target Linux amd64. Native Python installation
supports the documented desktop and ARM64 platforms. Gameplay remains an
experimental beta. Automated tests and short live runs do not establish that
all adventures can run indefinitely without a stall.
