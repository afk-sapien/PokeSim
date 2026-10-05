# Next release candidate

Target: 0.4.18. This work is not published yet.

## Adventure Stats

A compact overview uses the same playtime and League totals as Live, with durable
milestone times, 24-hour and 7-day progress, and current Battle Power and DV
highlights. Existing charts and return activities are grouped behind expandable
sections. Old milestone times remain unknown where evidence is incomplete.
Stat Power history keeps its original meaning. The detailed item and species
ledgers remain deferred. See [Adventure statistics](adventure-statistics.md).

## Battle Power and move development

The PC now defaults to Battle Power, which rates known moves using the actual
attacking stats and a consistent set of type matchups. Stat Power and Potential
Stat Power remain separate, with existing collection history and retention rules
preserved. The same moveset evaluator improves level-up move choices.

Stone evolution waits for useful upcoming moves the evolved species cannot learn
by leveling. Owned Surf and Strength HMs can fill empty party move slots for a
clear battle improvement. General TM spending remains deferred. An isolated replay
of a Red backup verified that a Tackle-only Starmie learned Surf through the cartridge
menus, retained its identity and stats, and returned to the overworld. See
[Pokémon stats](pokemon-stats.md) for the scoring assumptions and limits.

## Mobile controls

Direction, A, and B buttons repeat while held. Start and Select fire once per press. Pointer capture keeps release handling active if a finger moves off the button. Losing focus, hiding the page, a cancelled pointer, or a failed request stops repetition. Each server request remains a bounded action, so losing the browser cannot leave a game button held indefinitely.

## Shiny collection

Red and Blue have no native shiny appearance. PokeSim marks individuals whose DVs match the Generation II shiny rule: Defense, Speed, and Special are 10, and Attack is 2, 3, 6, 7, 10, 11, 14, or 15. The UI uses a distinct ★ Shiny badge alongside the separate DV rating. It keeps the original game sprites and supports the existing optional portrait packs.

Party cards, partner details, PC cards, and Pokédex records display the badge. PC and Pokédex filters find shiny partners or species. The Pokédex uses compact perfect and shiny species coverage counters out of 151, with final-evolution credit for earlier forms. Individual catch, perfect-find, and shiny totals appear in Journal Stats. Existing saves reveal their current shiny partners immediately. Historic sightings cannot be reconstructed. Trades and existing partners do not manufacture new capture receipts. Replaying the same verified encounter or capture does not increment its receipt twice.

The strategic policy prioritizes shiny captures, including already registered species and encounters outside its current target. It avoids damaging attacks against them, may use a Master Ball, and pauses if storage is full or ordinary battles have no usable balls. Manual control is still available. A capture is not guaranteed, since the original game still controls battle effects and escape behavior. Collected shinies are excluded from duplicate releases, NPC trade candidates, automatic trades, and explicit offers.

Wild encounter tracking runs only for the verified English Red and Blue cartridges and checks the expected instruction sequence. The rule is documented by [pret/pokecrystal](https://github.com/pret/pokecrystal/blob/master/engine/gfx/color.asm).

## Adventure deletion

Adventure cards keep Start or Stop, Download, Archive, and Delete in a compact grid, with a Settings icon beside Open or View adventure. Stop saves progress before shutting down. Archive and Delete save and stop a running adventure automatically. Delete still requires its exact name. Keep the page open while an action waits for shutdown or an active trade. A failed shutdown prevents removal. This removes the adventure directory and its registry entry. Shared ROMs, other adventures, and independent backup archives remain. A pending trade or live worker blocks deletion. A durable deletion record and temporary rename allow interrupted removal to resume without restarting a partially removed adventure. The retry action is available in the archived library if cleanup fails.

## Audio investigation

PyBoy 2.7.0 distinguishes disabling sound hardware from disabling PCM sampling. Previously, no listeners meant a replacement emulator with sound hardware disabled. That mode ignores sound-register writes. Restoring that checkpoint when a listener returns can revive stale channels. The new implementation keeps hardware emulation enabled, samples PCM only for listeners, and never replaces the emulator just because a listener connects or disconnects. Cable workers also preserve sound hardware state.

Regression checks cover ignored writes in the old mode, preserved writes in the new mode, queued input, unchanged game and save RAM, and conversion of supported legacy muted checkpoints. Old files remain untouched. This fixes a demonstrated cause of stale audio. The full Blue/Docker report still needs confirmation on the reporter's environment, and existing stale notes can persist until the game writes new music.

Keeping sound hardware active adds some CPU work while muted. A local cartridge check of 3,600 unrendered frames took 0.10 seconds with hardware disabled and 0.15 seconds with it enabled. This is a small emulator-only sample, not a full application benchmark.

## Palettes

Adventure Settings offers the background colors of the 12 GBC startup choices as whole-screen palettes. Palette changes require a stopped adventure and take effect when it starts again. The default remains the existing grayscale. Checkpoint hardware mode and game RAM stay unchanged.

Authentic GBC coloring uses separate background and sprite palettes. That is deferred because the current renderer's public DMG API exposes one whole-screen palette, and existing DMG checkpoints cannot simply be loaded as CGB checkpoints. The labels describe this implementation as GBC-inspired. Color data is cross-checked against [SameBoy's startup palette table](https://github.com/LIJI32/SameBoy/blob/master/BootROMs/cgb_boot.asm).

Manual trade initiation, accounts and OIDC, other generations, Yellow, and ROM hacks remain deferred.
