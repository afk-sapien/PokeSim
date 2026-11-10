# Menu shortcuts

`pokecore.shortcuts` drives the game's own menus on Red, Blue, Yellow,
Gold, Silver and Crystal. Each action is a resumable machine:
`machine.step(memory, ui)` returns one button, `None` (wait) or a final `Done`.
It never writes memory. `run(port, machine)` loops it over a `ControllerPort`,
so every input still goes through your `send` and `choose`.
`drive(machine, emulator)` runs it on a Core emulator for scripts and tests.
Class names, `ui` keys and every stop reason are in
[api.md](api.md#menu-shortcuts).

```python
from pokecore import shortcuts

shortcuts.use_item(port, 0x10, 0)                 # Full Restore on party slot 0
shortcuts.use_field_move(port, 'FLY', 1, 'Celadon City')
machine = shortcuts.RunAway()                     # or step it yourself
action = machine.step(memory, {'sp': sp})
```

## Results

Every result has `outcome` and `shortcut` with `kind`, `completed`, `settled`,
`stop_reason` and `can_continue`.

- `completed` means the effect was seen in memory.
- `settled` means the screen reached rest afterwards: the overworld, the menu
  the shortcut started from (pause, mart, PC), or in battle the battle menu,
  the move menu, a forced switch or the end of the battle. Text such as
  "recovered by 60!" is pressed through, never treated as rest.
- `stop_reason` is one of `shortcuts.STOP_REASONS`, such as `completed`,
  `refused`, `budget`, `choice` or `blocked`.
- `can_continue` is true when the screen came to rest, so the next command can
  start without inspecting it.

A shortcut refuses before any input when it can tell the request is invalid,
stops without a second attempt when the game refuses, and is bounded by
`max_steps`.

A caught Pokemon's nickname prompt is answered NO by default. Pass
`nickname='caller'` to `use_item` (or any shortcut) to stop at that prompt
instead. The result is then completed with `pending='nickname'`, and the caller
answers it.

## Catalog

| Shortcut | Games | Done means |
| --- | --- | --- |
| `use_item(port, item, target, move)` | All six | The bag count dropped or the item's effect showed (heal, Berry, status, revive, PP, vitamin, Rare Candy, evolution stone, TM or HM learned, ball thrown, repel, escape item, rod cast, bicycle, Poke Flute). Gen 2 turns to the right pocket first. TMs on a full moveset need `forget_move`. |
| `give_item(port, item, slot, swap=False)` | Gold, Silver, Crystal | The Pokemon holds `item`. Replacing a held item needs `swap=True`. Mail refuses. |
| `take_item(port, slot)` | Gold, Silver, Crystal | The held item is back in the pack. |
| `choose_move(port, slot)` | All six | The turn started with that move selected. With no PP left, or a turn locked by a move such as THRASH, FIGHT runs Struggle or the locked move and `forced` says which. |
| `learn_move(port, forget)` | All six | At a learn-a-new-move prompt, the move in slot `forget` was replaced, or with `'keep'` the new move was given up. HMs and empty slots refuse. |
| `switch_pokemon(port, slot)` | All six | In battle the new Pokemon is out, also from the "change Pokemon?" prompt. Outside battle it is the party lead. |
| `run_away(port)` | All six | The wild battle ended, or the game said you can't escape. Trainer battles refuse. |
| `reorder_party(port, first, second)` | All six | The two party slots swapped, outside battle. |
| `use_field_move(port, move, slot, destination)` | All six | CUT cut the tree, SURF started surfing, STRENGTH is active, FLASH lit the area, FLY landed in `destination`. Gen 2 adds WHIRLPOOL, WATERFALL, ROCK SMASH and HEADBUTT. Badges and known moves are checked first. |
| `toss_item(port, item, quantity)` | All six | The bag lost `quantity`. Key items refuse. |
| `buy_item(port, item, quantity)` | All six | The bag gained `quantity`. Starts at the mart's BUY/SELL menu. |
| `sell_item(port, item, quantity)` | All six | The bag lost `quantity`. Starts at the mart's BUY/SELL menu. |
| `deposit_pokemon(port, slot)` | All six | The party shrank and the current box grew by one. Starts at the PC menu. |
| `withdraw_pokemon(port, position)` | All six | The box shrank and the party grew by one. |
| `release_pokemon(port, position, allow_release=True)` | All six | The box shrank by one. Off unless `allow_release=True`. |
| `deposit_item(port, item, quantity)` | All six | The bag lost `quantity` into the item PC. |
| `withdraw_item(port, item, quantity)` | All six | The bag gained `quantity` from the item PC. |
| `change_box(port, box)` | All six | `box` is the current box. The game saves as part of the change. Starts at the PC menu. |
| `delete_move(port, slot, move_slot)` | Gold, Silver, Crystal | The Move Deleter made the Pokemon forget that move. Starts at the Move Deleter's greeting. |
| `tune_radio(port, station=78, music=0x40)` | Gold, Silver, Crystal | The Pokegear radio is on knob position `station` and `wMapMusic` is `music` (None skips the music check), then the Pokegear is closed. The default is the Poke Flute channel. Starts in the overworld or the start menu and refuses without the radio card. |
| `day_care(port, parent, slot=None)` | Gold, Silver, Crystal | Party `slot` is held in Day Care place `parent` (0 for the Day-Care Man, 1 for the Day-Care Lady), or with `slot=None` that parent is back in the party. Species, trainer ID, DVs and nickname must match, so a look-alike never counts. Starts at that person's greeting. Every YES/NO is answered YES. |
| `show_partner(port, slot, event)` | Gold, Silver, Crystal | Event flag `event` (an index into `wEventFlags`) turned on after party `slot` was shown to a person who asks to see a Pokemon. Starts at the person's greeting. A flag already on refuses. |
| `advance_dialogue(port)` | All six | Text was advanced to a choice (`stop_reason='choice'`, with `screen` and `choices`) or to its end (`'text_end'`). `lines` and `text` hold the conversation. Choices are never answered. |
| `walk(port, direction, tiles=1)` | All six | The player moved `tiles` tiles toward `direction`. It stops early with `blocked`, `battle`, `map_change` or `dialogue` and reports `tiles_moved`, `start`, `end` and `facing`. A ledge hop counts two tiles. On a bicycle a tap can move further than one tile. |

Read-only queries: `list_items`, `list_party`, `list_moves`, `list_box` and
`current_screen`. Slots, positions and move indexes are zero based. Items are
IDs or cartridge names. Gen 2 `list_items` names every item from the cartridge
and gives its pocket.

On Gold, Silver and Crystal the screen comes from the tilemap and menu bytes,
so `current_screen` also names the bag, quantity box, item PC, Bill's PC lists,
mart list and the battle switch prompt. `run` resolves menu choices into single
buttons there and only calls `port.send`, never `port.choose`. Mail is not
covered.

`shortcuts.gen2ui` also holds the Gen 2 menu helpers the machines use, for a
consumer that drives its own menus: `menu_label(row)` strips frame bars, cursors,
item numbers and the TM pack image from one row, `choose(rows, label,
exact=False)` returns one button toward a whole-word label in a vertical menu,
and `close_pc(rows, text)` returns the button that leaves a Pokemon Center PC.

## Building a tool list

`shortcuts.describe()` lists every command as JSON-ready data: arguments as a
JSON Schema object, the screens it can start from, whether it needs or rules out
a battle, and the games it runs on. `describe(version='red')` keeps the commands
that game supports. Which commands to offer, and any budgets or scoring, stay in
the consumer.

```python
tools = [{'name': c['name'], 'description': c['summary'], 'input_schema': c['arguments']}
         for c in shortcuts.describe(version='crystal')]
```
