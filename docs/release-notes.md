# PokeSim 0.4.18 experimental beta

Track your adventures in more detail, build stronger movesets, and complete shiny
and perfect collections. This release also improves mobile controls, adventure
management, item artwork, audio handling, and live screen colors.

## Collection and statistics

- Give Stats its own tab with Overview, Pokémon, and Items pages. Keep Journal
  focused on the event timeline.
- Add milestone times, 24-hour and 7-day progress, and Battle Power and DV highlights.
- Track encounters, opponents, defeats, catches, gifts, trades in and out, and
  current holdings for each species. Track purchases, consumption, and holdings
  for each item. Recover verified historical catches and completed cable trades.
- Show Pokédex collection coverage out of 151 for Seen, Registered, Level 100,
  Shiny, and Perfect, with earlier-form credit through the recorded evolution line.
- Identify Pokémon whose DVs satisfy the Generation II shiny rule. Add badges and
  filters, prioritize their capture, and protect collected shinies from release
  and automatic trades. Red and Blue do not gain native shiny battle sprites.
- Add move names to TM/HM labels and an optional PokéAPI item artwork pack.
  Icons download to local storage and work offline. Artwork is not bundled.

## Battle development and supplies

- Rate Battle Power using known moves and actual attacking stats. Keep Stat Power
  and potential separate, and remove Elite Four wins from PC cards and details.
- Improve move choices and delay stone evolution for useful upcoming moves.
  Teach owned Surf or Strength into empty move slots when beneficial.
- Allocate TMs greedily by projected level-100 Battle Power gain using each
  Pokémon's actual DVs and full training. Require level 50 and a material
  improvement both now and at maturity, then reassess after each use.
- Make all 38 limited TMs renewable at a custom Champion counter in Celadon.
  Purchases keep a cash reserve and recover safely after interruption.
- Replenish Moon Stones, PP Ups, Elixirs, and Max Elixirs at that counter.
- Offer one Master Ball and a bundle of five Rare Candies at separate million-step
  intervals after becoming Champion. Offers are capped at one unclaimed purchase
  each, with progress shown in Items.

## Controls and presentation

- Repeat held mobile direction, A, and B buttons, with reliable cancellation when
  the finger releases, the page loses focus, or an input request fails.
- Simplify adventure cards with Stop, Download, Archive, and Delete, plus a Settings
  icon beside Open adventure. Archive and Delete save and stop first. Deletion
  requires the exact name and preserves independent backups and other adventures.
- Apply screen palette changes live, including while paused, and remember each
  adventure's choice. New screenshots use the selected colors. Existing journal
  screenshots retain their captured colors.
- Keep sound hardware active while muted and during cable sessions, addressing
  a demonstrated source of stale audio when listening resumes.
- Fix Settings failing to load when saved backups exist.
- Remove stale validation records and unused assets, and refresh maintenance guidance.

## Upgrading and limits

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.4.18`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). Core remains pinned at 0.1.4.

Existing saves remain supported. Unrecorded past actions and unknown milestone
times are not estimated. New statistics show their tracking start date. Reusable
items and HMs are not counted as consumption. Million-step offers start when the
updated simulation first observes Champion status, without retroactive stockpiling.

Battle Power is an approximate benchmark, and TM allocation considers the current
party and species. Separate GBC sprite/background coloring remains deferred.
The reporter-specific Blue/Docker audio issue still needs confirmation. Gameplay
remains an experimental beta. See [release status](../RELEASE_STATUS.md) and the
[detailed feature scope](next-release.md) for validation and remaining limitations.
