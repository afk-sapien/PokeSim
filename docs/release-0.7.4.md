# PokeSim 0.7.4 release

A speed release with no gameplay change. Every replay makes the same decisions on the same
frames as in 0.7.3, and adventures play more frames a second. Each gain was measured on its own:

- Red, Blue and Yellow decode each step's memory once, about 23% faster in Red.
- Gold, Silver and Crystal reuse the planner's copy of their state, about 13% faster in Gold,
  and stop rebuilding team keys and wild levels, about 10% faster.
- PyBoy RS 0.1.7 runs the emulator about 17% faster in Red and 10% faster in Gold.
- Max speed with Sound on is faster, since no sound is made above the speed where the page is
  muted.

A busy Library database no longer fails a play pass. The run logs one warning and plays on.

See the [changelog](../CHANGELOG.md#074) for every change.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.7.4`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). pokecore moves to 0.12.3 and PyBoy RS to 0.1.7.

0.7.4 does not change the Library database or the save format, so adventures continue from
their saves.
