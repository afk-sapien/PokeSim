# Step reward validation, September 29, 2026

The update replaces the mixed League reward pool with starters. Native Eevee,
fossil, dojo, and four supported NPC trade activities use independent walking
opportunities. Repeat Mew requires walking followed by another League victory.

Validation used isolated PyBoy instances on the home server. Live ROM and save
mounts were read-only, cartridge RAM was in memory, temporary ledgers lived in
`/tmp`, and the test containers had no network. Live games were not manipulated.

The native interaction checks used a 100-step test interval and advanced the
private ledger to its boundary. NPC trade fixtures supplied two expendable
partners in private storage to exercise withdrawal and the real exchange.
The player then travelled normally and used the cartridge's own interactions.

- Eevee: revisited Celadon Mansion and received another Eevee.
- Dojo: repeated the Karate Master battle and collected the selected fighter.
- Fossils: separately collected Helix, Dome, and Old Amber and completed revival
  at Cinnabar. A discovered travel timeout was corrected to recognize decreasing
  route distance and allow sufficient time for the complete expedition.
- NPC trades: verified the supported Mr. Mime, Farfetch'd, Lickitung, and Jynx
  exchanges consume the offered partner and grant another received Pokémon.
  Acquisition bookkeeping uses inventory at the venue, so releasing a spare
  during PC preparation cannot leave a completed exchange marked available.
- Mew: a private real-cartridge delivery added one Mew after a simulated new
  League receipt. Before that receipt delivery was blocked. The new Pokémon
  counted once as a catch, the next walking requirement started, and another
  delivery was blocked. This check did not replay an entire League run.

Unit tests cover exact boundaries, no historical-step backlog, safe unloaded
rooms, missing prerequisites, disabled intervals, full-storage deferral, native
claim reconciliation after restores, fossil guards across changed choices,
Mew ordering, and atomic receipt rollback. The final regression suite passed
1,527 tests, with 94 optional checks skipped.

Seventeen Chromium checks passed across desktop and phone layouts. Screenshots
were visually reviewed for settings and walking progress. Lint, JavaScript,
and documentation checks passed.
