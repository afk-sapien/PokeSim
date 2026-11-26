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
| Collection browsing, sorting, and Keep settings | [PC storage](pc-storage.md) |
| Trading screen, trade builder, and broker connections | [Trading](trading.md) |
| Standalone Red and Blue pair coordinator | [Automatic trading](automatic-trading.md) |
| Backups, upgrades, recovery, and storage | [Operations](operations.md) |
| Remote access | [Self-hosting](self-hosting.md#configure-ports-and-remote-access) |
| Logins, identity providers, proxies, and view links | [Authentication](authentication.md) |
| Admins, members, invites, and sharing adventures | [Users and sharing](users-and-sharing.md) |

## Develop and maintain

| Topic | Guide |
| --- | --- |
| Setup, checks, and repository layout | [Contributing](../CONTRIBUTING.md) |
| Check, release, replay, and watch commands | [Tools](../tools/README.md) |
| Browser, lifecycle, and copied-save checks | [Validation guide](testing.md) |
| Shared decoding, package ownership, and coordinated updates | [Shared game core](shared-core.md) |
| What runs, in what order, how often and where | [Runtime map](architecture.md) |
| Source changes by version | [Changelog](../CHANGELOG.md) |
| Recorded deployments and known limits | [Release status](../RELEASE_STATUS.md) |
| Monitoring procedure | [Monitoring runbook](operations-monitor.md) |
| Sanitized test and deployment evidence | [Validation records](validation/README.md) |
| Distribution and dependency licensing | [Licensing](licensing.md) |

## Designs

Each design's status line says what is built. Its "Today" describes main when it was written.

- [Multi-user PokeSim](design/multi-user.md): built, merged with accounts off. Accounts, roles, sharing, a control lease and trade offers between people.
- [Goal system v2](design/goal-system.md): built through PR 7. A goal tree with hunt templates, typed progress events, one worth oracle and shared supervision. PR 8, PR 8a and PR 9, the report button, are not built.
- [Replayable bugs](design/replayable-bugs.md): built. Frame clocks, seeded randomness, an action trace with a replay verifier, a bisect tool and automatic stall capture.
- [Adventure state store](design/adventure-state-store.md): built. One owner of each adventure's database, a schema version and atomic restart resets.
- [pokecore state layer](design/pokecore-state-layer.md): built. One typed state layer in pokecore for both generations, Gen I boxes and names in pokecore, and a guard against raw RAM reads.
- [Decide pipeline](design/decide-pipeline.md): built. One decision pipeline in both generations, where every source offers to the arbiter and an outside director is one more source.
- [Typed goals](design/typed-goals.md): built. One record per goal in both generations, the goal catalogue and the manager's pin.
- [One bot, two adapters](design/one-bot.md): built. One policy protocol and one runtime loop for both generations, with a game adapter that only headless runs use today.
- [Goal queue](design/goal-queue.md): proposed, not built. An ordered, saved list of goals that a manager can add to and reorder.
- [Nuzlocke mode](design/nuzlocke.md): proposed, not built. A per-adventure challenge mode where a Pokémon that faints is dead for good.
- [When to rethink the goal](design/when-to-rethink.md): proposed, not built. Whether to pick the goal again only on named events instead of at every decision, measured on saves thousands of game hours past the Champion. It recommends keeping today's model and asking each whole-PC question once per PC change, starting with the Gen II egg scan.
- [Gen II rung builds](design/gen2-rung-builds.md): proposed, not built. How the Gen II activities stop paying for a deep copy and roll back at every ask, measured on deep Gold and Crystal saves. It recommends a shallow draft with builds that replace values instead of editing them, then Facts on the costly helpers, and keeps asking every rung for now.
- [Gate paired seeds](design/gate-paired-seeds.md): proposed, not built. Judge a ladder gate rung that fails on waste on 23 paired seeds against its merge base, about 2 minutes a rung, and charge restock time with its own share.

## Historical records

- [Planner systems](history/planner-systems.md): the shared planner systems S1 to S5 that replaced special-case fixes, as proposed and as built, with the parked mastery credit step.
- [Roadmap as reviewed against 0.5.0](history/roadmap-0.5.md) and [PokeSim 0.4.18 feature details](history/next-release.md).
- [Multi-adventure application plan](history/multi-adventure-app-plan.md) and
  [implementation report](history/multi-adventure-implementation.md): historical design and qualification records.
- [Earlier multi-game design](history/multi-game.md): historical design context.
- [Distribution readiness](distribution-readiness.md): historical release-process review.
- [Link-cable research](link-spike.md): experimental implementation evidence.
- [First-trade review history](trade-review.md): earlier proposals and rehearsal evidence.
- [Archived status, roadmap, and operations logs](history/README.md): preserved records
  whose version and authorization statements describe their original context.

## Keep documentation current

Put each kind of update in its owning document. User-visible changes belong in the
pull request description, and the release pull request gathers them into the changelog.
Plans for future work belong in a design under `design/`. Keep routine validation output outside
Git, and retain selected evidence under the [validation policy](validation/README.md).
Summarize the latest recorded deployment in `RELEASE_STATUS.md`. Link supporting records
instead of repeating release narratives across guides.

Distinguish working source, published artifacts, and deployed revisions. When a build
workflow publishes `release-notes.md`, review that file against the exact tag being
released. A configured build target is not evidence of a successful native runtime check.
