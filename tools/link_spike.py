#!/usr/bin/env python3
"""Milestone 4 feasibility spike: intercepting a Game Boy ROM routine from Python.

This is a spike, not production code. It answers one question with running code:

    Can we intercept a ROM routine with PyBoy's supported APIs, supply a return
    value from Python, and make the routine return early without executing its
    body -- and can two PyBoy instances in one process rendezvous that way?

Nothing here is imported by pokesim. It only reads the ROM; it never writes a
save file (every PyBoy instance is stopped with ``save=False``).

Run with the project interpreter, which is where PyBoy 2.7 lives::

    /home/ty/Repos/pokesim/.venv/bin/python tools/link_spike.py all --rom roms/pokered.gb

Stages (see ``--help``):

  mechanism     hook fires / write A / force early return, on a controlled
                routine we assemble ourselves into work RAM
  transparency  does an observe-only hook perturb the game? does an
                intercepting one?
  serial        the real ``Serial_ExchangeByte`` at 00:219a in the retail ROM:
                it hangs without interception, and two instances trade bytes
                through it with interception
  block         the real ``Serial_ExchangeBytes`` block transfer, preamble
                skipping and all, driven end-to-end between two instances

``docs/link-spike.md`` records the findings.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from collections import deque
from pathlib import Path

# A raw rgbds 1.0.3 pokered.sym contains lines PyBoy cannot parse (exported
# constants with no address). PyBoy logs one warning per line -- thousands of
# them. They are harmless; quieten them unless --verbose.
logging.getLogger("pyboy.pyboy").setLevel(logging.ERROR)

try:
    from pyboy import PyBoy
except ImportError:  # pragma: no cover - spike
    sys.exit("pyboy is not importable. Use /home/ty/Repos/pokesim/.venv/bin/python")


# --------------------------------------------------------------------------
# Retail Pokemon Red facts, independently checkable against the ROM file.
# --------------------------------------------------------------------------

POKERED_MD5 = "3d45c1ee9abd5738df46d2bdda8b57dc"

# home/serial.asm, pinned revision a1a22aaf84d1675bcdbaeb194592379d586d838e.
SERIAL_EXCHANGE_BYTE = 0x219A
SERIAL_EXCHANGE_BYTES = 0x216F
H_SERIAL_SEND_DATA = 0xFFAC
H_SERIAL_RECEIVE_DATA = 0xFFAD

# First instructions of Serial_ExchangeByte:
#   af        xor a
#   e0 a9     ldh [hSerialReceivedNewData], a
#   f0 aa     ldh a, [hSerialConnectionStatus]
#   fe 02     cp USING_INTERNAL_CLOCK
SERIAL_EXCHANGE_BYTE_SIGNATURE = bytes([0xAF, 0xE0, 0xA9, 0xF0, 0xAA, 0xFE, 0x02])
# Serial_ExchangeBytes contains `call Serial_ExchangeByte` at +0x07.
SERIAL_EXCHANGE_BYTES_CALL = bytes([0xCD, 0x9A, 0x21])

SERIAL_PREAMBLE_BYTE = 0xFD


# --------------------------------------------------------------------------
# The technique.
# --------------------------------------------------------------------------


def force_return(pyboy, value=None):
    """Make the currently-hooked routine return immediately, as if by ``ret``.

    Must be called from a hook installed on the routine's **first** instruction,
    where the only thing the routine has pushed is the return address left by
    the caller's ``call``.

    PyBoy stops the CPU *before* executing the hooked instruction, so PC is the
    hook address and SP points at the return address. Emulating `ret` by hand is
    therefore exactly:

        pop the two bytes at SP into PC, and add 2 to SP

    Optionally set A first: Gen I returns single bytes in A.
    """
    rf = pyboy.register_file
    mem = pyboy.memory
    sp = rf.SP
    ret_addr = mem[sp] | (mem[sp + 1] << 8)
    rf.SP = (sp + 2) & 0xFFFF
    rf.PC = ret_addr
    if value is not None:
        rf.A = value & 0xFF
    return ret_addr


def rewind_call(pyboy, entry):
    """Un-execute the ``call`` that led here, so the routine is entered again.

    The "not ready yet" counterpart to `force_return`: pops the return address
    and points PC back at the 3-byte ``call`` instruction that pushed it. The
    routine's body still never runs. Validates that the call site really is
    ``call <entry>`` before touching anything.

    Returns the address of the call instruction.
    """
    rf = pyboy.register_file
    mem = pyboy.memory
    sp = rf.SP
    ret_addr = mem[sp] | (mem[sp + 1] << 8)
    call_site = (ret_addr - 3) & 0xFFFF
    opcode = mem[call_site]
    target = mem[call_site + 1] | (mem[call_site + 2] << 8)
    if opcode != 0xCD or target != entry:
        raise RuntimeError(
            f"call site at {call_site:#06x} is not `call {entry:#06x}` "
            f"(opcode {opcode:#04x}, target {target:#06x})"
        )
    rf.SP = (sp + 2) & 0xFFFF
    rf.PC = call_site
    return call_site


# --------------------------------------------------------------------------
# Small assembler-by-hand helpers. We plant Game Boy machine code into work RAM
# (0xC000-0xDFFF) and point PC at it. PyBoy supports hooks in work RAM too, so
# both the caller and the callee can be ours when we want a controlled target.
# --------------------------------------------------------------------------


def plant(pyboy, program):
    """program: {address: [bytes]}"""
    for addr, blob in program.items():
        for i, byte in enumerate(blob):
            pyboy.memory[addr + i] = byte


def boot(rom, symbols=None, frames=60):
    pyboy = PyBoy(str(rom), window="null", symbols=symbols, sound_emulated=False)
    pyboy.set_emulation_speed(0)
    pyboy.tick(frames, False)
    return pyboy


def screen_hash(pyboy):
    return hashlib.sha1(bytes(pyboy.screen.ndarray)).digest()


def ok(flag):
    return "PASS" if flag else "FAIL"


# --------------------------------------------------------------------------
# Stage 1 -- the mechanism, on a routine we control completely.
# --------------------------------------------------------------------------

# 0xC000  f3            di                  ; keep the game's interrupts out of our RAM
# 0xC001  31 fe cf      ld sp, $cffe
# 0xC004  cd 40 c0      call $c040          ; <- the routine we hook
# 0xC007  ea 20 c0      ld [$c020], a       ; the caller records what came back in A
# 0xC00a  21 21 c0      ld hl, $c021
# 0xC00d  34            inc [hl]            ; ... and that it is still running
# 0xC00e  18 f4         jr $c004
#
# 0xC040  21 22 c0      ld hl, $c022        ; the routine body
# 0xC043  34            inc [hl]            ; "the body executed" witness
# 0xC044  3e 99         ld a, $99           ; the body's own return value
# 0xC046  c9            ret
MECHANISM_PROGRAM = {
    0xC000: [0xF3],
    0xC001: [0x31, 0xFE, 0xCF],
    0xC004: [0xCD, 0x40, 0xC0],
    0xC007: [0xEA, 0x20, 0xC0],
    0xC00A: [0x21, 0x21, 0xC0],
    0xC00D: [0x34],
    0xC00E: [0x18, 0xF4],
    0xC040: [0x21, 0x22, 0xC0],
    0xC043: [0x34],
    0xC044: [0x3E, 0x99],
    0xC046: [0xC9],
}
MECH_ENTRY, MECH_BODY, MECH_RET = 0xC040, 0xC043, 0xC046
MECH_RETURNED_A, MECH_ITERS, MECH_BODY_RUNS = 0xC020, 0xC021, 0xC022
INJECTED_A = 0x42


def stage_mechanism(args):
    print("STAGE 1: does the hook fire, can we write A, can we force an early return?")
    print("  Target: a 4-instruction routine assembled into work RAM at 0xc040.")
    print("  It returns 0x99 in A. We try to make it return 0x42 without running.\n")

    def run(mode):
        pyboy = boot(args.rom)
        plant(pyboy, MECHANISM_PROGRAM)
        for addr in (MECH_RETURNED_A, MECH_ITERS, MECH_BODY_RUNS):
            pyboy.memory[addr] = 0
        counts = {"entry": 0, "body": 0, "ret": 0}
        ret_addrs = set()

        def on_entry(_):
            counts["entry"] += 1
            sp = pyboy.register_file.SP
            ret_addrs.add(pyboy.memory[sp] | (pyboy.memory[sp + 1] << 8))
            if mode == "early-return":
                force_return(pyboy, INJECTED_A)
            elif mode == "write-A-at-entry":
                pyboy.register_file.A = INJECTED_A

        def on_body(_):
            counts["body"] += 1

        def on_ret(_):
            counts["ret"] += 1
            if mode == "write-A-at-ret":
                pyboy.register_file.A = INJECTED_A

        pyboy.hook_register(0, MECH_ENTRY, on_entry, None)
        pyboy.hook_register(0, MECH_BODY, on_body, None)
        pyboy.hook_register(0, MECH_RET, on_ret, None)
        pyboy.register_file.PC = 0xC000
        pyboy.tick(args.frames, False)
        result = {
            "calls": counts["entry"],
            "body_hook": counts["body"],
            "returned_A": pyboy.memory[MECH_RETURNED_A],
            "iters_mod256": pyboy.memory[MECH_ITERS],
            "body_runs_mod256": pyboy.memory[MECH_BODY_RUNS],
            "ret_addrs": sorted(ret_addrs),
        }
        pyboy.stop(save=False)
        return result

    rows = {m: run(m) for m in
            ("control", "write-A-at-entry", "write-A-at-ret", "early-return")}

    print(f"  {'mode':18s} {'calls':>7s} {'body hook':>10s} {'A seen by caller':>17s} "
          f"{'caller iters':>13s}")
    for mode, r in rows.items():
        print(f"  {mode:18s} {r['calls']:7d} {r['body_hook']:10d} "
              f"{r['returned_A']:#17x} {r['iters_mod256']:13d}")
    print("  (caller iters is an 8-bit counter in RAM, so it is calls mod 256)")
    print()

    checks = [
        ("(a) the callback fires", rows["control"]["calls"] > 0),
        ("(a) PyBoy stops before the instruction: SP holds the call's return address",
         rows["control"]["ret_addrs"] == [0xC007]),
        ("(b) writing A at the routine's `ret` is observed by the caller",
         rows["write-A-at-ret"]["returned_A"] == INJECTED_A),
        ("(b) writing A at the routine's entry is overwritten by the body (expected)",
         rows["write-A-at-entry"]["returned_A"] == 0x99),
        ("(c) forced early return delivers our A to the caller",
         rows["early-return"]["returned_A"] == INJECTED_A),
        ("(c) forced early return never executes the body (hook count 0)",
         rows["early-return"]["body_hook"] == 0),
        ("(c) forced early return never executes the body (RAM witness 0)",
         rows["early-return"]["body_runs_mod256"] == 0),
        ("(c) the program keeps running afterwards",
         rows["early-return"]["calls"] > rows["control"]["calls"]),
    ]
    return report(checks)


# --------------------------------------------------------------------------
# Stage 2 -- how much does a hook perturb the running game?
# --------------------------------------------------------------------------


def stage_transparency(args):
    print("STAGE 2: is hooking transparent? is intercepting?")
    print("  Target: CopyData (00:00b5), 'copy bc bytes from hl to de'. It loops by")
    print("  jumping back to its own entry, so the hook fires once per byte copied.")
    print("  The intercepting run does the copy in Python, reproduces the routine's")
    print("  exact end state (hl+=n, de+=n, bc=0, a=0, Z set) and returns early.\n")

    copydata = 0x00B5

    def run(mode):
        pyboy = boot(args.rom, symbols=args.symbols, frames=0)
        counts = {"hits": 0, "body": 0}

        def observe(_):
            counts["hits"] += 1

        def intercept(_):
            counts["hits"] += 1
            rf = pyboy.register_file
            mem = pyboy.memory
            hl = rf.HL
            de = (rf.D << 8) | rf.E
            bc = (rf.B << 8) | rf.C
            count = bc if bc else 0x10000
            for i in range(count):
                mem[(de + i) & 0xFFFF] = mem[(hl + i) & 0xFFFF]
            rf.HL = (hl + count) & 0xFFFF
            end_de = (de + count) & 0xFFFF
            rf.D, rf.E = end_de >> 8, end_de & 0xFF
            rf.B = rf.C = rf.A = 0
            rf.F = 0x80  # `or b` with a==b==0: Z set, N/H/C clear
            force_return(pyboy)

        def body(_):
            counts["body"] += 1

        if mode == "observe":
            pyboy.hook_register(0, copydata, observe, None)
        elif mode == "intercept":
            pyboy.hook_register(0, copydata, intercept, None)
            pyboy.hook_register(0, copydata + 1, body, None)

        screens, div, cycles = [], [], []
        for _ in range(args.frames):
            pyboy.tick(1, True)
            screens.append(screen_hash(pyboy))
            div.append(pyboy.memory[0xFF04])  # rDIV, which pokered seeds its RNG from
            cycles.append(pyboy._cycles())
        pyboy.stop(save=False)
        return counts, screens, div, cycles

    base = run("control")
    obs = run("observe")
    itc = run("intercept")

    def first_diff(a, b):
        return next((i for i in range(args.frames) if a[i] != b[i]), None)

    print(f"  control     frames={args.frames}")
    print(f"  observe     hook hits={obs[0]['hits']:6d}  "
          f"first frame whose screen differs from control: {first_diff(base[1], obs[1])}")
    print(f"  intercept   hook hits={itc[0]['hits']:6d}  "
          f"first frame whose screen differs from control: {first_diff(base[1], itc[1])}")
    print(f"              body-executed hook hits: {itc[0]['body']}")
    print(f"              first frame whose rDIV differs:  {first_diff(base[2], itc[2])}")
    print(f"              first frame whose cycle count differs: "
          f"{first_diff(base[3], itc[3])}")
    print(f"              cycle count delta after {args.frames} frames: "
          f"{itc[3][-1] - base[3][-1]:+d}")
    print()

    checks = [
        ("an observe-only hook is bit-exact transparent for the whole run",
         first_diff(base[1], obs[1]) is None and obs[0]["hits"] > 0),
        ("interception reproduced the routine exactly while it lasted "
         "(hundreds of identical frames)",
         (first_diff(base[1], itc[1]) or args.frames) > args.frames // 4),
        ("interception never executed the routine body",
         itc[0]["body"] == 0),
        ("the eventual divergence is a cycle-budget effect: cycles and rDIV "
         "diverge before the screen does",
         first_diff(base[3], itc[3]) is not None
         and first_diff(base[1], itc[1]) is not None
         and first_diff(base[3], itc[3]) <= first_diff(base[1], itc[1])),
    ]
    return report(checks)


# --------------------------------------------------------------------------
# Stage 3 and 4 -- the real thing.
# --------------------------------------------------------------------------


PARK = 0xC030  # `jr @` -- somewhere harmless to leave PC while a side is starved
DONE = 0xC081
SEND_TABLE = 0xC100
RECV_BUFFER = 0xC200

# A caller for Serial_ExchangeByte, written the way Serial_ExchangeBytes writes
# one: put the byte in hSerialSendData, call, store the byte that comes back.
#
# 0xC000  f3            di
# 0xC001  31 fe cf      ld sp, $cffe
# 0xC004  21 00 c1      ld hl, $c100        ; bytes to send
# 0xC007  11 00 c2      ld de, $c200        ; where to put what we receive
# 0xC00a  06 nn         ld b, count
# 0xC00c  7e            ld a, [hl]
# 0xC00d  e0 ac         ldh [hSerialSendData], a
# 0xC00f  cd 9a 21      call Serial_ExchangeByte      ; the real routine in bank 0
# 0xC012  12            ld [de], a
# 0xC013  23            inc hl
# 0xC014  13            inc de
# 0xC015  05            dec b
# 0xC016  20 f4         jr nz, $c00c
# 0xC018  3e aa         ld a, $aa
# 0xC01a  ea 81 c0      ld [$c081], a       ; done flag
# 0xC01d  18 fe         jr $c01d
def byte_caller(count):
    return {
        0xC000: [0xF3],
        0xC001: [0x31, 0xFE, 0xCF],
        0xC004: [0x21, 0x00, 0xC1],
        0xC007: [0x11, 0x00, 0xC2],
        0xC00A: [0x06, count],
        0xC00C: [0x7E],
        0xC00D: [0xE0, H_SERIAL_SEND_DATA & 0xFF],
        0xC00F: [0xCD, SERIAL_EXCHANGE_BYTE & 0xFF, SERIAL_EXCHANGE_BYTE >> 8],
        0xC012: [0x12],
        0xC013: [0x23],
        0xC014: [0x13],
        0xC015: [0x05],
        0xC016: [0x20, 0xF4],
        0xC018: [0x3E, 0xAA],
        0xC01A: [0xEA, 0x81, 0xC0],
        0xC01D: [0x18, 0xFE],
        PARK: [0x18, 0xFE],
    }


# The same, but handing the whole block to the ROM's own Serial_ExchangeBytes
# (hl = send, de = receive, bc = length) so the ROM drives the transfer.
def block_caller(count):
    return {
        0xC000: [0xF3],
        0xC001: [0x31, 0xFE, 0xCF],
        0xC004: [0x21, 0x00, 0xC1],
        0xC007: [0x11, 0x00, 0xC2],
        0xC00A: [0x01, count & 0xFF, count >> 8],
        0xC00D: [0xCD, SERIAL_EXCHANGE_BYTES & 0xFF, SERIAL_EXCHANGE_BYTES >> 8],
        0xC010: [0x3E, 0xAA],
        0xC012: [0xEA, 0x81, 0xC0],
        0xC015: [0x18, 0xFE],
        PARK: [0x18, 0xFE],
    }


class Side:
    """One PyBoy instance, hooked at Serial_ExchangeByte, with a byte mailbox."""

    def __init__(self, name, rom, symbols, program, table, intercept=True):
        self.name = name
        self.table = list(table)
        self.pyboy = boot(rom, symbols=symbols)
        plant(self.pyboy, program)
        for i, byte in enumerate(self.table):
            self.pyboy.memory[SEND_TABLE + i] = byte
        self.pyboy.memory[DONE] = 0
        self.inbox = deque()
        self.sent = []
        self.published = False
        self.ticking = False
        self.parked = None
        self.hits = self.stalls = self.body_hits = 0
        self.peer = None
        self.entry = SERIAL_EXCHANGE_BYTE
        if symbols:
            bank, addr = self.pyboy.symbol_lookup("Serial_ExchangeByte")
            if (bank, addr) != (0, SERIAL_EXCHANGE_BYTE):
                raise RuntimeError(
                    f"symbol file disagrees: Serial_ExchangeByte is {bank:02x}:{addr:04x}, "
                    f"expected 00:{SERIAL_EXCHANGE_BYTE:04x}"
                )
        if intercept:
            self.pyboy.hook_register(0, self.entry, self._on_exchange, None)
            self.pyboy.hook_register(0, self.entry + 1, self._on_body, None)
        self.pyboy.register_file.PC = 0xC000

    def _on_body(self, _):
        self.body_hits += 1

    def tick(self, frames=1):
        if self.parked is not None:
            self.pyboy.register_file.PC = self.parked
            self.parked = None
        self.ticking = True
        try:
            self.pyboy.tick(frames, False)
        finally:
            self.ticking = False

    @property
    def done(self):
        return self.pyboy.memory[DONE] == 0xAA

    def _on_exchange(self, _):
        """The rendezvous. Publish our byte, then get the peer's -- or stall."""
        self.hits += 1
        peer = self.peer
        if not self.published:
            byte = self.pyboy.memory[H_SERIAL_SEND_DATA]
            self.sent.append(byte)
            peer.inbox.append(byte)
            self.published = True

        # "Block" by driving the peer from inside our own callback. The peer is
        # never re-entered while it is ticking (it stalls instead), so the
        # nesting depth never exceeds two -- no threads, no clock to sync.
        depth = 0
        while not self.inbox and not peer.ticking and not peer.done and depth < 4:
            depth += 1
            peer.tick(1)

        if self.inbox:
            self.published = False
            force_return(self.pyboy, self.inbox.popleft())
        else:
            # Nothing to hand back yet. Un-execute the call and park until the
            # scheduler ticks us again. The body still never runs.
            self.stalls += 1
            call_site = rewind_call(self.pyboy, self.entry)
            self.parked = call_site
            self.pyboy.register_file.PC = PARK

    def received(self, count):
        return [self.pyboy.memory[RECV_BUFFER + i] for i in range(count)]

    def stop(self):
        self.pyboy.stop(save=False)


