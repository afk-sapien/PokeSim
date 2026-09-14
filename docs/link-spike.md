# Link spike — intercepting a ROM routine from Python

Milestone 4 of `docs/multi-game.md`. One question:

> Can we intercept a Game Boy ROM routine from Python with PyBoy's supported APIs, supply a
> return value, and make the routine return early without executing its body?

**Yes. GO for execution backend B.**

Everything below was measured, not reasoned about. `tools/link_spike.py` reproduces all of it:

```
/home/ty/Repos/pokesim/.venv/bin/python tools/link_spike.py all --rom roms/pokered.gb
```

Four stages, all PASS. No PyBoy modification, no fork, no thread, no serial emulation.

## The headline result

Two PyBoy instances in one process ran the **real** `Serial_ExchangeBytes` block transfer from
retail Pokémon Red against each other and exchanged sixteen bytes each, correctly and in order,
in a single outer frame — preamble skipping and all, driven entirely by ROM code. The body of
`Serial_ExchangeByte` executed **zero** times on either side.

The same program without interception hangs forever at `PC=0x21cc`, busy-waiting inside the
routine for serial hardware that PyBoy does not provide. That is the status quo the hook removes.

## The early-return technique

PyBoy installs a hook by replacing the instruction at `bank:addr` with opcode `0xDB`, which sets
a "bail" flag. The important consequence, from `pyboy/core/opcodes.py`:

```python
def BRK(cpu):
    cpu.bail = True
    ...
    # NOTE: We do not increment PC
```

So **inside the callback, `PC` is the hook address and the hooked instruction has not run yet**.
If the hook is on the routine's *first* instruction, the only thing on the stack that belongs to
this routine is the return address pushed by the caller's `call`. Emulating `ret` is therefore
three lines:

```python
def force_return(pyboy, value=None):
    rf, mem = pyboy.register_file, pyboy.memory
    sp = rf.SP
    ret_addr = mem[sp] | (mem[sp + 1] << 8)   # pop, little-endian
    rf.SP = (sp + 2) & 0xFFFF                 # ... and discard
    rf.PC = ret_addr                          # resume at the caller
    if value is not None:
        rf.A = value & 0xFF                   # Gen I returns single bytes in A
```

After the callback returns, PyBoy restores the original opcode, single-steps **one** instruction
from the new `PC`, then re-injects the hook. Execution simply continues at the caller. Verified
by a hook planted on the routine's second instruction: it fires thousands of times in the control
run and exactly zero times under early return, while a RAM witness incremented by the body stays
at zero and the caller's own progress counter keeps climbing.

Register writes are observed by the ROM independently of the PC/SP trick: hooking the routine's
own `ret` and setting `A` there makes the caller store our value instead of the routine's.

Preconditions that matter:

- **Hook the routine's first instruction.** If the routine has already pushed registers, `SP`
  does not point at the return address and this corrupts the stack.
- **The caller must have used `call`.** A tail-called routine (`jp`) returns to its caller's
  caller; that is still correct behaviour, but the return address on the stack is not the
  instruction after any `call` you can see.
- **The cycles the routine would have burned are not accounted.** See "Cost" below.

### The counterpart: stalling instead of returning

Sometimes the answer is not ready. Returning a wrong byte is not an option and letting the body
run means a hardware busy-wait. The counterpart is to **un-execute the `call`**:

```python
def rewind_call(pyboy, entry):
    rf, mem = pyboy.register_file, pyboy.memory
    sp = rf.SP
    ret_addr = mem[sp] | (mem[sp + 1] << 8)
    call_site = (ret_addr - 3) & 0xFFFF
    assert mem[call_site] == 0xCD                                       # `call nn`
    assert (mem[call_site + 1] | (mem[call_site + 2] << 8)) == entry    # ... to us
    rf.SP = (sp + 2) & 0xFFFF
    rf.PC = call_site           # the routine will be entered again, body still unrun
```

The two assertions make this safe: it refuses to act unless the call site really is a three-byte
`call` to the hooked address. In pokered it always is — `Serial_ExchangeBytes+7` is literally
`cd 9a 21`.

A stalled side is then parked at a `jr @` so it burns no emulated work until the scheduler ticks
it again. Parking cut the stall count in the block-transfer demo from 23 350 to 8.

## The rendezvous

Two `PyBoy` objects in one process, a byte mailbox each, no threads and no clock synchronisation:

- On a hook hit, a side publishes its outgoing byte (read from `hSerialSendData`, `0xffac`) into
  the peer's mailbox.
- If its own mailbox has a byte, it consumes it and `force_return`s with that byte in `A`.
- If not, it **drives the peer from inside its own callback** — `peer.pyboy.tick(1)` — until the
  peer publishes. That is the literal "block inside the callback until the peer produces".
