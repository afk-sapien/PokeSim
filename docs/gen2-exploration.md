# Gold, Silver and Crystal support

This branch implements Generation II adventures in the normal Library and
adventure runtime. Gold, Silver and Crystal have each completed Johto, the
Pokémon League, all eight Kanto gyms, and Red through ordinary cartridge input.
The original boot experiment remains available in `tools/probe_gen2.py`.

The branch is `codex/gen2-exploration`, based on release `v0.4.17` at `c3fc0c9`.
Its local worktree is `/home/ty/Repos/pokesim/.worktrees/gen2-exploration`.
The separate `codex/release-0.4.18` checkout and its emulator migration have not
been modified. This work is not part of the published v0.4.17 package.

## Supported cartridges

| Game | Retail revision | SHA-1 |
| --- | --- | --- |
| Gold | USA, Europe | `d8b8a3600a465308c9953dfa04f0081c05bdcb94` |
| Silver | USA, Europe | `49b163f7e57702bc939d642a18f591de55d92dae` |
| Crystal | USA, Europe, Rev 1 | `f2f52230b536214ef7c9924f483392993e226cfb` |

ROM installation accepts these cartridges as raw files or a ZIP containing one
supported cartridge. ROM assets remain read-only. Each adventure owns its own
SRAM, real-time clock, checkpoints, policy memory and journal. Other revisions,
languages and ROM hacks are rejected instead of using incompatible addresses.
No ROM, save, screenshot, reference checkout or full symbol file is committed.

## Runtime and gameplay

- Library creation, per-game starters, worker isolation, pause, manual controls,
  speed, audio, health reporting, restart and standard `.sav` export.
- Complete Johto and Kanto campaign goals, including the Radio Tower, Ice Path,
  Strength puzzles, Dragon’s Den, S.S. Aqua, Power Plant, Snorlax and Mt. Silver.
- Battle decisions, healing, safe capture weakening, status moves, party
  switching, move learning, HM protection and recovery from depleted supplies.
- Fishing, Surf, Fly, Cut, Strength, Whirlpool, Waterfall, Headbutt and Rock Smash.
- All 251 species, all moves, version and time dependent encounter tables,
  six battle stats, Dark and Steel types, gender, friendship, held items,
  eggs, shiny DVs, all 14 PC boxes and cartridge portraits.
- Postgame collection, gift quests, Day Care breeding and hatching, Exp. Share
  projects, item and friendship evolution, and continued level 100 training.
- Legendary quests, roaming beast tracking and delayed retries after failed
  static legendary encounters. Retries preserve consumed supplies and progress.
- Durable capture counts, Pokédex milestones, observed activity statistics,
  cartridge walking counts, individual League records and notifications through
  the existing integrations. Collection expeditions also catch spare copies
  requested by compatible adventures in the Library.
- Optional Johto starter gifts after League victories and the optional custom
  Mew gift, with repeat Mew earned by walking and a later League victory.
  Gift claims, checkpoint publication and recovery prevent duplicate
  delivery or a rewind across the latest committed gift.

Gold, Silver and Crystal can trade with each other through the managed Cable
Club. Preparation uses the cartridge PC and held-item menus. The exchange runs
both cartridges through their link routines, verifies the resulting party,
checks unaffected Pokémon and story state, verifies a fresh cartridge Continue,
and uses the existing durable two-adventure commit protocol. Held-item trade
evolutions and individual League records travel with the exchanged Pokémon.

## Validation

Testing uses Python 3.12.3 and PyBoy 2.7.0 with the owner-supplied cartridges.
The full regression suite passed 1,822 tests with 151 skipped.
Skipped tests retain their existing external fixture or environment requirements.

Recorded cartridge scenarios include:

