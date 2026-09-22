# PokeSim 0.3.0 experimental beta

This release is about an adventure spending its time well, and about the page you watch it on
saying more while doing less work.

## It stops grinding one Pokémon forever

A training project aimed straight at level 100, and training was the only kind of work exempt from
the planner's recency decay — so once it started, it kept winning the draw. One partner could hold
an adventure for hundreds of game hours while trades and unregistered species waited their turn.

Training now aims at the next multiple of ten. Finishing a step ends the project and hands the turn
back, then picks it up again later. It still leads when there is nothing new to register, by 247
draws to 173 in the settled case, rather than by never stopping.

Trades that trigger an evolution are also worth taking now even when the evolved species is already
registered. A Kadabra that would come back an Alakazam scored nothing once Alakazam was in the
book, despite the cable being the only way it can happen.

## The Cable Club leaves a record

A completed trade used to read "Both cartridges completed their exchange and saved the result",
every time, with a placeholder where a screenshot would be. It now names both Pokémon and the
trainer on the other end, and the journal card shows the two of them either side of a swap arrow.

Events gained a `detail` column for this, added by the migration the store already performs when it
opens. Trades staged by an older build have no arriving side recorded and keep the previous
wording.

## Max speed is about four times faster

The emulator encoded a JPEG of the game every four frames whether or not a browser was open. At Max
speed that is roughly 1,100 encodes a second for a stream that shows fifteen. Frames are now
encoded only while something is asking for them, and no faster than the stream can show them, which
takes Max from about 74x to about 314x real time. Screen tiles and event flags also decode from
lookup tables, worth about 14% of a headless run on its own.

## The interface says more

- **The live page.** The plan moved to a full-width row along the foot — what it is doing, how that
  is going, what comes next — which hands the upper half to the game and the team. The screen grew
  from 400 to 560 pixels and the team column runs the full height beside it, six slots, each card
  carrying its moves, remaining PP and DV rating without a click. The plan also stops flickering:
  the planner reports its gap between projects as an objective of its own, so the row used to cycle
  between the real goal and "Plan the next adventure project" several times a minute.
- **The top bar.** The adventure bar carried eight items in one row using three different looks for
  navigation, and the link that left the adventure was bolder than the page you were on. One
  breadcrumb answers where you are, tabs share a single active treatment with the library, and the
  edition badge that three other places already stated is gone.
- **The Pokédex.** Seven tallies become five: registered, seen, caught, level 100 and perfect
  finds. Level 100 was labelled and badged with a star, which put a milestone in the same visual
  language as the DV ratings beside it; it reads as a flag now. Three-star DVs are still recorded,
  still badged on an entry and still filterable.
- **A mark of its own.** A handheld in the browser tab and the top bar, rather than the `p.`
  lockup.

## Nicknames stop repeating

An adventure remembers every name it has used, so after a hundred Pokémon the draw fell back to the
whole list and quietly began handing out duplicates. Names are now built from prefix and suffix
pairs — 1,616 of them, filtered to the ten characters a cartridge holds. The written names are
unchanged and still come first, so nothing already loved is lost.

## Also in this release

- A stall hunt that continues from a checkpoint honours `--seed` again. A checkpoint carries the
  policy's own random state, so four postgame hunts with four seeds were one hunt repeated four
  times. Scenario replays still make the original choices.
- New Pokédex entries come before the level 100 grind, and a partner with a stone evolution
  available is evolved before being trained.
- Standalone executable bundles are no longer built. Install the Python package with pipx, or run
  the container.

## Upgrading

Existing adventures carry over untouched. The policy state format is unchanged, and the one
database change is additive and applied automatically the next time each adventure starts — an
adventure that is stopped migrates when you start it.
