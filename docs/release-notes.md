# PokeSim 0.4.19 experimental beta

This patch fixes two gameplay issues found during review of 0.4.18.

- Keep shiny encounter protection after Transform by reading the wild Pokémon's
  original DVs. A shiny Ditto stays protected after transforming, while an ordinary
  Ditto copying shiny DVs does not become a shiny encounter. Successful captures
  exit normally even when they consume the last ball or fill the last storage slot.
- Free bag space for story items when all 20 slots are occupied. Sell ordinary
  surplus first, then sell the limited TM stack with the lowest Champion replacement
  cost only if no ordinary surplus remains. Keep key items, HMs, balls, and medicine.
  Champion TM and supply purchases now leave one bag slot free.

## Upgrading and validation

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.4.19`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). Core remains pinned at 0.1.4.

The local non-browser suite passed 1,789 tests with 34 skips, including private-ROM
checks. A copied-save replay also verified the full-bag recovery through actual
cartridge shop menus. Regression tests cover original DVs after Transform,
capture completion, emergency selling, and reserved purchase space.

Existing saves remain supported. Gameplay remains an experimental beta.
The fixes do not establish uninterrupted multi-day gameplay or resolve the
reporter-specific Blue/Docker audio issue. See [release status](../RELEASE_STATUS.md)
for remaining limitations and [0.4.18 feature details](next-release.md) for the
larger feature update included in this version.