| Scenario | Evidence |
| --- | --- |
| Gold, Silver and Crystal campaign | All 16 badges and Red defeated in each version |
| Fresh Gold campaign | One uninterrupted process, 3,108,188 frames through Red |
| Fresh Silver campaign | Chikorita, one uninterrupted process, 4,783,228 frames through Red |
| Fresh Crystal campaign | Cyndaquil, one uninterrupted process, 3,415,124 frames through Red |
| Low-cash Chikorita recovery | Sold a spare TM, bought balls, weakened and caught Krabby, continued through Red |
| Full party before Togepi | Deposited a partner through the PC and received the egg |
| Day Care | Deposited compatible parents, received and hatched Wooper, retrieved both parents |
| Special encounters | Caught Heracross using Headbutt and Shuckle using Rock Smash |
| Legendary quests | Caught Crystal Suicune and Lugia, Gold Lugia and Ho-Oh |
| Missed legendary recovery | Retried the failed Gold Ho-Oh encounter and caught it |
| Gift quests | Eevee, Crystal Odd Egg, Dratini, Kiyo’s Tyrogue and Bill’s grandfather’s first gift |
| Cable Club | Gold/Silver, Gold/Crystal and Silver/Crystal exchanges |
| Held trade evolution | Prepared Metal Coat through the menu, traded Onix and received Steelix |
| Runtime API | Pages, 251-entry Pokédex, PC, journal, statistics, manual input, audio, paused frame and restart |
| Portable saves | Fresh Continue verified for all three games |
| Optional rewards | Valid party and box preservation, fresh Continue, durable claim and replay protection |
| Repeat Mew | First and repeat gifts on all three cartridges, later win requirement and duplicate prevention |
| Library integration | Three installed games, three actual workers, automatic selection and committed Cable Club exchange |
| Reference installation | Clean download and generation from pinned public sources for all three games |

Private evidence, traces and reproducible failure checkpoints are under
`.release-local/`. The scenario runner reports its actual stopping reason and
retains both the cartridge checkpoint and policy state.

## Reproduce

Install this checkout in an isolated Python environment, then launch the normal
Library with `pokesim-desktop`. Add an owner-supplied cartridge and choose the
matching starter. The first installation prepares the generation-specific data.

With local cartridge and generated data directories, run the regression suite:

```sh
GAME_DATA_DIR=.release-local/gen1-data \
GEN2_DATA_DIR=.release-local/gen2-data \
GEN2_CARTRIDGE_DIR=.release-local/gen2 \
GEN2_ROM_DIR=/home/ty/Downloads \
.venv/bin/pytest -q tests
```

Run a complete isolated campaign:

```sh
.venv/bin/python tools/play_gen2.py .release-local/gen2/crystal.gbc \
  --game crystal --starter cyndaquil --frames 10000000 --until red \
  --data .release-local/gen2-data --output .release-local/crystal-campaign
```

`--load PATH` resumes a cartridge checkpoint and its sibling `.policy.json`.
Focused scenarios include gifts, legends, breeding, stones, Headbutt, Rock
Smash and a specified encounter. Separate verification tools exercise runtime
APIs, capture accounting, portable saves, trade preparation, durable exchange
and custom reward delivery. `tools/verify_gen2_library.py` also exercises worker
restart during trade preparation and reservation release before an automatic
exchange.

## Boundaries

Time Capsule trading between Generation I and Generation II is not implemented.
The coordinator pairs adventures within their cartridge generation. This does
not prevent any Gold/Silver/Crystal pairing.

The autonomous controller is not a proof that every seed will finish without a
stall, or that every optional cartridge activity is automated. The Battle Tower,
Game Corner, Bug-Catching Contest, Ruins of Alph puzzles and limited distribution
events remain available through manual controls. All 251 species have data and
UI support. An autonomous 251-species collection has not been demonstrated.
The Red/Blue Kanto Marathon and repeatable fossil, dojo and NPC-trade rewards
have not been transplanted into the Generation II campaign. Generation II
retries missed static legendary encounters, but does not schedule repeat
encounters with already caught legends. Settings that apply only to Red and
Blue are hidden for these adventures.

## Reference provenance

Game data comes from pinned primary disassemblies:

- [pret/pokegold at 62388c7](https://github.com/pret/pokegold/tree/62388c7204e5d13aa05b4231e220b6760584d1b5)
- [pret/pokecrystal at 5beda23](https://github.com/pret/pokecrystal/tree/5beda23ffa505f62e1dad7e3d7c214d1737b3358)

`pokesim/gen2/data.py` pins the source and symbol revisions, verifies symbol
hashes, generates version-specific data and validates cached bundle checksums.
The original selected-address audit is in
[gen2-symbols.json](validation/gen2-symbols.json).
All banked memory access uses explicit banks. The capture hooks and link
transport check cartridge instruction signatures before they attach.