def validate_rom(rom):
    data = Path(rom).read_bytes()
    digest = hashlib.md5(data).hexdigest()
    sig_ok = data[SERIAL_EXCHANGE_BYTE:SERIAL_EXCHANGE_BYTE
                  + len(SERIAL_EXCHANGE_BYTE_SIGNATURE)] == SERIAL_EXCHANGE_BYTE_SIGNATURE
    call_ok = data[SERIAL_EXCHANGE_BYTES + 7:SERIAL_EXCHANGE_BYTES + 10] \
        == SERIAL_EXCHANGE_BYTES_CALL
    print(f"  ROM {rom}")
    print(f"    md5 {digest}  ({'matches' if digest == POKERED_MD5 else 'DOES NOT match'} "
          f"retail Pokemon Red {POKERED_MD5})")
    print(f"    bytes at 00:{SERIAL_EXCHANGE_BYTE:04x}: "
          f"{' '.join(f'{b:02x}' for b in data[SERIAL_EXCHANGE_BYTE:SERIAL_EXCHANGE_BYTE + 7])}"
          f"   -> xor a / ldh [$ffa9],a / ldh a,[$ffaa] / cp 2   [{ok(sig_ok)}]")
    print(f"    bytes at 00:{SERIAL_EXCHANGE_BYTES + 7:04x}: "
          f"{' '.join(f'{b:02x}' for b in data[SERIAL_EXCHANGE_BYTES + 7:SERIAL_EXCHANGE_BYTES + 10])}"
          f"   -> call ${SERIAL_EXCHANGE_BYTE:04x}                        [{ok(call_ok)}]")
    return digest == POKERED_MD5, sig_ok, call_ok


