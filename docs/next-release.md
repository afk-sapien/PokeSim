# PokeSim 0.4.18 feature details

Published as [PokeSim 0.4.18](https://github.com/afk-sapien/PokeSim/releases/tag/v0.4.18).

## Adventure Stats

A compact overview uses the same playtime and League totals as Live, with durable
milestone times, 24-hour and 7-day progress, and current Battle Power and DV
highlights. Existing charts and return activities are shown in open
sections with clear headings. Old milestone times remain unknown where evidence is incomplete.
Stat Power history keeps its original meaning. Stats now has its own main tab
with Overview, Pokémon, and Items subpages. Searchable species and item tables
track encounters, defeats, catches, gifts, trades in and out, purchases, consumable
uses, and current holdings. Verified completed cable trade records are backfilled,
using the received species after trade evolution. NPC exchanges count from the
update. Failed and canceled trades are excluded. Verified historical catches carry forward. Other counters begin with
the update, without estimating older activity. Reusable item use is not counted. See [Adventure statistics](adventure-statistics.md).

Item labels include TM/HM move names. An optional PokéAPI item artwork pack adds
icons beside all 125 entries, including discs colored by the move's type. The
pack downloads to local data storage and works offline. It can be enabled or
hidden in Library Settings independently of Pokémon portraits.

## Battle Power and move development

The PC now defaults to Battle Power, which rates known moves using the actual
attacking stats and a consistent set of type matchups. Stat Power and Potential
Stat Power remain separate, with existing collection history and retention rules
preserved. The same moveset evaluator improves level-up move choices.

Stone evolution waits for useful upcoming moves the evolved species cannot learn
by leveling. Owned Surf and Strength HMs can fill empty party move slots for a
clear battle improvement. A Champion-only custom TM counter in Celadon makes all
38 limited TMs renewable for managed adventures. The AI buys one useful upgrade
for a compatible party member, keeps a supply reserve, and teaches it through
normal menus. TM allocation compares absolute level-100 Battle Power gains
using each partner's real DVs and full training, with a level-50 minimum and
material gains required now and at maturity. Each use triggers fresh evaluation.
Limited TMs are protected from selling. Purchases and their item
statistics share recoverable checkpoint ownership. An isolated replay
of a Red backup verified that a Tackle-only Starmie learned Surf through the cartridge
menus, retained its identity and stats, and returned to the overworld. See
[Pokémon stats](pokemon-stats.md) for the scoring assumptions and limits.

The Champion counter also replenishes Moon Stones, PP Ups, Elixirs, and Max
Elixirs. Separate capped million-step offers sell one Master Ball and five Rare
Candies, with progress on Stats → Items. Purchases and offer redemption share
the existing recoverable checkpoint transaction. PP Ups use native move menus.

## Mobile controls

Direction, A, and B buttons repeat while held. Start and Select fire once per press. Pointer capture keeps release handling active if a finger moves off the button. Losing focus, hiding the page, a cancelled pointer, or a failed request stops repetition. Each server request remains a bounded action, so losing the browser cannot leave a game button held indefinitely.

## Shiny collection

Red and Blue have no native shiny appearance. PokeSim marks individuals whose DVs match the Generation II shiny rule: Defense, Speed, and Special are 10, and Attack is 2, 3, 6, 7, 10, 11, 14, or 15. The UI uses a distinct ★ Shiny badge alongside the separate DV rating. It keeps the original game sprites and supports the existing optional portrait packs.

Party cards, partner details, PC cards, and Pokédex records display the badge. PC and Pokédex filters find shiny partners or species. The Pokédex uses compact perfect and shiny species coverage counters out of 151, with final-evolution credit for earlier forms. Individual catch, perfect-find, and shiny totals appear in Stats. Existing saves reveal their current shiny partners immediately. Historic sightings cannot be reconstructed. Trades and existing partners do not manufacture new capture receipts. Replaying the same verified encounter or capture does not increment its receipt twice.

The strategic policy prioritizes shiny captures, including already registered species and encounters outside its current target. It avoids damaging attacks against them, may use a Master Ball, and pauses if storage is full or ordinary battles have no usable balls. Manual control is still available. A capture is not guaranteed, since the original game still controls battle effects and escape behavior. Collected shinies are excluded from duplicate releases, NPC trade candidates, automatic trades, and explicit offers.

Wild encounter tracking runs only for the verified English Red and Blue cartridges and checks the expected instruction sequence. The rule is documented by [pret/pokecrystal](https://github.com/pret/pokecrystal/blob/master/engine/gfx/color.asm).

## Adventure deletion

Adventure cards keep Start or Stop, Download, Archive, and Delete in a compact grid, with a Settings icon beside Open or View adventure. Stop saves progress before shutting down. Archive and Delete save and stop a running adventure automatically. Delete still requires its exact name. Keep the page open while an action waits for shutdown or an active trade. A failed shutdown prevents removal. This removes the adventure directory and its registry entry. Shared ROMs, other adventures, and independent backup archives remain. A pending trade or live worker blocks deletion. A durable deletion record and temporary rename allow interrupted removal to resume without restarting a partially removed adventure. The retry action is available in the archived library if cleanup fails.

## Audio investigation

PyBoy 2.7.0 distinguishes disabling sound hardware from disabling PCM sampling. Previously, no listeners meant a replacement emulator with sound hardware disabled. That mode ignores sound-register writes. Restoring that checkpoint when a listener returns can revive stale channels. The new implementation keeps hardware emulation enabled, samples PCM only for listeners, and never replaces the emulator just because a listener connects or disconnects. Cable workers also preserve sound hardware state.

Regression checks cover ignored writes in the old mode, preserved writes in the new mode, queued input, unchanged game and save RAM, and conversion of supported legacy muted checkpoints. Old files remain untouched. This fixes a demonstrated cause of stale audio. The full Blue/Docker report still needs confirmation on the reporter's environment, and existing stale notes can persist until the game writes new music.

Keeping sound hardware active adds some CPU work while muted. A local cartridge check of 3,600 unrendered frames took 0.10 seconds with hardware disabled and 0.15 seconds with it enabled. This is a small emulator-only sample, not a full application benchmark.

## Palettes

Adventure Settings offers the background colors of the 12 GBC startup choices as whole-screen palettes. Palette changes apply live, including while paused, and persist per adventure. Display recoloring updates the live view and new screenshots without restarting the emulator. Existing journal screenshots keep their captured colors. The default remains the existing grayscale. Checkpoint hardware mode and game RAM stay unchanged.

Authentic GBC coloring uses separate background and sprite palettes. That is deferred because the current renderer's public DMG API exposes one whole-screen palette, and existing DMG checkpoints cannot simply be loaded as CGB checkpoints. The labels describe this implementation as GBC-inspired. Color data is cross-checked against [SameBoy's startup palette table](https://github.com/LIJI32/SameBoy/blob/master/BootROMs/cgb_boot.asm).

Manual trade initiation, accounts and OIDC, other generations, Yellow, and ROM hacks remained deferred in 0.4.18. Generation II and Yellow arrive in 0.5.0, see the [0.5.0 release notes](release-notes.md).

## Live audio buffering

Issue 38 reported stuttering and drifting live sound. The Rust backend publishes one 1,600 byte packet per frame at a steady 60 Hz (16.7 ms apart, 28 ms at worst), so the gaps came from the client. The old page kept about 40 ms of audio ahead, set the playback rate from the measured frames per second, and abandoned the session after one 3 second request. Any delay above 40 ms became silence, truncated responses lost media, and the rate took dozens of distinct values at 1x.

The page now schedules through `pokesim/web/static/audio-buffer.js`, a pure module with Node tests. It waits until the target lead is buffered before starting. The target is 0.4 seconds for watching and 0.1 seconds for Take Control. After an underrun it grows by the gap plus 50 ms up to 1.5 seconds (0.3 seconds in manual mode) and gives 50 ms back for every 10 calm seconds. A smoothed trim of at most 2% holds the lead, and a larger excess is skipped forward with a 6 ms fade instead of clearing the queue. The server ring holds 2 seconds and serves every frame after the `after` cursor. Responses report `X-Audio-Dropped` when the cursor fell behind the ring and `X-Audio-Mode` for the control mode. Playback rates snap to 0.25, 0.5, 0.75, 1, 1.5, 2, 3 and 4 inside a 2% band and sound is muted above 4.5x, where the server also stops sending PCM.

HTTP polling stayed. It works through the manager proxy and needs no fallback logic, and the measured gaps come from delay, not from request overhead. Failed polls are retried for 6 seconds before the page reports a disconnect.

Run `uv run python tools/audio_jitter_harness.py --rom <rom> --game-data <dir>` to measure silence in Chromium through a delaying proxy. In a 30 second run with 30 to 150 ms of jitter and occasional stalls, silence fell from 2.2 s (21 gaps) to 0 s and dropped media from 2.4 s to 0.1 s. A harsh profile with multi second stalls fell from 9.8 s to 7.3 s and now reports an unstable connection. Manual mode under the same jitter still had 3.2 s of silence, the cost of its small buffer, and also reports the problem. Steady playback has no gaps and the mean lead is 0.4 seconds. Listening on real devices was not tested.
