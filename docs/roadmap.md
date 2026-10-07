# Roadmap

Outstanding work reviewed against the published 0.4.20 baseline and the 0.5.0 draft. Delivered
features belong in the [changelog](../CHANGELOG.md), and current limitations
are summarized in [release status](../RELEASE_STATUS.md).

## Gameplay reliability

- Investigate the original stored DV-byte mutation described in the
  [withdrawal recovery report](validation/withdrawal-hp-recovery-20261003.md).
  The excess-HP healing recovery fixes the reproduced rewind loop, but the
  originating mutation has not been reproduced or explained.
- Extend unattended gameplay coverage across Red and Blue, repeated League
  rematches with rotating teams, collection, and automatic cable exchanges.
  Record actual achievements, failed projects, reloads, and process continuity.
  Short copied-save replays do not establish multi-day reliability.
- Turn new reproducible stalls into private copied-save scenarios and focused
  regression tests. Improve travel and preparation without extending objectives
  solely because the player is moving. See the [validation guide](testing.md).

## Trading and recovery

- Design recovery for a permanently stuck committed exchange without losing a
  participant's Pokémon. An arbitrary retry ceiling cannot safely abandon a
  transaction already committed on one side.
- Reduce cancellation delays during staging while preserving commit ordering.
  Staging currently holds the coordinator guard across both participant calls.
- Improve candidate matching for larger libraries. The current candidate search
  is quadratic and repeats each scheduling cycle.

## Maintenance and architecture

- Measure storage and resource growth during longer runs, including journal
  images, backups, retained rewind states, and interrupted upgrades. Preserve
  recovery evidence and verify restores before changing retention.
- Continue extracting battle and field-move state ownership when those features
  change. Follow the [architecture guide](architecture.md) and keep decisions
  separate from emulator I/O, persistence, and HTTP presentation.

## Earlier plans

The [previous roadmap](https://github.com/afk-sapien/PokeSim/blob/5ea6630aab466cbf1f02abde4e3912ee3e90f0b6/docs/roadmap.md)
and [historical records](history/README.md) preserve older proposals and delivery
notes. Their branch names, deployments, and pending work describe their original
context and do not define the current backlog.