- A side that is already ticking is never re-entered; it `rewind_call`s and parks instead. So the
  nesting depth never exceeds two, and reentrancy into a `tick()` already on the stack — which
  would corrupt PyBoy's breakpoint state machine — cannot happen.

Confirmed in practice: the blocked side is simply not ticked, and there is no timing problem.
Sixteen bytes each way completed inside one outer frame, byte-for-byte correct in both directions.

The frame is the finest granularity `tick()` offers, which is why the stall path exists at all: a
nested `tick(1)` runs the peer for a whole frame, during which the peer may need many more bytes
than it has. Stalling absorbs that cleanly.

## Cost: a hook is transparent, an early return is not

Measured against `CopyData` (`00:00b5`), which loops by jumping to its own entry so the hook fires
once per byte copied, over 600 frames from cold boot:

| run | hook hits | first frame differing from control |
|---|---|---|
| observe only (callback does nothing) | 4 480 | **never** |
| intercept (copy done in Python, early return) | 35 | 326 |

So **an observe-only hook is bit-exact transparent** — 4 480 interceptions of the CPU with no
observable effect at all. That is a stronger result than expected and it means read-only hooks are
free to use anywhere.

An early return is not transparent, and the reason is cycle budget, not incorrectness: the
Python replacement reproduced the routine's effects and end state exactly (326 bit-identical
frames covering 35 real calls), but the ~7 600 CPU cycles the routine would have burned simply
vanish. `rDIV` and the cycle counter diverge at frame **324**, two frames *before* the screen
does, and pokered seeds its RNG from `rDIV` (`Random_` reads `$ff04`). Cause established, not
assumed.

For the serial case this is a feature: the cycles being skipped are a hardware busy-wait that
would otherwise never terminate.

## Symbols

**Build them.** pokered is byte-perfect, and this was confirmed rather than trusted: the ROM built
here at the pinned revision has md5 `3d45c1ee9abd5738df46d2bdda8b57dc`, **identical** to
`roms/pokered.gb`. Symbol addresses from that build are therefore valid for the retail ROM by
construction.

```bash
# rgbds v1.0.3 — the version pokered's own CI pins (.github/workflows/main.yml)
git clone --branch v1.0.3 --depth 1 https://github.com/gbdev/rgbds.git
make -C rgbds -j"$(nproc)"                  # needs g++ (C++20), bison, flex, pkg-config, libpng-dev

git clone https://github.com/pret/pokered.git
git -C pokered checkout a1a22aaf84d1675bcdbaeb194592379d586d838e
PATH="$PWD/rgbds:$PATH" make -C pokered red -j"$(nproc)"
md5sum pokered/pokered.gbc                  # expect 3d45c1ee9abd5738df46d2bdda8b57dc

# rgbds 1.0.3 also writes exported constants with no address; PyBoy logs a
# warning for each of the ~900 of them. Keep only the address lines:
grep -E '^[0-9A-Fa-f]{2}:[0-9A-Fa-f]{4} ' pokered/pokered.sym > pokered.gb.sym
```

Total build time here was under two minutes. Note the output ROM is named `pokered.gbc` despite
being a DMG ROM; that is upstream's naming.

Then `PyBoy(rom, symbols="pokered.gb.sym")` resolves names in `hook_register(None, "Name", ...)`
and `symbol_lookup`. Verified working for bank 0 (`Serial_ExchangeByte` → `00:219a`) and for
banked symbols (`MainMenu` → `01:5af2`).

**Symbols are a convenience, not a dependency.** `tools/link_spike.py` runs without a `.sym` file
at all, using hard-coded addresses validated directly against the ROM image:

```
bytes at 00:219a: af e0 a9 f0 aa fe 02   = xor a / ldh [$ffa9],a / ldh a,[$ffaa] / cp 2
bytes at 00:2176: cd 9a 21               = call $219a
```

which is exactly the head of `Serial_ExchangeByte` in `home/serial.asm` and the call to it inside
`Serial_ExchangeBytes`. When a `.sym` *is* supplied the spike cross-checks it against these
constants and refuses to run if they disagree.

Useful addresses, all bank 0:

| symbol | address |
|---|---|
| `Serial` (the serial interrupt handler) | `2125` |
| `Serial_ExchangeBytes` | `216f` |
| `Serial_ExchangeByte` | `219a` |
| `Serial_ExchangeNybble` | `22c3` |
| `Serial_TryEstablishingExternallyClockedConnection` | `22fa` |
| `hSerialReceivedNewData` | `ffa9` |
| `hSerialConnectionStatus` | `ffaa` |
| `hSerialIgnoringInitialData` | `ffab` |
| `hSerialSendData` | `ffac` |
| `hSerialReceiveData` | `ffad` |

