# Documentation

Start with the [project README](../README.md) for an overview and installation.
This index separates current instructions, future plans, and historical evidence.

## Use PokeSim

| Topic | Guide |
| --- | --- |
| Python desktop setup and save locations | [Desktop](desktop.md) |
| Current server installation | [Server setup](../README.md#in-one-docker-container) |
| Prebuilt release image | [Docker and migration](self-hosting.md) |
| Publishing Python and Docker releases | [Release workflow and GHCR setup](publishing.md) |
| DV ratings, level 100 stars, and perfect finds | [Collection goals](collection-goals.md) |
| Gameplay, settings, and APIs | [Feature guide](guide.md) |
| PC views, offers, and Pokémon locks | [PC and trading](pc-trading.md) |
| Automatic library exchanges | [Automatic trading](automatic-trading.md) |
| Backups, upgrades, recovery, and storage | [Operations](operations.md) |
| Authenticated remote access | [HTTPS proxy](proxy.md) |

## Develop and maintain

| Topic | Guide |
| --- | --- |
| Setup, checks, and repository layout | [Contributing](../CONTRIBUTING.md) |
| Browser, lifecycle, and copied-save checks | [Validation guide](testing.md) |
| Module ownership and refactoring | [Architecture](architecture.md) |
| Source changes by version | [Changelog](../CHANGELOG.md) |
| Recorded deployments and known limits | [Release status](../RELEASE_STATUS.md) |
| Remaining work | [Roadmap](roadmap.md) |
| Historical distribution review | [Distribution readiness](distribution-readiness.md) |
| Monitoring procedure | [Monitoring runbook](operations-monitor.md) |
| Installation-specific deployment layout | [Homelab notes](homeserver.md) |
| Sanitized test and deployment evidence | [Validation records](validation/README.md) |
| Distribution and dependency licensing | [Licensing](licensing.md) |

## Plans and historical records

- [Multi-adventure application plan](multi-adventure-app-plan.md): architecture and acceptance gates for the implemented library.
- [Earlier multi-game design](multi-game.md): historical design context.
- [Link-cable research](link-spike.md): experimental implementation evidence.
- [First-trade review history](trade-review.md): earlier proposals and rehearsal evidence.
- [Archived status, roadmap, and operations logs](history/README.md): preserved records
  whose version and authorization statements describe their original context.

## Keep documentation current

Put each kind of update in its owning document. User-visible changes belong in the
changelog, future work in the roadmap, and deployment evidence in validation records.
Summarize the latest recorded deployment in `RELEASE_STATUS.md`. Link supporting records
instead of repeating release narratives across guides.

Distinguish working source, published artifacts, and deployed revisions. When a build
workflow publishes `release-notes.md`, review that file against the exact tag being
released. A configured build target is not evidence of a successful native runtime check.
