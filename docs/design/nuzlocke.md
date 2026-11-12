# Nuzlocke mode

Status: proposed on 2026-11-11. Every line number was read from main at `44d17450` (#563). It builds on [Typed goals](typed-goals.md), the [Decide pipeline](decide-pipeline.md), [One bot](one-bot.md) and [Replayable bugs](replayable-bugs.md).

A nuzlocke is a challenge run with three rules. A Pokémon that faints is dead for good, only the first wild Pokémon met in each area may be caught, and every catch gets a nickname. This note plans it as a per-adventure mode. The bot still plays to win, but it plays to keep its party alive, and the run's deaths become its story.

## Choices for the owner

Choose before slice 1. The recommendation is in bold.

1. **After a wipe.** **The run ends and is kept as a record, with a Try again button that starts a linked new attempt.** The other path restarts on its own, which suits an unattended library but buries each record under the next.
2. **Cable trades.** **Banned by default, with a setting that allows trades only with another nuzlocke adventure.** The third path allows every trade, which lets a normal adventure feed the run.
3. **The default preset.** **Classic: the three core rules plus the dupes clause, the shiny clause and free gifts.** Hardcore adds level caps, no items in battle and set mode.
4. **After the champion.** **The run is won and stops.** It could instead lift the rules and go on collecting as a normal adventure.
5. **A blackout with living Pokémon in the PC.** **The run ends, as in the classic rules.** It could instead go on with the boxed ones.

Choose before the Gen II slice:

1. **Breeding.** **Off.** A Day Care egg is a Pokémon with no encounter. The eggs the game hands out (Togepi, Crystal's Odd Egg) are gifts either way.
2. **Roaming beasts.** **Free statics that may be chased until caught or knocked out**, since they flee by design.

## What a player can notice

Nothing changes for an adventure without the mode. With it on:

1. The library card shows "Nuzlocke", the death count and whether the run is alive.
2. The bot catches the first Pokémon it meets in each area, whatever goal it is on, and names it. It runs from wild battles in spent areas unless it is training.
3. A death is a notable journal entry with a push: "Sparky the Pikachu died on Route 3 to a wild Spearow (level 9)".
4. A run page shows the living party, the dead box and every area's encounter.
5. A wipe stops the adventure for good. It stays readable as a record, and no reload or rewind brings the party back.

## 1. Rules

The core rules are always on in the mode:

1. **A fainted Pokémon is dead.** It is never sent into battle, trained, traded or withdrawn again, and it goes to the dead box at the next PC. A Center still heals it, but the ledger keeps it dead by its identity (trainer ID, DVs and species, as `mon_identity` builds it).
2. **First encounter per area.** The first wild battle in an area spends that area, whatever comes of it: a catch, a flee, a knockout or a loss. Areas met before the first Poké Ball is in the bag stay open.
3. **Every catch gets a nickname.** The `nicknames` setting is forced on and covers the starter, gifts and trades too (`nicknames.configured_pool`, `pokesim/nicknames.py:149`). Create refuses a run whose name pool is empty.

An area is a place named on the town map, so Mt. Moon's three floors are one area. Fishing, surfing and grass in one area share its one encounter.

The options are per adventure:

| Option | Classic | Hardcore | Rule |
|---|---|---|---|
| Dupes clause | on | on | A first encounter whose evolution family is already caught or dead does not spend the area. The next new family does. |
| Shiny clause | on | on | A shiny may always be caught and spends nothing. Gen II only, since Gen I has no shinies. |
| Gifts and statics | free | free | A gift, fossil, prize or static does not spend its area. Each static is one try, and no walking return brings it back. |
| Level caps | off | on | No party member above the next boss's ace level. |
| No items in battle | off | on | No healing or status items in battle. Gen II held items stay. |
| Set mode | off | on | The game's battle style option is set to Set once, at the start. |

The rules are picked at create time and lock when play starts, since changing them mid-run is the cheat the mode exists to stop. Level caps are off in Classic because training past the next boss is the bot's main way to stay alive (section 3.4).

## 2. Fit with what PokeSim does today

Today the bot plays to collect, breed, trade and train to targets. In the mode it plays to beat the champion with the run alive, and collection is what the rules allow along the way.

| What it does today | In the mode | Where it lives |
|---|---|---|
| Hunt kinds (grass, surf, fish, safari) search a map for a species | One goal per open area, "Take the first encounter on Route 3". A species target is never feasible. | `policies/kinds.py:130-166` |
| Catch or decline by worth | Every first encounter is caught if the bot can. `pcvalue.worth` never declines one, since it is the only chance. | `pcvalue.py:323`, `policies/collection.py:100` |
| Travel flees wild battles | A wild battle in an open area is a catch, whatever goal runs. One in a spent area is fled unless a train goal wants it. | `planning/stance.py` |
| Missing Pokédex entries as the postgame filter | Off. The dex fills with what the run meets. | the director |
| Static encounters | One try each. `LegendaryRecovery` and the walking legendary returns are off. | `kinds.py:222`, `legendary.py:25`, `legendary_returns.py` |
| Gifts, fossils and Porygon | Free, nicknamed, under the dupes clause. The step event re-offers (Eevee, the Dojo, fossils, `trade_N`) are off, so there is one of each. | `kinds.py:264-330`, `step_events.py:78` |
| In-game NPC trades | Allowed. The Pokémon given leaves the run alive, and the one received is free like a gift. | `kinds.py:285`, `gen2/npc_trades.py` |
| Cable trades between adventures, Time Capsule included | Banned by default (choice 2). A trade evolution then has no route and is not feasible. | `app/coordinator.py:700-702`, `:1186-1194`, `app/trade_settings.py:35-37` |
| Gen II breeding and hatching | Off (Gen II choice 1). The breed, hatching and peer store rungs are not feasible. | `gen2/breeding.py`, `gen2/collection.py:948-986` |
| Box and release | The dead box is Keep-locked and never released. The release goal still makes room among the living. | `pcvalue.py:494`, `policies/strategic.py:597-608`, `gen2/release.py` |
| Mew, League rewards and the event and legendary claims | PokeSim's own gifts from outside the game. The claims ledger never earns them in a run. | `mew_returns.py`, `rewards.py:122`, `return_claims.py` |
| Training to targets | Kept and weighed more, since it keeps the party alive. Under level caps a train goal stops at the cap. | `kinds.py:511`, `planning/league.py:128` |
| Evolving | Allowed, stones included. | `kinds.py:478` |

## 3. How it is built

### 3.1 The mode

One adventure setting, `nuzlocke`, holds the preset and the options, for example `{"preset": "classic", "dupes": true, "shiny": true, "gifts_free": true, "level_caps": false, "battle_items": true, "set_mode": false, "trades": "banned"}`. It follows the recipe every setting uses:

1. `validate_adventure_settings` checks it (`app/manager.py:188-244`) and the create form offers it (`web/static/library.js:939-1021`).
2. `SimulationSettings` carries it to the worker as `config.NUZLOCKE` (`runtime/settings.py:40`). It is not a play setting, and PATCH refuses it once the adventure has played a frame.
3. Every save manifest (`runtime/manifest.py:14-43`) and every trace header (`runtime/trace.py:252`) stamps it, so a replay plays by the same rules.
4. The coordinator's trade gates (`app/coordinator.py:700-702`, `:1186-1194`) read it for choice 2.

### 3.2 The ledger

```python
@dataclass(frozen=True)
class Encounter:
    area: str            # town map name, from the adapter
    species: int
    outcome: str         # 'caught', 'fled', 'knocked_out', 'lost', 'dupe', 'shiny', 'lost_to_reload'
    identity: str | None # the catch's mon_identity
    nickname: str | None
    frame: int           # PlayClock frame

@dataclass(frozen=True)
class Death:
    identity: str
    nickname: str
    species: int
    level: int
    area: str
    cause: str           # 'a wild Spearow', "Misty's Starmie"
    frame: int

@dataclass
class Ledger:
    rules: dict
    opened: int | None   # PlayClock frame of the first Poké Ball
    encounters: list[Encounter]
    deaths: list[Death]
    status: str          # 'alive', 'wiped', 'won', 'stuck'
    ledger_id: int       # bumps on every change, the barrier in section 5
```

One observer writes it from snapshots, the way `events.py` writes the journal. A wild battle that starts in an open area adds an encounter. A party member whose HP falls to 0 adds a death. A blackout sets wiped and the champion sets won. It counts PlayClock frames, which never go back (`play_clock.py:21-26`), and it is a pure function of the snapshots, so a replay rebuilds it.

It lives in the store's SURVIVES domain beside the trade barrier (`state/domains.py:108-111`), so neither a reload nor a restart resets it, and it is declared a policy read (`state/domains.py:13`). The headless runner has no store (`runtime/headless.py`), so it keeps the ledger in memory and the gate can play a nuzlocke rung.

Areas come from the adapter's `area(map)`. Gen II has them: each map's landmark (`gen2/data.py:150-157`). Gen I has none today, since nothing reads the town map. The plan reads the town map entries from the cartridge in pokecore's romdata next to the encounter tables (`romdata/gen1.py:81`), which keeps randomizers and hacks right, with pret's `data/maps/town_map_entries.asm` as the test oracle.

### 3.3 Feasibility on typed goals

One check runs before each kind's own `feasible`: `nuzlocke.feasible(view, spec) -> Failure | None`. It decides by the kind's family (catch, gift, trade, breed, claim, train, battle), which answers typed goals open question 1: the catalogue should carry each kind's family. A goal the rules forbid fails with a new `rule` kind beside the others in `planning/decide.py:25-46`, and the catalogue's why_not shows the reason:

1. "Route 3's first encounter is spent (Rattata, caught as Nibbles)"
2. "Breeding is off in this nuzlocke"
3. "Cable trades are off in this nuzlocke"
4. "Level cap 14 until Brock"

A pin on such a goal is accepted and waits with its reason, as for any pin since typed goals slice 5, so it never runs.

The catch of a first encounter during travel is not a goal. It is a stance: `planning/stance.py` returns CATCH when the area is open and the foe is not a dupe, whatever goal runs. Running out of balls would lose the encounter, so the decide pipeline's supplies need keeps a floor of Poké Balls while an open area lies on the next goal's route.

### 3.4 Pricing the risk of a death

No faint probability model exists today. The battle code uses the most damage the foe can do (`incoming`, `policies/battle.py:358`), and the oracles price levels, not deaths. The plan adds one oracle per adapter and raises two bars:

1. **Danger.** `danger(view, spec)` from 0 to 1. For a trainer, boss or League goal it is the level gap and type matchup the readiness oracles already score (`planning/readiness.py`, `gen2/readiness.py`). For a hunt it is the area's wild level gap.
2. **Rank.** A goal ranks by worth times (1 minus danger). Above a danger bar it fails `not_now`, "Too risky: Brock's Onix outlevels the party by 4", and the needs step offers the training that lowers it, as it does for a boss today.
3. **Readiness.** The margin over the next boss's ace (`MARGIN = 10`, `planning/readiness.py:40`) and the half HP and PP bar before a boss (`planning/boss.py`) move to the adapter table, raised in the mode. Before a boss the party is at full HP and PP.
4. **Worth.** A catch is worth what it adds to the team, not only its dex entry, so a strong first encounter in a risky area can still be worth the walk.

The bar and the numbers come from slice 5's seeded runs, not from a guess.

### 3.5 Battle policy weighs survival over speed

Both battle codes (`policies/battle.py:345-489`, `gen2/policy/battle.py:52-254`) read a survival table from the adapter:

1. Heal or switch at HP at most 2 times `incoming`, not 1.5 times (`policies/battle.py:396-398`).
2. Switch out before a likely faint, even at the cost of a turn, to the living member with the best matchup. Today the send after a faint picks the most HP (`policies/strategic.py:815-830`).
3. Never send or switch to a dead member.
4. Weaken a first encounter without knocking it out, as the catch stance already avoids risky chips (`policies/battle.py:20`).
5. Flee wild battles in spent areas unless a train goal wants the experience.

With no items in battle, step 1 switches in place of healing. A hopeless trainer battle cannot be fled, so the bot plays it out with its best move. Set mode needs nothing here, since the game stops offering the switch.

### 3.6 The dead box

The last box is the dead box: box 12 in Gen I, box 14 in Gen II. A dead member is deposited at the next PC as an upkeep need, before anything else there. `pcvalue.may_go` (`pcvalue.py:494`) and every withdraw, the Partner kinds included (`kinds.py:453`), skip dead identities, and the release goal never touches the box. If it fills, the box before it takes the rest. Gen I deposits only into the current box, so a death costs one box switch and the save the game makes with it. That is rare enough to accept.

### 3.7 Both generations through the adapters

The adapter carries what differs between the generations, as in [One bot](one-bot.md). Gen I is the reference: Red and Blue first, then Yellow on the same code.

| Adapter part | Gen I | Gen II |
|---|---|---|
| `area(map)` | town map entries, new in pokecore | landmarks, exist |
| Dead box | box 12 | box 14 |
| Shiny clause | none | from DVs |
| Survival table and `danger` | from `planning/readiness.py` | from `gen2/readiness.py` |
| `reload_targets(saves)` | filters by the nuzlocke barrier | the same, and `RELOAD_AFTER_PARK` still holds |

## 4. Failure

A run has three end states:

1. **Wiped.** The game blacks out (`events.py:157-161`). Every member that fainted in that battle is dead.
2. **Won.** The champion is beaten (choice 4).
3. **Stuck.** The supervisor gives up after 12 reloads (`MAX_RELOADS`, `runtime/supervision.py:52`). That is a bug or a dead end, not a loss, so the run can be resumed after a fix.

After a wipe:

1. The ledger sets wiped at that PlayClock frame and bumps its barrier.
2. The emulator saves a final state for viewing and the worker stops. The ladder's blackout handling (`watch_boss` and `lost`, `runtime/supervision.py:335-358`) never runs.
3. The adventure is marked ended. Its journal, run page, dead box and final screen stay readable, and it cannot be started again.
4. Try again makes a new adventure on the same cartridge with the same rules and a new seed, named "attempt 2" and linked to the first. Choice 1's other path presses it on its own.

Deaths and the story show in the events and the UI:

| Event | Priority | Example |
|---|---|---|
| death | HIGH, notable, push | "Sparky the Pikachu died on Route 3 to a wild Spearow (level 9)" |
| encounter | NORMAL | "Route 3: met a Rattata first, caught as Nibbles" |
| spent | LOW | "Route 4: the Ekans got away, so Route 4 is spent" |
| wipe | URGENT, push | "The run is over: the party fell to Misty's Starmie after 5 hours 12 minutes" |
| won | URGENT, push | "Nuzlocke won with 3 deaths" |

In the mode, death replaces today's faint row, which is MINIMAL and hidden by default (`events.py:154-156`, `gen2/journal.py:68-73`). The journal is SURVIVES (`state/domains.py:156`), so the story outlives reloads and restarts. A run page reads GET `/api/nuzlocke`: the rules, the living party, the dead box as a memorial (nickname, species, level, area, cause, playtime), every area's encounter and the attempt number. The library card says "Nuzlocke, 2 deaths, alive" or "Wiped on Route 9", and the party card's fainted style (`web/static/app.js:319`) becomes a dead mark.

## 5. Replay and cheating

Two rules hold it together:

1. **The ledger is the truth and a save is only a position.** The ledger lives outside the save and every load applies it. A dead Pokémon that a load brings back is still dead and goes to the dead box. A spent area stays spent. A catch the load undid is recorded as lost to a reload, so a rollback is never a reroll (`replayable-bugs.md:288`).
2. **Every ledger change writes a barrier and a save.** A third barrier, `('nuzlocke-barrier-v1', 'ledger_id')`, joins `BARRIERS` (`runtime/emulator.py:42`) and `REWIND_BARRIERS` (`web/app.py:104`). Every manifest stamps it (`runtime/manifest.py:35-37`), and an autosave follows as soon as the game settles after the change. So every reload and every manual load finds a save at or after the latest change.

Each way back, in the mode:

| Way back | Rule |
|---|---|
| Stall reload (`_reload_saves`, `runtime/emulator.py:251`) | Saves behind the barrier are filtered out, as for trades. With none left, `_unstick` already does not reload (`emulator.py:796-801`). |
| Reload out of a battle | The ledger is written first: a wild battle spends its area and each fainted member is dead. Then rule 1. |
| League retry from `league-entry.state` (`LEAGUE_RESTARTS`, `runtime/supervision.py:50`) | Removed. A League loss is a blackout and a wipe. |
| Manual load and the event page rewind (`web/app.py:108`, `:755-762`) | Refused with 409 behind the barrier, as for trades. |
| Boot after a crash (`emulator.py:217`) | The newest save can predate a death by up to 5 game minutes. Rule 1 applies. |
| Power cycle with no saves (`emulator.py:802-811`) | Rule 1 applies to whatever the cartridge save holds. |
| Backup loaded as a new adventure (`app/backup.py:267`) | The backup must carry the ledger, and the copy is marked "restored from a backup". |

So the supervisor's ladder keeps its rungs (park, reload, give up) with one rule: a reload goes only to a save at or after the barrier, the League restart rung is gone, and a blackout ends the run in place of feeding `watch_boss`.

Seeded play stays replayable:

1. The rules ride in the trace header and the manifest, and the ledger is a policy read, so a replay sees both.
2. The observer is a pure function of snapshots on PlayClock frames, so a replay from a save rebuilds the same ledger and makes the same choices.
3. `tests/test_determinism.py` gets a nuzlocke case: a reload after a death keeps the death and the trace head hash.

## 6. Slices

One PR per row. Each deletes what it replaces, runs the targeted tests, and shows in its body that the gate is unchanged with the mode off. Heavy runs go through `tools/load_gate.sh heavy`.

| # | Scope | Behaviour change | Agent time |
|---|---|---|---|
| 1 | The `nuzlocke` setting, the presets, the lock at start, the create form, the manifest and trace stamp | none unless on | about 2 hours plus 30 minutes of tests |
| 2 | The Gen I area table from the cartridge, the ledger and its observer, GET `/api/nuzlocke` | the ledger fills, no rule holds yet | about 4 hours plus 1 hour |
| 3 | Gen I rules: the feasibility check and `rule` failure, the catch stance, the dupes clause, forced nicknames, free gifts, no claims or returns, trades blocked, the dead box | the rules hold | about 5 hours plus 1 hour of gate |
| 4 | The barrier, the barrier save, loads apply the ledger, the ladder and rewind rules, the determinism case | no reload or rewind undoes a death | about 3 hours plus 1 hour |
| 5 | The survival table, the `danger` oracle and the raised readiness bars, measured on 10 seeded Red runs | the bot plays safer | about 4 hours plus 3 hours of seeded runs |
| 6 | The end states, Try again, the new events, the run page and the library badge | a wipe ends the run | about 4 hours plus 30 minutes |
| 7 | Hardcore: level caps, no items in battle, set mode | only when picked | about 3 hours plus 1 hour |
| 8 | Yellow | Yellow gets the mode | about 2 hours plus 1 hour |
| 9 | Gen II through the adapter: landmarks, box 14, the shiny clause, breeding off, its survival table and `danger` | Gold, Silver and Crystal get the mode | about 6 hours plus 2 hours |
| 10 | Trades only between nuzlocke runs, if choice 2 picks it | only when picked | about 2 hours plus 1 hour |

**First playable version:** slices 1 to 6 on Red and Blue with the Classic preset, about 22 hours of agent work plus about 7 hours of tests and runs. Slice 5 is in it because without it the bot loses its party early and the run is not worth watching. Slices 7 to 10 add about 13 hours plus 5 hours.

## 7. Open questions for the build

1. Rule 1 makes an older save safe, and the barrier save makes needing it rare. Slice 4 measures how often a stall reload has no save at or after the barrier.
2. The danger bar, the switch multiple and the readiness margin are guesses until slice 5 measures deaths per run against them.
3. A run that is stuck for many game hours with no feasible goal (every area spent, the next boss too risky) may need its own end state. Slice 5's runs will show whether it happens.
