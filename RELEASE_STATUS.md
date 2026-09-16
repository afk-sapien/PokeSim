# Release status

Updated September 15, 2026 from repository evidence. Deployment details below are
recorded observations, not a fresh health check.

## Source and deployment versions

The package version is `0.2.0rc30`. The working source also contains newer desktop,
PC trading, Pokémon lock, and reward changes. A version number alone does not identify
those changes. Record the exact source revision when building or deploying.

| Component | Last recorded version | Evidence |
| --- | --- | --- |
| Red adventure | rc30 | [Deployment receipt](docs/validation/release-0.2.0rc30-red.json) |
| Blue adventure | rc29 | [Deployment receipt](docs/validation/release-0.2.0rc29-blue.json) |
| Trading coordinator | rc24 | [Independent safe-point validation](docs/validation/trade-safe-points-0.2.0rc24.json) |
| Public prebuilt installation documented here | rc6 | [Pinned installation reference](docs/self-hosting.md) |
| Desktop bundles | New workflow targets | [Desktop build and validation guide](docs/desktop.md) |

The rc30 follow-up recorded both games healthy at maximum speed, zero recovery reloads,
144 registrations in each adventure, and 31 completed automatic exchanges.
See the [recorded follow-up](docs/validation/supply-live-0.2.0rc30.json).

## What has been demonstrated

- Runs have reached the Hall of Fame and continued collecting and training.
- Copied-save comparisons cover route recovery, legendary encounters, PC transfers,
  training continuity, and the rc30 optional-shopping correction.
- Trusted Red and Blue peers have completed automatic exchanges with durable holds,
  checkpoint validation, and recovery after interrupted transactions.
- The current source adds browser-based desktop setup, game-local trading views,
  individual offers and locks, and a separate one-time Champion Mew reward.
  These source changes do not establish that existing deployments have received them.

## Remaining limits

- Autonomous campaign completion, all 151 registrations, and uninterrupted multi-day
  progress are not guaranteed. Routing, preparation, and storage can still stall projects.
- Red is the primary supported game. Blue remains experimental.
- Desktop workflow targets need successful native build and runtime results before
  being described as validated downloads. Older public releases omit the launcher.
- Current trading uses coordinated checkpoint edits. Authentic Cable Club execution
  and a single application managing multiple adventures remain planned work.
- Existing deployments may still use the earlier eight-species Championship reward
  pool. The source now separates Mew from the seven-species repeatable pool.

## Where updates belong

Use [CHANGELOG.md](CHANGELOG.md) for user-visible changes,
[the roadmap](docs/roadmap.md) for remaining work, and
[the monitoring runbook](docs/operations-monitor.md) for evidence collection.
Keep this page short and link new validation records rather than copying their contents.

The complete previous status log is preserved in
[release and deployment history](docs/history/release-status.md).
