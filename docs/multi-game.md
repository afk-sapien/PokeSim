Current scope: see [roadmap.md](roadmap.md). This document records earlier design work. Trading is being introduced as read-only proposals, followed by individually approved exchanges. Completion and automatic trading are not current commitments.

# Multiple cartridges that trade with each other

A plan for running several pokesim instances — one per cartridge — and letting them trade, so a
Pokédex can be completed the way Generation I intended rather than by modifying a ROM.

## Why

One vanilla cartridge cannot complete the Pokédex. In a Red run, 26 species need a second game:
11 Blue exclusives, 4 trade evolutions, 6 unchosen starter-family members, and the unchosen
Hitmon, Eevee and fossil lines. That is the cartridge's design, not a gap in the policy, so no
amount of planning work closes it.

## Runtime shape

Each cartridge is an ordinary pokesim container: its own ROM, `DATA_DIR`, port, journal, feed and
Pokédex page. Nothing about a single run changes.

| Instance | ROM | URL | Port | Data |
| --- | --- | --- | --- | --- |
| `pokesim` | Red | https://pokesim-red.tynet.app | 8930 | `/docker/pokesim/data` |
| `pokesim-blue` | Blue | https://pokesim-blue.tynet.app | 8940 | `/docker/pokesim-blue/data` |

Both homeserver instances use the GUI update from September 13, 2026, including separate PC
and Pokédex pages and locally installed sprites. The original `pokesim.tynet.app` URL remains
an alias for Red. Deployment and rollback details are in [homeserver.md](homeserver.md).

Version selection already works: `config.KNOWN_ROM_SHA1` identifies the cartridge and
`emulator.py` sets `collection.version` from it, so a Blue instance plans against Blue encounter
tables without configuration.

The instances never talk to each other directly. A **broker** coordinates them.

## Two layers

Keep these separate; the second one is the risky half and must never block the first.

**Negotiation — what to trade.** Pure decision-making over two inventories. No emulator involved.

**Execution — how to trade.** A backend that carries out an agreed swap. Two implementations,
same interface.

## Negotiation

Each instance already publishes everything the broker needs at `/api/pokedex/status`: owned and
seen dex numbers, the party, and every stored Pokémon with its dex number and level.

A proposal pairs a *want* with a *price*:

- **Want** — a species missing from my dex that the peer holds a spare of.
- **Price** — a spare of mine the peer is missing, or, for premium targets, a trained Pokémon
  meeting an agreed bar (level ≥ 90, say).
- **Never offer** — a party member, or the instance's current hunt target. See "What trades may
  give away" below; the release rule in `policies/team.py:spare_copies` is deliberately stricter
  and governs only the ordinary duplicate path.

Premium targets are the ones worth pricing: trade evolutions and version exclusives. Requiring a
trained Pokémon in exchange gives each run a long-horizon goal — raise something valuable, then
spend it — which is more interesting to watch than an instant swap and is naturally self-limiting.

## Execution backend A — save level

Cheap, low risk, and enough to finish the Pokédex.

1. Both runs pause and checkpoint (the existing `/api/control` pause and save path).
2. The broker boots each side headless on its own ROM, loads its checkpoint, moves the box bytes
   through `pyboy.memory`, and publishes a **new** checkpoint beside the original. There are no
   cartridge `.sav` files to edit — pokesim persists PyBoy save states. Publishing a new state
   rather than overwriting two files is what makes the pair safe: each write is atomic on its own,
   the originals stay readable, and `Emulator.start` already resumes from the newest autosave, so a
   run resumes into the trade by itself.
3. Both runs resume, picking up the traded state.

Containers never interact in real time, and the machinery already exists and is trusted.

Built and verified — `pokesim/trade/`. The box layout was confirmed byte-for-byte against a real
240-Pokémon save: count at `+0`, a 21-byte species list, twenty 33-byte structs at `+22`, OT names
at `+682`, nicknames at `+902`. The stat assumption holds and is provable in-repo: `PARTY_STRUCT`
is 44 bytes and a box struct is 33, so a box entry stores no computed stat and the game rebuilds
them from level, DVs and EVs on withdrawal. Trade evolutions are applied on arrival, including
pokered's own rename of a mon still carrying its species as its nickname.

Checksums (`~sum & 0xFF`, per bank at `0xBA4C`) turned out not to be load-bearing for a save-state
workflow — a running game never reads them and re-stamps them at the next in-game save — but a bad
all-boxes checksum makes the game wipe every box on a title-screen restore, so they are recomputed
anyway, and only for the bank actually written.

