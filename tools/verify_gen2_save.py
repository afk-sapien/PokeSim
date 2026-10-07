"""Verify a late-campaign portable save after dismissing the ending credits."""
import argparse
import io
import os
from pathlib import Path

from pokesim.gen2.core import boot

from pokesim.gen2.data import GameData
from pokesim.gen2.ram import read_snapshot
from pokesim.gen2.save import export_with_clock, press


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom', type=Path)
    parser.add_argument('state', type=Path)
    parser.add_argument('--game', required=True, choices=('gold', 'silver', 'crystal'))
    parser.add_argument('--data', type=Path, default=Path(os.environ.get('GEN2_DATA_DIR', '.release-local/gen2-data')))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = GameData.load(args.data, args.game)
    pb = boot(str(args.rom), sound=True)
    pb.set_emulation_speed(0)
    try:
        pb.load_state(io.BytesIO(args.state.read_bytes()))
        for step in range(1000):
            press(pb, 'start' if step % 3 == 0 else 'a', 60)
            snapshot = read_snapshot(pb.memory, data)
            if snapshot.map == data.map_ids['SILVER_CAVE_OUTSIDE'] and '┌' not in snapshot.tiles[12]:
                break
        else:
            raise AssertionError('The ending did not return the trainer to Mt. Silver')
        press(pb, wait=120)
        state = io.BytesIO()
        pb.save_state(state)
        save, clock = export_with_clock(args.rom, state.getvalue(), data)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(save)
        args.output.with_suffix('.rtc').write_bytes(clock)
        print(f'{args.game}: {len(save)} bytes and {len(clock)} clock bytes verified by a fresh cartridge Continue with its clock')
    finally:
        pb.stop(save=False)


if __name__ == '__main__':
    main()
