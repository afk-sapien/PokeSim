# Documentation

Start with the [project README](../README.md) for an overview and installation.
This index separates current instructions, future plans, and historical evidence.

## Use PokeSim

| Topic | Guide |
| --- | --- |
| Python desktop setup and save locations | [Desktop](desktop.md) |
| Current server installation | [Server setup](self-hosting.md#first-installation) |
| Prebuilt release image | [Docker and migration](self-hosting.md) |
| Publishing Python and Docker releases | [Release workflow and GHCR setup](publishing.md) |
| Collection milestones, level 100 stars, and perfect finds | [Collection goals](collection-goals.md) |
| Postgame races, checkpoints, and finish reports | [Kanto Marathon](marathon.md) |
| Gameplay, settings, and APIs | [Feature guide](guide.md) |
| Power, stats, DVs, training, and individual victory counts | [Pokémon stats and Power](pokemon-stats.md) |
| Collection browsing, sorting, and Pokémon locks | [PC storage](pc-storage.md) |
| Trading screen, offers, and broker connections | [Trading](trading.md) |
| Automatic library exchanges | [Automatic trading](automatic-trading.md) |
| Backups, upgrades, recovery, and storage | [Operations](operations.md) |
| Authenticated remote access | [HTTPS proxy](proxy.md) |

## Develop and maintain

| Topic | Guide |
| --- | --- |
| Setup, checks, and repository layout | [Contributing](../CONTRIBUTING.md) |
| Browser, lifecycle, and copied-save checks | [Validation guide](testing.md) |
| Shared decoding, package ownership, and coordinated updates | [Shared game core](shared-core.md) |
| Module ownership and refactoring | [Architecture](architecture.md) |
| Source changes by version | [Changelog](../CHANGELOG.md) |
| Recorded deployments and known limits | [Release status](../RELEASE_STATUS.md) |
| Remaining work | [Roadmap](roadmap.md) |
| Monitoring procedure | [Monitoring runbook](operations-monitor.md) |
| Sanitized test and deployment evidence | [Validation records](validation/README.md) |
| Distribution and dependency licensing | [Licensing](licensing.md) |

## Plans and historical records

- [Earlier homelab deployment](homeserver.md): September 2026 two-container layout.
- [Distribution readiness](distribution-readiness.md): historical release-process review.

- [Multi-adventure application plan](multi-adventure-app-plan.md) and
  [implementation report](multi-adventure-implementation.md): historical design and qualification records.
- [Earlier multi-game design](multi-game.md): historical design context.
- [Link-cable research](link-spike.md): experimental implementation evidence.
- [First-trade review history](trade-review.md): earlier proposals and rehearsal evidence.
- [Archived status, roadmap, and operations logs](history/README.md): preserved records
  whose version and authorization statements describe their original context.

## Keep documentation current

Put each kind of update in its owning document. User-visible changes belong in the
changelog and future work in the roadmap. Keep routine validation output outside
Git, and retain selected evidence under the [validation policy](validation/README.md).
Summarize the latest recorded deployment in `RELEASE_STATUS.md`. Link supporting records
instead of repeating release narratives across guides.

Distinguish working source, published artifacts, and deployed revisions. When a build
workflow publishes `release-notes.md`, review that file against the exact tag being
released. A configured build target is not evidence of a successful native runtime check.