def stage_serial(args):
    print("STAGE 3: the real Serial_ExchangeByte at 00:219a.\n")
    md5_ok, sig_ok, call_ok = validate_rom(args.rom)
    print()

    count = 8
    program = byte_caller(count)

    print("  Control: one instance, no hook, calling the real routine.")
    control = Side("control", args.rom, args.symbols, program,
                   range(0x01, 0x01 + count), intercept=False)
    control.tick(args.frames)
    control_pc = control.pyboy.register_file.PC
    control_done = control.done
    control_recv = control.received(count)
    control.stop()
    print(f"    after {args.frames} frames: done={control_done} "
          f"PC={control_pc:#06x} received={[hex(b) for b in control_recv]}")
    print("    -> the routine busy-waits inside its body forever. There is no")
    print("       serial hardware behind PyBoy, so this is the status quo.\n")

    print("  Intercepted: two instances, each hooked, trading bytes.")
    a = Side("A", args.rom, args.symbols, program, range(0x10, 0x10 + count))
    b = Side("B", args.rom, args.symbols, program, range(0xA0, 0xA0 + count))
    a.peer, b.peer = b, a
    frames = 0
    while not (a.done and b.done) and frames < args.frames:
        if not a.done:
            a.tick(1)
        if not b.done:
            b.tick(1)
        frames += 1
    a_recv, b_recv = a.received(count), b.received(count)
    print(f"    outer frames driven: {frames}   A done={a.done} B done={b.done}")
    print(f"    hook hits A/B: {a.hits}/{b.hits}   stalls A/B: {a.stalls}/{b.stalls}   "
          f"body-executed A/B: {a.body_hits}/{b.body_hits}")
    print(f"    A sent     {[hex(x) for x in a.sent]}")
    print(f"    B received {[hex(x) for x in b_recv]}")
    print(f"    B sent     {[hex(x) for x in b.sent]}")
    print(f"    A received {[hex(x) for x in a_recv]}")
    print()
    checks = [
        ("the ROM is retail Pokemon Red", md5_ok),
        ("00:219a really is Serial_ExchangeByte (opcode signature)", sig_ok and call_ok),
        ("without interception the routine never returns", not control_done),
        ("both instances completed their transfer", a.done and b.done),
        ("A received exactly what B sent", a_recv == b.table),
        ("B received exactly what A sent", b_recv == a.table),
        ("the routine body never executed on either side",
         a.body_hits == 0 and b.body_hits == 0),
    ]
    a.stop()
    b.stop()
    return report(checks)


