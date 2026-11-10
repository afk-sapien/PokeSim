"""Exercise sequence resume, replay and profiling through the Core API.

Uses the redistributable demo by default. External ROMs and saves stay local.
Run with the experimental Core and PyBoy RS packages installed.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

from pokecore.emulator import Emulator, demo_rom


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--frames', type=int, default=6000)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--audio', action='store_true')
    args = parser.parse_args()
    if args.frames < 2:
        parser.error('--frames must be at least 2')
    source = args.rom if args.rom is not None else demo_rom()
    with Emulator(source) as emulator, Emulator(source) as resumed, Emulator(source) as replayed:
        if args.state is not None:
            emulator.load(args.state.read_bytes())
        else:
            emulator.tick(90)
        emulator.start_sequence([(('a',), 1), ((), args.frames - 1)])
        initial = emulator.checkpoint()
        started = time.perf_counter()
        emulator.run_sequence(args.frames, render=args.render, sound=args.audio)
        ordinary_seconds = time.perf_counter() - started
        expected = emulator.checkpoint()
        emulator.restore_checkpoint(initial)
        emulator.start_recording(max_frames=args.frames)
        emulator.run_sequence(args.frames // 2, render=args.render, sound=args.audio)
        midpoint = emulator.checkpoint()
        resumed.restore_checkpoint(midpoint)
        emulator.run_sequence(args.frames, render=args.render, sound=args.audio)
        resumed.run_sequence(args.frames, render=args.render, sound=args.audio)
        recording = emulator.stop_recording()
        assert resumed.checkpoint() == emulator.checkpoint() == expected
        replay = replayed.replay(recording)
        assert replayed.checkpoint() == expected
        emulator.restore_checkpoint(initial)
        emulator.start_profiling()
        started = time.perf_counter()
        emulator.run_sequence(args.frames, render=args.render, sound=args.audio)
        profile_seconds = time.perf_counter() - started
        counters = emulator.stop_profiling()
        assert emulator.checkpoint() == expected
        print(json.dumps({'frames': args.frames, 'resume_verified': True, 'replay': replay,
                          'state_sha256': hashlib.sha256(emulator.save()).hexdigest(),
                          'ordinary_seconds': ordinary_seconds, 'profile_seconds': profile_seconds,
                          'profile': counters}, indent=2))


if __name__ == '__main__':
    main()