## Execution backend B — the real link

Faithful: the games run their own trade protocol, so trade evolutions fire naturally and both
saves are updated by the game itself.

The trade protocol does **not** need to be written. `home/serial.asm` in the pinned disassembly
already implements it — byte-at-a-time exchange, preamble skipping, soft timeouts with retries.
Only the physical layer is missing, and only inside the emulator.

PyBoy cannot help directly: `pyboy/core/serial.py` is a compiled Cython stub that forces
`SB = 0xFF`, and the motherboard is not exposed on the Python object. Forking PyBoy to fix that
means owning a Cython build, against the project's deliberate PyBoy pin.

Instead, intercept at ROM level using supported APIs:

- `hook_register(bank, addr, callback, context)` fires a Python callback at a ROM address and
  resolves names from a `.sym` file.
- `register_file` exposes A, B, C, D, E, F, HL, PC and SP for reading **and writing**.
- Two PyBoy instances coexist in one process.
- pokered is byte-perfect, so building it at the pinned revision yields symbol addresses that are
  valid for the retail ROM.

Hook the serial exchange routine, hand the peer's byte back in `A`, and the game does the rest.

Because the broker owns both instances, there is no timing problem: the side waiting for a byte is
simply not ticked until the other side produces one. A rendezvous, not clock synchronisation.

Two costs remain. The hook must make the routine return early instead of waiting on hardware,
which means adjusting `PC`/`SP` in the callback — the primitives are writable but this is unproven
and deserves a spike before anything else is built. And both runs must physically walk into a
Pokémon Center, talk to the Cable Club attendant, sit at the table and work the trade menus in
sync. That is policy work comparable to the existing PC and storage handling, doubled.

## What trades may give away

Releases and trades follow different rules, deliberately. A release is pure loss, so
`policies/team.py:spare_copies` never gives up the last copy of a species. A trade returns
something and, crucially, the Pokédex entry persists once registered — giving away a last Nidoking
costs the specimen, not the record. So trades may offer a species' best or only **boxed** copy.

Party members are never offered. That is also what protects HM carriers, since the policy keeps
field-move users in the party and boxed Pokémon are never used for HMs. The instance's current
hunt target is never offered either. Spares are still preferred: a keeper is only spent when the
proposal needs it, which is what makes a premium price payable at all.

## Milestones

1. **Blue instance — done.** `pokesim-blue` on servarr:8940, own data directory, available at https://pokesim-blue.tynet.app.
2. **Broker, read-only — built.** Poll both `/api/pokedex/status` endpoints and publish proposed trades —
   a trade board page showing what the two runs could exchange and at what price. No writes, so no
   risk, and it makes the negotiation rules visible before anything acts on them.
3. **Backend A — built and verified.** Executes agreed trades at save level; a real cross-version
   Red-to-Blue trade produced a Gengar from a traded Haunter with experience, DVs, EVs and PP
   unchanged. Not yet wired to the live instances.
4. **Hook spike — done, GO.** See `docs/link-spike.md`. Two PyBoy instances ran retail Red's own
   `Serial_ExchangeBytes` against each other and exchanged 16 bytes in order, in one frame, with
   `Serial_ExchangeByte`'s body never executing. The early return works because PyBoy's hook opcode
   does not advance PC: pop the return address off SP, set PC to it, put the byte in A. The
   counterpart, re-entering a call later with its body still unrun, is what makes the threadless
   rendezvous work. Symbols were built from pokered at the pinned revision and the resulting ROM is
   md5-identical to `roms/pokered.gb`.

   Two caveats from the spike. Link *establishment* is untouched — `Serial` is an interrupt handler
   rather than a called routine, so the early-return trick does not apply to it, and it deserves its
   own short spike. And the routine is not reachable through gameplay without a save, a Pokémon
   Center and the Cable Club, so everything was driven from a planted caller rather than from play.
5. **Cable Club policy plus backend B.** Swap the execution backend behind the same interface.

Steps 2 and 3 deliver the outcome. Steps 4 and 5 buy authenticity, and can fail without costing it.

## Open questions

- Does a third instance add anything, or is Red plus Blue sufficient? A third would mostly help
  with duplicate supply for premium prices.
- How should the broker be scheduled — continuously, or only when one side is blocked on a want?
- Should a trade appear in both journals as a paired event, and should it push to ntfy?
- Whether the Cable Club attendant and trade menus are reachable without new screen kinds in
  `screen.py`.
