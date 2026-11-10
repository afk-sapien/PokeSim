"""Measure Core overhead and differential gameplay in isolated worker processes.

PyBoy and direct PyBoy RS imports are development references only. All public
application code uses Core. Inputs are held for 12 frames and released for 12.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

BUTTONS = ("right", "down", "left", "up", "a", "a", "b", "a")


def worker(args):
    if args.backend == "core":
        from pokecore.emulator import Emulator
    elif args.backend == "rust":
        from pyboy_rs import PyBoy as Emulator
    else:
        from pyboy import PyBoy as Emulator
    game = Emulator(io.BytesIO(args.rom.read_bytes()), window="null", sound_emulated=True)
    game.set_emulation_speed(0)
    state = args.states[0].read_bytes()
    game.load_state(io.BytesIO(state))
    game.tick(120, True, True)
    game.load_state(io.BytesIO(state))
    trace = bytearray()
    start = time.perf_counter()
    for chunk in range(args.frames // 24):
        button = BUTTONS[chunk % len(BUTTONS)]
        game.button_press(button)
        for pressed in (True, False):
            if not pressed:
                game.button_release(button)
            if args.mode == "batch":
                game.tick(12, False, False)
            else:
                for _ in range(12):
                    game.tick(1, True, True)
        trace.extend(game.memory[a] for a in (0xd35e, 0xd361, 0xd362, 0xd057))
    seconds = time.perf_counter() - start
    saved = io.BytesIO()
    game.save_state(saved)
    outputs = {"state": saved.getvalue(), "trace": trace}
    if args.mode == "audio":
        outputs.update(rgba=bytes(game.screen.raw_buffer),
                       audio=bytes(game.sound.raw_buffer[:game.sound.raw_buffer_head]))
    game.stop(save=False)
    print(json.dumps({"seconds": seconds, "hashes": {k: hashlib.sha256(v).hexdigest() for k, v in outputs.items()}}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--states", type=Path, nargs="+", required=True)
    parser.add_argument("--frames", type=int, default=4800)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--cpu", type=int, default=min(os.sched_getaffinity(0)))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--backend", choices=("core", "rust", "pyboy"))
    parser.add_argument("--mode", choices=("batch", "audio"), default="audio")
    args = parser.parse_args()
    if args.frames <= 0 or args.frames % 24 or args.repeats < 1:
        parser.error("Use a positive multiple of 24 frames and positive repeats")
    os.sched_setaffinity(0, {args.cpu})
    if args.backend:
        worker(args)
        return
    if not args.output:
        parser.error("--output is required")
    from pokecore.emulator_state import runtime_provenance
    from importlib.metadata import version
    jobs = [(state, mode, backend, repeat) for state in args.states for mode in ("batch", "audio")
            for backend in ("core", "rust", "pyboy") for repeat in range(args.repeats)]
    random.Random(20261006).shuffle(jobs)
    rows, expected = [], {}
    for state, mode, backend, repeat in jobs:
        result = subprocess.run([sys.executable, __file__, "--rom", str(args.rom), "--states", str(state),
            "--frames", str(args.frames), "--cpu", str(args.cpu), "--backend", backend, "--mode", mode],
            capture_output=True, text=True, check=True)
        result = json.loads(result.stdout)
        assert result["hashes"] == expected.setdefault((state.stem, mode), result["hashes"]), (state.stem, mode, backend)
        rows.append({"scenario": state.stem, "mode": mode, "backend": backend, "repeat": repeat, **result})
    summary = []
    for state in args.states:
        for mode in ("batch", "audio"):
            for backend in ("core", "rust", "pyboy"):
                samples = [r["seconds"] for r in rows if (r["scenario"], r["mode"], r["backend"]) == (state.stem, mode, backend)]
                summary.append({"scenario": state.stem, "mode": mode, "backend": backend,
                                "median_seconds": statistics.median(samples), "min_seconds": min(samples),
                                "max_seconds": max(samples), "fps": args.frames / statistics.median(samples)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"frames": args.frames, "repeats": args.repeats, "cpu": args.cpu,
        "rom_sha256": hashlib.sha256(args.rom.read_bytes()).hexdigest(), "emulator": runtime_provenance(),
        "core_version": version("pokecore"), "reference_version": version("pyboy"),
        "checkpoints": [{"label": p.stem, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in args.states],
        "all_outputs_match": True, "samples": rows, "summary": summary}, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
