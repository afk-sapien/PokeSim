# Roadmap

Updated September 15, 2026.

The goal is an autonomous Red or Blue adventure with useful collection, training,
and trading projects after the Champion. The [release status](../RELEASE_STATUS.md)
describes demonstrated behavior and validation limits.

## Current baseline

The source includes a persistent postgame director, seeded starter and gift choices,
reserve training, legendary recovery, ground-item collection, automatic exchanges,
Championship rewards, searchable PC views, partner locks, and a desktop launcher.
Some of these changes are newer than the recorded deployments.

## Priorities

1. **Sustained progression.** Reduce route failures and supply or PC detours that
   interrupt useful projects. Compare copied checkpoints using actual catches, trainee
   gains, completed milestones, and recovery counts. Preserve productive training while
   keeping inactivity and total project budgets bounded.
2. **Reliable storage and exchanges.** Reproduce full-bag and full-box failures, verify
   safe handling of retired story items, and retain trade and reward recovery guarantees.
   Validate offers and locks through transfers, restores, and interrupted exchanges.
3. **Long runs and releases.** Measure 24-hour, 48-hour, and week-long intervals without
   confusing HTTP health with game progress. Track resource growth and test backup,
   restore, upgrade, shutdown, and peer outages. Qualify each desktop build target.
   Follow the [distribution review](distribution-readiness.md) for public branch
   alignment, registry images, simpler server storage, and desktop signing.
4. **Clearer module ownership.** The rc31 release extracts shop and PC controllers and shares lifecycle ownership.
   Apply the same explicit boundaries to battle and field-move interactions as needed.
   Keep transition tests as the compatibility contract. See [architecture](architecture.md).
5. **One app, multiple adventures.** Follow the separate
   [multi-adventure implementation plan](multi-adventure-app-plan.md), including its
   Cable Club execution and migration gates. This is a proposed architecture, not the
   current desktop or server runtime.

## Later progression work

- Varied Hall of Fame teams and visible stat-training milestones.
- Peer requests that lead to purposeful collection or training projects.
- Optional quality hunting with encounter and storage budgets.
- Low-activity behavior when useful goals are exhausted, without resetting adventures.

Perfect DVs and guaranteed Pokédex completion are not required outcomes. New long-term
features must preserve existing saves and make partial progress distinguishable from
completed goals.

## Evidence and history

Keep delivery details in the [changelog](../CHANGELOG.md) and
[validation records](validation/README.md). The
[earlier roadmap and delivery notes](history/roadmap.md) preserve previous proposals,
held experiments, and release narratives. Historical statements about disabled trading,
reward pools, and live versions do not describe the current source.
