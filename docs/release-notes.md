# PokeSim 0.7.1 release

This release fixes runs that kept busy without getting anywhere. Gold, Silver and Crystal stop
catching Pokémon only to release them, legendary trips go straight to the legendary, and a stuck
game no longer holds up automatic trades for everyone else.

- **Fewer catch and release loops in Gold, Silver and Crystal.** A run with full boxes could
  catch a Pokémon for a linked adventure, release another kept copy to make room, and then hunt
  that one next. A postgame Crystal run caught 196 and released 193 in about seven hours. A PC
  visit now releases only spares and the copies you asked it to release, a hunt for another
  adventure starts only when there is room for the catch, and a full party makes room by
  releasing a spare first. A hunt also skips a target the battle would only run from.
- **Shiny spares are kept longer.** A duplicate shiny now stays until every plain spare is gone,
  including spares that hold items.
- **Legendary trips go straight to the legendary.** In Gold, Silver and Crystal a trip to Lugia,
  Ho-Oh or Suicune runs from other wild battles and leaves better copies of owned species for
  later. In Red, Blue and Yellow a legendary trip sets out once the bag holds 10 Ultra Balls,
  instead of walking back to a Mart for the 20th.
- **Less standing around.** A Gold, Silver or Crystal run no longer waits by the phone for a
  trainer's call while other work is open. The call rings during that work and the run picks up
  the stone afterwards.
- **Battles that never ended.** A Gold, Silver or Crystal catch no longer picks a move the wild
  Pokémon has disabled, which used to repeat "Disabled!" forever. A trade walk now closes a start
  menu left open, where before it pressed A on the menu until the trade timed out.
- **Automatic trades skip a stuck game.** A game shown as stalled, or one whose trades keep
  timing out, is left out of automatic trades and no longer asks the others to collect for it,
  until it makes progress. A Red, Blue or Yellow hunt for a copy another adventure needs now
  ends when its time runs out, instead of moving from place to place forever.
- **Randomized Red and Blue.** With random starters, the rival battle on Route 22 no longer
  freezes. The rival uses the party that matches the rival's starter.
- **Slow startup.** An adventure that was not ready in time when the app started gets one more
  try instead of staying stopped until someone starts it by hand.
- **Old view links end when you say.** With accounts turned on, **Make a link** for an
  adventure's old view link now uses the days field, as **Make watch link** does. Before, the
  new link never expired, whatever the days field said.

For contributors, a stuck-scenario replay now fails when its goal changes more than 120 times
in 60 game minutes, and scenarios can name returned legendaries, returned events and another
adventure's demand. A browser checklist for the multi-user release pass is in
`docs/qa/multi-user-ui-checklist.md`.

See the [changelog](../CHANGELOG.md#071) for every change.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.7.1`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). pokecore moves to 0.12.1. PyBoy RS stays at 0.1.5.

0.7.1 does not change the Library database or the save format, so adventures continue from
their saves.
