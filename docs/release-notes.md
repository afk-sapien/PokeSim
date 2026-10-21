# PokeSim 0.5.2 patch release

This patch fixes worker memory growth, several stalls found on adventures running 0.5.1,
and adds two optional Red, Blue and Yellow features.

- **Worker memory ([#111](https://github.com/afk-sapien/PokeSim/issues/111)).** Red, Blue and
  Yellow workers grew to about 900 MiB over a day of play. Each autosave rebuilt the learned
  map as hundreds of thousands of small lists, which fragmented memory. The map is now saved
  as flat lists of numbers.
- **Stalls and trade failures.** Gold, Silver and Crystal trainers no longer get stuck in the
  National Park Gate officer's corner, League runs no longer reload at Koga with only a Ditto
  left, and Time Capsule trades no longer stall at the PC when the last Pokémon able to battle
  cannot be deposited. Red, Blue and Yellow trades no longer fail on a PC box behind a
  nickname with a text command. A game whose PC is full now pauses automatic trades until it
  completes one, instead of failing with a different Pokémon each time.
- **Fair wild DVs.** An optional Red, Blue and Yellow setting, off by default, that gives each
  wild encounter fully random DVs.
- **Snorlax returns.** After the Champion battle, the Route 12 Snorlax blocks the road again
  every 100,000 steps in Red, Blue and Yellow.
- **Clearer trade reasons and a readable Live page** between phone and desktop widths.

See the [changelog](../CHANGELOG.md#052) for every change.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.5.2`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). Core moves to 0.7.1, which only allows Pillow 13 for its security fixes. PyBoy RS stays at 0.1.2.
Saves and checkpoints from 0.5.1 load unchanged. Rolling back to 0.5.1 is safe, but a
Red, Blue or Yellow adventure saved by 0.5.2 starts a fresh learned map under 0.5.1.

The local suite passed 4,173 tests with private-ROM checks, including replays of the stuck
National Park Gate, Koga and Time Capsule saves and the old saved map format.

See the [0.5.0 release notes](release-0.5.0.md) for the full 0.5.0 update and its known
limitations, and [release status](../RELEASE_STATUS.md) for remaining limits.