def stage_block(args):
    print("STAGE 4: the real Serial_ExchangeBytes block transfer (00:216f).")
    print("  We hand the ROM a pointer, a destination and a length and let its own")
    print("  loop -- preamble skipping included -- drive Serial_ExchangeByte.\n")

    count = 16
    program = block_caller(count)
    # The ROM discards received bytes until it sees a preamble byte, so both
    # sides start their stream with one, exactly as the game does.
    table_a = [SERIAL_PREAMBLE_BYTE, SERIAL_PREAMBLE_BYTE] + list(range(0x10, 0x10 + 24))
    table_b = [SERIAL_PREAMBLE_BYTE, SERIAL_PREAMBLE_BYTE] + list(range(0xA0, 0xA0 + 24))
    a = Side("A", args.rom, args.symbols, program, table_a)
    b = Side("B", args.rom, args.symbols, program, table_b)
    a.peer, b.peer = b, a
    frames = 0
    while not (a.done and b.done) and frames < args.frames:
        if not a.done:
            a.tick(1)
        if not b.done:
            b.tick(1)
        frames += 1
    a_recv, b_recv = a.received(count), b.received(count)
    print(f"    outer frames driven: {frames}   A done={a.done} B done={b.done}")
    print(f"    hook hits A/B: {a.hits}/{b.hits}   stalls A/B: {a.stalls}/{b.stalls}   "
          f"body-executed A/B: {a.body_hits}/{b.body_hits}")
    print(f"    A sent     {[hex(x) for x in a.sent]}")
    print(f"    B received {[hex(x) for x in b_recv]}")
    print(f"    B sent     {[hex(x) for x in b.sent]}")
    print(f"    A received {[hex(x) for x in a_recv]}")
    print()
    # The ROM eats one preamble byte and stores the rest of the stream, so what
    # A stored is a contiguous window of what B put on the wire, and vice versa.
    def is_window(received, sent):
        blob, want = bytes(sent), bytes(received)
        return want in blob

    checks = [
        ("both instances completed the block transfer", a.done and b.done),
        ("what A stored is a contiguous run of what B sent",
         is_window(a_recv, b.sent)),
        ("what B stored is a contiguous run of what A sent",
         is_window(b_recv, a.sent)),
        ("the payload got through in order",
         a_recv[2:] == table_b[2:2 + count - 2] and b_recv[2:] == table_a[2:2 + count - 2]),
        ("Serial_ExchangeByte's body never executed on either side",
         a.body_hits == 0 and b.body_hits == 0),
    ]
    a.stop()
    b.stop()
    return report(checks)


