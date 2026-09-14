PokeSim 0.2.0rc12 fixes routine travel out of Seafoam Islands. The navigator now avoids floor holes that trigger falls and currents, using the ladders to reach healing. Remembered fall steps are also rejected.

A copied stalled Blue save restored its entire party's HP and PP at Fuchsia Pokémon Center after 7632 frames. It then picked up Full Restore and resumed gaining experience. Red's replay behavior was unchanged. All 386 tests passed, with one optional checkpoint test skipped.

Blue is deployed on rc12 with a fresh cold backup and verified save compatibility. The live run has already left Seafoam. Red remains on rc10 without a maintenance restart. Both services and all 12 public endpoint checks passed.

This release excludes the held rc11 obstacle experiment. It does not add Articuno's boulder puzzle solver. Collection efficiency and multi-day endurance remain open.

See [release status](../RELEASE_STATUS.md), [the roadmap](roadmap.md), and [deployment details](homeserver.md).
