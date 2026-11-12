# pokecore state layer

Status: proposed on 2026-11-10. It was read from main at `63cb1717`. It is phase 4 item 1 of the architecture plan of 2026-11-09, together with the plan's section "code in the wrong place" (boundary report findings F2, F4, F6 and F7).

## 1. Goal

1. `packages/pokecore` gets one generation-neutral state layer, `pokecore.state`, with typed battle and menu state for Red, Blue, Yellow, Gold, Silver and Crystal.
2. Gen I box reading and its SRAM bank math move from `pokesim/ram.py` into pokecore, where the Gen II box reader already lives.
3. Raw Gen I addresses in PokeSim modules become pokecore names.
4. `repair_party_nicknames`, PokeSim's one write to game memory, goes behind a named and tested pokecore function.
5. The view and scoring fields `dv_stars` and `potential_power`, with the rest of the DV rating, move out of pokecore's Gen II `Mon.to_dict` into PokeSim.
6. A test fails on a new raw RAM literal or a new direct symbol read in PokeSim outside an allow list, so the leak stays closed.

## 2. What is there today

1. Gen I talks to pokecore through flat `W_*` constants and dicts (`packages/pokecore/src/pokecore/gen1.py`). The typed Gen I `Snapshot`, `PartyMon` and `StoredMon` live in `pokesim/ram.py`.
2. Gen II has a typed `Mon` and `Snapshot` in `pokecore.gen2.ram`, but `read_snapshot` needs PokeSim's tables, and policies read 87 symbols by name (`mem.byte('wEnemySubStatus5') & 128`).
3. Hex RAM literals remain in 21 PokeSim modules outside `pokesim/gen2`. The largest are `activity_ledger.py` (18), `policies/strategic.py` (11), `screen.py` (9), `catches.py` (8), `shiny.py` and `fair_dvs.py` (6 each).
4. Three PokeSim modules copy code pokecore already has. `pokesim/yellow.py` repeats `pokecore.yellow.RedLayoutMemory`. `pokesim/gen2/cable_metadata.py` and `pokesim/interactions/cable_metadata.py` repeat `pokecore.gen2_link_metadata` and `pokecore.gen1_link_metadata`.
5. `pokesim/ram.py` reads inactive boxes at `0xA000 + (box % 6) * 1122` in bank `2 + box // 6`, and writes nickname terminators into the party.

## 3. Rules for every slice

1. A slice changes no behaviour. The same memory gives the same snapshot, the same payload and the same actions. Persisted payloads and checkpoint fields keep their names.
2. A slice is small enough to merge alone and is reverted alone.
3. Before each merge, compare the slice's files with every open pull request. A slice that shares a file with an open goal system v2 pull request waits for it, then rebases.
4. Each slice needs green CI and a passed `tools/preflight.py`, then merges with auto-merge.
5. pokecore stays free of text, sprites, music and ROM bytes. Addresses, IDs and bit names may ship. Tables stay with the consumer, as today.
6. Gen I surfaces the benchmark package uses (`gen1` constants, `read_party`, `read_bag`, `read_progress`, `storage.decode_box`, `memory_bytes`) only gain names. Nothing is renamed or removed there.
7. No pokecore release is cut for this work. PokeSim uses the workspace copy, as `pokesim/gen2/routes.py` already does for `pokecore.gen2.mapfacts`. The next pokecore release notes the changes.

## 4. Slices, in order

Agent time per slice is 1 to 4 hours plus CI and a 10 minute preflight.