## What was proved

1. The callback fires, and it fires *before* the hooked instruction, with `SP` pointing at the
   caller's return address (verified: the popped address was always `0xc007`, the instruction
   after the planted `call`).
2. Writing `A` from Python is observed by ROM code.
3. A routine can be made to return early without executing its body, and the program keeps running
   — proved three independent ways (instruction-level hook count, a RAM witness incremented by the
   body, and the caller's own progress counter).
4. `SP`, `PC`, `A`, `B`, `C`, `D`, `E`, `F` and `HL` writes all behave; `F` masks to the high
   nibble as the Game Boy does.
5. Hooks work in ROM bank 0, in banked ROM, and in work RAM.
6. An observe-only hook perturbs nothing, bit-exact, over 600 frames and 4 480 hits.
7. Two PyBoy instances in one process rendezvous through hooks with no threads, and the blocked
   side is genuinely just not ticked.
8. The real `Serial_ExchangeByte` hangs forever without interception and works with it.
9. The real `Serial_ExchangeBytes` completes a block transfer between two instances, with the
   ROM's own preamble skipping behaving as written.
10. pokered at `a1a22aaf` builds to a ROM byte-identical to `roms/pokered.gb`.

## What was *not* proved

- **The hook was never reached through gameplay.** With a cold boot and 3 000 frames of button
  mashing the game reaches `MainMenu` and `StartNewGame`, and `Serial`, `Serial_ExchangeByte`,
  `Serial_ExchangeBytes`, `Serial_SyncAndExchangeNybble` and
  `Serial_TryEstablishingExternallyClockedConnection` all fire **zero** times. Reaching them needs
  a save, a Pokémon Center, the Cable Club attendant and the trade table. Every demonstration here
  therefore calls the routine from a small program planted in work RAM, with the same calling
  convention the ROM uses. The routine is real, the caller is ours.
- **Link establishment was not exercised.** `Serial_ExchangeByte` is the inner loop, but before it
  runs, both sides negotiate a clock through the `Serial` interrupt handler and
  `Serial_TryEstablishingExternallyClockedConnection`, and `hSerialConnectionStatus` must end up
  set (`$01` external / `$02` internal). Those paths spin on hardware too and will each need their
  own interception or a direct write to `hSerialConnectionStatus`. Unproven, and the largest
  remaining unknown.
- **`Serial_SyncAndExchangeNybble`** — used for the link menu and trade-menu selections — was not
  touched. It calls `Serial_ExchangeByte` underneath, so it should fall out, but "should" is not
  "did".
- **No actual trade happened.** No Pokémon changed hands, no trade evolution fired, no save was
  written. This spike proves the transport, not the trade.
- **Long-run stability.** The longest run was 600 frames. Nothing suggests a leak — hooks are
  re-injected by PyBoy itself after each hit — but it has not been run for an hour.

## Remaining risks

| risk | severity | note |
|---|---|---|
| Link establishment cannot be intercepted as cleanly | high | `Serial`'s body is an interrupt handler, not a `call`ed routine, so `force_return` does not apply to it. Likeliest fix: intercept `Serial_TryEstablishingExternallyClockedConnection` and write `hSerialConnectionStatus` directly rather than emulating the handshake. Needs its own spike. |
| Cable Club policy work | high | Unchanged from `docs/multi-game.md`: both runs must walk into a Pokémon Center, talk to the attendant, sit down and work the trade menus in sync. This is the real cost of backend B and this spike does nothing to reduce it. |
| Timing divergence from skipped cycles | low | Established as the cause of the only divergence seen. Irrelevant for serial, where the skipped cycles are a busy-wait. |
| Frame-granular `tick()` | low | Handled by the stall/park path. Costs emulated CPU, not correctness. |
| Hooked address is data, not code | low | PyBoy's own warning: the `0xDB` byte is readable. Not a concern for `219a`, which nothing reads. |
| PyBoy pin | none | Nothing here needs a newer PyBoy, and everything used is public API: `hook_register`, `register_file`, `memory`, `symbol_lookup`, `tick`. |

## Recommendation

**GO.** The mechanism the design doc called "unproven" is now proven, and the strongest form of it
— two emulators completing a real block transfer through the game's own serial code — works
first-class. The `hook_register` + `register_file` + `memory` trio is sufficient; the PyBoy pin
stays intact; no serial hardware needs emulating.

Two caveats on the decision. First, the remaining transport unknown is link *establishment*, not
byte exchange, and it should get a short follow-up spike before milestone 5 is scheduled, because
the interrupt handler does not yield to the same technique. Second, and more important, the
transport was never the expensive half. Backend B still costs the Cable Club policy work, and
milestones 2 and 3 deliver the outcome without it. This result says backend B is *possible*; it
does not say it is next.
