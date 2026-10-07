"""Boot owner-supplied Gen II ROMs and check input, observation and checkpoints.

Run with python -m tools.probe_gen2 ROM_OR_ZIP ... --output NEW_DIRECTORY.
This experiment never starts the Red/Blue adventure runtime.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import tempfile

from pokesim.experimental.gen2 import load_rom, read_snapshot


def ram_digest(pb):
    """Hash fixed WRAM and bank 1, independent of the bank selected by the CPU."""
    raw = bytearray()
    for bank in (0, 1):
        # Upstream PyBoy 2.7.0 rejected a banked slice ending exactly at the bank boundary.
        start = 0xC000 + bank * 0x1000
        raw.extend(pb.memory[bank, start:start + 0xFFF])
        raw.append(pb.memory[bank, start + 0xFFF])
    return hashlib.sha256(raw).hexdigest()


def probe(source: Path, output: Path) -> dict:
    from pokesim.gen2.core import boot, lock_clock
    from pokesim_core.emulator_state import runtime_provenance
    profile, raw = load_rom(source)
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='pokesim-gen2-') as temporary:
        rom = Path(temporary) / 'probe.gbc'
        rom.write_bytes(raw)

        def start():
            pb = boot(str(rom), sound=True)
            # Set before the first tick so a test's clock cannot move backwards.
            lock_clock(pb, True)
            return pb

        def tap(pb, button, frames):
            # Core exposes press/release only; hold for the requested frames.
            pb.press(button)
            pb.tick(frames, True)
            pb.release(button)

        def walk(pb):
            tap(pb, 'right', 16)
            pb.tick(60, True)
            return read_snapshot(pb.memory, profile), ram_digest(pb), pb.screen.image.tobytes()

        pb = start()
        try:
            pb.tick(1200, True)
            pb.screen.image.save(output / 'opening.png')
            tap(pb, 'start', 8)
            pb.tick(120, True)
            # Bounded input replay for the English opening, not a general policy.
            for _ in range(110):
                tap(pb, 'a', 8)
                pb.tick(60, True)
            before = read_snapshot(pb.memory, profile)
            if (before.map_group, before.map_number, before.x, before.y) != (24, 7, 3, 3):
                pb.screen.image.save(output / 'failure.png')
                raise RuntimeError(f'Opening did not reach the bedroom: {before}')
            pb.screen.image.save(output / 'bedroom.png')
            checkpoint = io.BytesIO()
            pb.save_state(checkpoint)
            state = checkpoint.getvalue()
            (output / 'bedroom.state').write_bytes(state)
            before_ram = ram_digest(pb)
            after, after_ram, after_pixels = walk(pb)
            if (after.map_group, after.map_number, after.x, after.y) != (24, 7, 4, 3):
                raise RuntimeError(f'Right input did not move one tile: {after}')
            pb.screen.image.save(output / 'walk.png')
            pb.load_state(io.BytesIO(state))
            if read_snapshot(pb.memory, profile) != before or ram_digest(pb) != before_ram:
                raise RuntimeError('Checkpoint failed to restore observed state and WRAM')
            if walk(pb) != (after, after_ram, after_pixels):
                raise RuntimeError('Checkpoint replay diverged')
            title = pb.cartridge_title
        finally:
            pb.stop(save=False)

        restored = boot()
        try:
            restored.load_state(io.BytesIO(state))
            if read_snapshot(restored.memory, profile) != before or ram_digest(restored) != before_ram:
                raise RuntimeError('Fresh emulator did not restore the checkpoint')
            if walk(restored) != (after, after_ram, after_pixels):
                raise RuntimeError('Fresh emulator checkpoint replay diverged')
        finally:
            restored.stop(save=False)

    result = {
        'game': profile.game, 'revision': profile.revision, 'sha1': profile.sha1,
        'cartridge_title': title, 'emulator': dict(runtime_provenance()),
        'mode': 'CGB', 'rtc': 'locked before first tick', 'opening_frames': 7920,
        'checks': {'bedroom_reached': True, 'walked_one_tile': True,
                   'checkpoint_restores_wram': True, 'checkpoint_replays_pixels_and_wram': True,
                   'fresh_emulator_replays_pixels_and_wram': True},
        'before_walk': asdict(before), 'after_walk': asdict(after),
        'checkpoint_bytes': len(state), 'production_support': False,
    }
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('roms', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True, help='New output directory')
    args = parser.parse_args(argv)
    # Validate all inputs before starting any emulator or creating output.
    profiles = [load_rom(path)[0] for path in args.roms]
    if len({profile.game for profile in profiles}) != len(profiles):
        parser.error('Supply each game only once')
    args.output.mkdir(parents=True, exist_ok=False)
    reports = []
    for source, profile in zip(args.roms, profiles):
        report = probe(source, args.output / profile.game)
        reports.append(report)
        print(f'{profile.game}: bedroom, movement and both checkpoint replays passed', flush=True)
    (args.output / 'report.json').write_text(json.dumps(reports, indent=2) + '\n')


if __name__ == '__main__':
    main()
