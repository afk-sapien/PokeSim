# Gold, Silver and Crystal exploration

Generation II is feasible on the emulator shipped with PokeSim v0.4.17. The
three owner-supplied cartridges boot in color, complete the opening, move in
the bedroom, and resume reproducibly from checkpoints. Full autonomous
adventures are not implemented by this experiment.

The branch is `codex/gen2-exploration`, based on release tag `v0.4.17`, commit
`c3fc0c9`. The local worktree is
`/home/ty/Repos/pokesim/.worktrees/gen2-exploration`. The existing
`codex/release-0.4.18` checkout contains uncommitted emulator migration work.
This experiment does not incorporate or modify that work.

## Verified scope

Validation ran on October 5, 2026, with PyBoy 2.7.0 and Python 3.12.3.
Each cartridge was read from its ZIP in the owner's Downloads folder.

| Game | Retail revision | SHA-1 | Result |
| --- | --- | --- | --- |
| Gold | USA, Europe | `d8b8a3600a465308c9953dfa04f0081c05bdcb94` | Passed |
| Silver | USA, Europe | `49b163f7e57702bc939d642a18f591de55d92dae` | Passed |
| Crystal | USA, Europe, Rev 1 | `f2f52230b536214ef7c9924f483392993e226cfb` | Passed |

The hashes match the retail builds documented by
[pret/pokegold](https://github.com/pret/pokegold) and
[pret/pokecrystal](https://github.com/pret/pokecrystal).
Crystal 1.0, other languages, hacks, and other revisions are not accepted by
this probe.

All three passed these checks with an isolated blank cartridge RAM buffer:

1. Boot in CGB mode with sound hardware emulation enabled.
2. Reach map group 24, map 7, position `(3, 3)` through ordinary button input.
3. Read the player name, empty party, badges, and Pokédex state from the
   cartridge's own memory layout.
4. Move one tile right to `(4, 3)`.
5. Restore the bedroom checkpoint and match fixed WRAM plus WRAM bank 1.
6. Replay the same input and match the resulting snapshot, WRAM and pixels.
7. Repeat restore and replay in a newly constructed emulator.

The opening replay takes 7,920 frames and names the player `AAAAAAA`. It is
a deliberately small fixed input sequence, not an opening policy. The tests
lock the cartridge clock before the first tick. They do not establish real
time clock persistence or deterministic replay with a running clock.

The focused suite passed **23 tests**, including all three real cartridges.
The recorded [validation report](validation/gen2-probe.json) contains the
snapshots and check results. Local screenshots and checkpoints are under
`.release-local/gen2-validation-v2/`, with one subdirectory per game.
ROM bytes, full symbol files, screenshots and save states are not committed.

## What this branch adds

- `pokesim/experimental/gen2.py`: exact hash identification, bounded local
  ZIP loading, separate Gold/Silver and Crystal memory profiles, and a
  read-only diagnostic snapshot.
- `tools/probe_gen2.py`: a repeatable headless boot, input and checkpoint
  probe that runs separately from the adventure runtime.
- `tests/test_gen2_experiment.py`: decoder boundary tests and optional real
  cartridge integration tests.
- `docs/validation/gen2-symbols.json`: pinned source URLs, file hashes and
  the selected addresses used by the profiles.

The decoder handles map group and number separately, 251 Pokédex flags,
two badge bytes, 48-byte party records, held items, moves, eggs and separate
Special Attack and Special Defense. Party records beyond the empty starting
party have synthetic coverage only. Live starter, capture, battle and egg
fixtures remain necessary. The name decoder covers English letters, numbers
and spaces, preserving unsupported glyph bytes visibly.

All reads use explicit WRAM bank 1. A CPU-visible address alone is unsafe
for banked CGB memory, especially while Crystal switches banks. The probe
does not write game RAM or attach hooks.

## Reproduce

From the exploration worktree, use an isolated environment:

```sh
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python 'pyboy==2.7.0' pytest pillow
.venv/bin/python -m tools.probe_gen2 \
  '/home/ty/Downloads/Pokemon_ Gold Version.zip' \
  '/home/ty/Downloads/Pokemon_ Silver Version.zip' \
  '/home/ty/Downloads/Pokemon_ Crystal Version.zip' \
  --output .release-local/gen2-next-run
GEN2_ROM_DIR=/home/ty/Downloads .venv/bin/python -m pytest tests/test_gen2_experiment.py -q
```

The output directory must be new. Plain `.gbc` files also work. The tool
accepts exactly one cartridge per ZIP and never extracts archive paths.
ROMs are copied into a temporary directory for emulation, then removed.
No adjacent Downloads save or clock file is read or written. The original
archives remain untouched.

Without `GEN2_ROM_DIR`, the decoder tests run and the three real cartridge
tests skip. The minimal environment above does not install the full
application or its data bundles. The existing Red/Blue application suite
was not run for this isolated experiment.

## Work needed for supported adventures

| Area | Current obstacle | Next implementation |
| --- | --- | --- |
| ROM installation | `desktop_setup.py` caps uploads at 1 MiB and accepts only Red/Blue hashes. `app/assets.py` maps the version to Red or Blue. These cartridges are 2 MiB. | Introduce explicit game profiles and capability gates before changing the production allowlist. |
| Runtime observation | `ram.py` imports Gen I core addresses and tables. `emulator.py` attaches Gen I hooks and writes Gen I options. | Dispatch observation, options and hooks through a game adapter. Keep unsupported Gen II operations disabled. |
| World data | Reference bundles and generators are pinned to pokered. Navigation assumes its maps and events. | Generate versioned Gen II maps, collisions, warps, scripts, encounters and event data from pinned pret references. Preserve map group plus number. |
| Policy | Opening, menus, battles, shopping, gyms and collection are Gen I specific. Starter settings only accept the Kanto starters. | Start with bedroom to Elm, starter acquisition, first wild battle and first capture. Add route and badge goals after those fixtures pass. |
| Pokémon and interface | Much of the data, portraits, collection and completion logic assumes 151 species and Gen I stats. | Support 251 species, split Special stats, held items, friendship, eggs, new types and evolution rules in shared schemas and UI. |
| Persistence and time | This probe freezes RTC and only checks emulator checkpoints. | Test cartridge save checksums, save export, clock files, day rollover, reload after elapsed wall time and time-dependent encounters. |
| Trading | Existing cable scripts, hook addresses and save layouts target Gen I. | Design and test Gen II trades separately. Treat Time Capsule compatibility as another capability. |
| Emulator migration | The release 0.4.18 checkout is moving to a different emulator interface. | Repeat CGB, banked memory, RTC, input and checkpoint checks against that backend before integrating. |

A useful first product milestone is an explicitly experimental manual
Gen II adventure with correct observation, isolated persistence and safe
capability gating. The first autonomous milestone should be a repeatable
Elm starter and first capture scenario for each game. Completing the
Johto campaign and trading need substantially more work than adding ROM
hashes to the existing installer.

## Reference provenance

The exact symbol files are linked in
[gen2-symbols.json](validation/gen2-symbols.json). Their addresses were
cross-checked against live bedroom movement for every cartridge.
Party field definitions and the English text alphabet were checked against
[pokecrystal constants](https://github.com/pret/pokecrystal/tree/5beda23ffa505f62e1dad7e3d7c214d1737b3358/constants)
and [pokegold constants](https://github.com/pret/pokegold/tree/62388c7204e5d13aa05b4231e220b6760584d1b5/constants).
The experiment uses the installed PyBoy 2.7.0 implementation for its memory,
clock and checkpoint API behavior.