# --------------------------------------------------------------------------


def report(checks):
    failed = 0
    for label, passed in checks:
        if not passed:
            failed += 1
        print(f"  [{ok(passed)}] {label}")
    print()
    return failed == 0


STAGES = {
    "mechanism": stage_mechanism,
    "transparency": stage_transparency,
    "serial": stage_serial,
    "block": stage_block,
}
DEFAULT_FRAMES = {"mechanism": 10, "transparency": 600, "serial": 240, "block": 240}


def main(argv=None):
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        prog="link_spike.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "stage", choices=list(STAGES) + ["all"], nargs="?", default="all",
        help="which demonstration to run (default: all)",
    )
    parser.add_argument(
        "--rom", type=Path, default=repo / "roms" / "pokered.gb",
        help="path to the retail Pokemon Red ROM (default: %(default)s)",
    )
    parser.add_argument(
        "--symbols", type=Path, default=None,
        help="optional pokered.sym; when given, symbol lookups are cross-checked "
             "against the hard-coded addresses",
    )
    parser.add_argument(
        "--frames", type=int, default=None,
        help="frame budget for the stage (each stage has its own sensible default)",
    )
    parser.add_argument("--verbose", action="store_true", help="let PyBoy log warnings")
    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger("pyboy.pyboy").setLevel(logging.WARNING)
    if not args.rom.is_file():
        parser.error(f"ROM not found: {args.rom} (pass --rom)")
    if args.symbols is not None and not args.symbols.is_file():
        parser.error(f"symbol file not found: {args.symbols}")
    args.symbols = str(args.symbols) if args.symbols else None

    stages = list(STAGES) if args.stage == "all" else [args.stage]
    chosen = args.frames
    results = {}
    for name in stages:
        args.frames = chosen if chosen is not None else DEFAULT_FRAMES[name]
        print("=" * 78)
        results[name] = STAGES[name](args)

    print("=" * 78)
    for name, passed in results.items():
        print(f"{name:14s} {ok(passed)}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
