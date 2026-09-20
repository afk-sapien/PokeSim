# PokeSim 0.2.1 experimental beta

This release fixes four ways an adventure could stop getting anywhere, and makes every stall
something that can be replayed until it is fixed.

Found by full-speed test adventures and by saves edited into hard situations:

- **A battle nobody can finish.** The original trainer routine favours any move of a super
  effective type, even one that does nothing, so Lorelei's Dewgong only uses Rest against a frozen
  Muk and never knocks it out. With nobody able to act, the player hands over to a partner the foe
  does attack, and when there is none the save from before the battle is reloaded at once instead
  of after the battle timeout.
- **Trading the lead forever.** With two partners tied for the highest level, moving the second
  League battler to the lead changed who was chosen, and a run with eight badges swapped Lapras
  and Muk in Pokémon Mansion's party menu indefinitely.
- **Wandering before Misty.** A side project that led back to Viridian Forest replaced the Mt. Moon
  goal with training on Route 24, which lies beyond the mountain. Misty is now reached about three
  game hours after Brock instead of nine.
- **Wandering before the League.** Route 23 draws its grass with its own tile, so preparing for the
  League there had no destination. One test adventure reached the Hall of Fame in 41 game hours
  instead of 60.

**Stalls are kept.** Rotating autosaves were long gone by the time a stall was reported. Each
adventure now keeps the first autosave after its last achievement, and a reported stall leaves a
folder in `stalls/` with that save, the moment the stall was noticed, a screenshot and a report.
`KEEP_STALL_BUNDLES` sets how many are kept, 5 by default, 0 for none.

**Stuck scenarios.** `tools/stuck_scenarios.py` turns any of those saves into a regression test that
replays in about a minute, and can edit the copy into a situation that is hard to reach by
playing: frozen or sleeping partners, 1 HP, no PP, an emptied bag, no money. See the
[validation guide](testing.md#stuck-scenarios). Seventeen private scenarios and four fresh Red
adventures play through on this code.

Install the Python package with `pokesim-desktop`, or run one Docker container. Prepared
adventures work offline. Supply your own supported ROM. Packages exclude Pokemon ROMs, saves,
generated game datasets, and portrait packs.

After publication, install the container from `ghcr.io/afk-sapien/pokesim:0.2.1`
using the attached `compose.yaml` and `env.example`. Follow the
[container installation guide](https://github.com/afk-sapien/PokeSim/blob/v0.2.1/docs/self-hosting.md#install-a-published-container).
No GitHub login or local image build is needed. To upgrade, set `POKESIM_IMAGE` to the new
version, then `docker compose pull && docker compose up -d`. Adventures and settings are kept.

Downloads for this release are Python packages, a Linux amd64 Docker image archive,
Compose configuration, checksums, and a source manifest. Standalone executable
bundles are outside this release scope. Native package checks use PyBoy's demo
ROM and do not establish full cartridge gameplay reliability on every platform.

Back up existing adventures before upgrading. Publishing does not upgrade existing
installations. See [installation and migration](desktop.md) and [server setup](self-hosting.md).

The automatic player can still get stuck. This remains an experimental beta without
a new uninterrupted multi-day gameplay claim.