1. **Guard.** `tests/test_ram_literals.py` counts, per PokeSim module, hex literals in cartridge RAM, WRAM and HRAM (`0xA000` to `0xDFFF`, `0xFF80` to `0xFFFE`) and direct symbol reads (`mem.byte('w...')`, `.word`, `.read`, `.text`, and `['w...']` keys). It fails when a module goes above its allowance or a new module has any. Counts start at today's values and only go down. Tests only.
2. **Drop the copies.** `pokesim/yellow.py` uses `pokecore.yellow` for the layout view and the emulator. The two `cable_metadata.py` modules re-export pokecore's link metadata after a test proves the tables equal.
3. **Gen I names, outside the policies.** Add the missing names to `pokecore.gen1` (battle mon, enemy HP and DVs, battle status 3, link state, menu cursor and scroll, options, `wd728`, `wd733`, `wd737`, `hRandomAdd` and the rest found). Replace the literals in `screen.py`, `activity_ledger.py`, `shiny.py`, `fair_dvs.py`, `trade_statistics.py`, `scenarios.py`, `step_events.py`, `replay/rung.py`, `trade/boxes.py` and `adventure_records.py`.
4. **Gen I names, in the policies.** The same in `policies/strategic.py`, `policies/battle.py`, `policies/navigation.py`, `policies/travel.py`, `runtime/preparation.py`, `catches.py` and `emulator.py`. These files are in the v2 pull requests, so this slice waits for them.
5. **Gen I boxes in pokecore.** `pokecore.storage` gains `box_location(box, active)`, `read_box_counts` and `read_box_records`, built on `decode_box`. `pokesim/ram.py` keeps `StoredMon`, its species and level filter, maximum PP and the PC list check, and calls pokecore for the bytes.
6. **Nickname repair in pokecore.** `pokecore.repairs.repair_party_nicknames(memory, *, version=None)` holds the write, in a module named for writes so the decoders stay read only. It is tested on Red and Yellow layouts. `pokesim/ram.py` calls it.
7. **View fields out of Mon.to_dict.** PokeSim gets `pokesim/gen2/views.py` with `mon_view(mon, egg_view=False)`, which adds `perfect_dvs`, `dv_total`, `dv_percent`, `dv_stars` and `potential_power` to pokecore's dict. Every PokeSim caller moves to it first, then pokecore drops the fields. The payload is unchanged. The benchmark package reads only Gen I, so it is not affected.
8. **State types.** `pokecore.state` with frozen `GameState`, `Player`, `Mon`, `Party`, `Bag` and `MapState`, a `generation` field, and `None` for what a generation lacks. `read_state(memory, game)` is a thin layer over the existing decoders. pokecore only, with tests on synthetic memory for all six games.
9. **BattleState.** Kind (none, wild, trainer, tutorial, scripted), both active mons, enemy HP, and named flags: transformed, trapped, can run, link battle. pokecore only.
10. **UiState.** Text box, start menu, menu cursor and scroll, facing, walking, biking or surfing. pokecore only. The shortcut machine already detects most of this internally, so it is exposed, not rebuilt.
11. **Boxes and events in the state.** `GameState.boxes` from slice 5 and `gen2.state.read_box_structs`, and `GameState.events` from the event flag arrays.
12. **Consumer moves, handed to phase 3.** Changed on 2026-11-11. The Gen I hook modules (`activity_ledger.py`, `shiny.py`, `fair_dvs.py`, `catches.py`) stay as they are. After slices 3 and 4 they read only pokecore names, so the guard counts none of their reads. At hook time they also need bytes `BattleState` does not hold: Species2, the link state outside a battle, the raw `wIsInBattle`, bag slots and the DV write. The Gen II policy reads move with phase 3 item 5, as section 6 says.

Slices 8 to 11 change only pokecore, so they can run while slices 3 to 7 wait on open pull requests.

## 5. Choices

1. **One `Mon` for both generations.** Fields both have keep one name (`nick`, not `nickname`). `species` is the cartridge's ID and `dex` the national number from `pokecore.identity`. `held_item`, `friendship` and `pokerus` are `None` in Gen I. The existing readers build it, so `read_party` and `gen2.ram.Mon` stay as they are.
2. **No tables.** The state holds IDs. Maximum PP takes an optional base PP mapping, as `gen1.read_party` does now.
3. **Speed.** `read_state` reads the same bytes as the current snapshot readers. A consumer move that makes a tick slower is measured with `pokesim/benchmark.py` before it merges.
4. **Parity.** A pokecore test checks that every `GameState` field is filled for one game of each generation, or is listed as absent by design with a reason, like `tests/test_generation_parity.py` does for payloads.
5. **Writes.** pokecore's decoders only read memory. Named writes live in `pokecore.repairs` and `pokecore.resets`, each with a test.

## 6. Hand-off to phase 3 item 5

Done. `pokesim/gen2/policy/` kept 72 direct symbol reads, 51 of them on the battle side and most of the other 21 menu, facing and bike state. None are left. Each decision now builds one `policy/reads.Reads`, which reads `read_battle` and `read_ui` when first asked, and the rest are snapshot fields that do not count toward snapshot equality. Modules outside the package that take memory still read it. The tick was measured before and after on three saves, and the per-decision dumps match. The steps it followed:

1. Call `pokecore.state.read_battle(memory, game)` and `read_ui` once per tick, next to the snapshot, and pass the results down. Calling them at each read site would decode both battle structs every time.
2. Fields the policy reads that `BattleState` or `UiState` lacks, such as substatus, screens, Disable and the last enemy move, are added in pokecore first, each with a test. Gen I fills the same field or leaves it `None` with a written reason.
3. Each pull request measures the tick with `pokesim/benchmark.py` and lowers the policy's numbers in `tests/test_ram_literals.py`. Until then the guard keeps them from rising.

## 7. Not in this note

The table reader that replaces the three table pipelines (boundary report F3) is scheduled last in the plan. Splitting `shortcuts/actions.py` per generation is a separate refactor.
