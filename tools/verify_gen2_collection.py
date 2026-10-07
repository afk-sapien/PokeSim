"""Verify all 251 native Pokédex entries and a portable save after fresh Continue."""
import argparse
import hashlib
import io
import json
from pathlib import Path

from pyboy import PyBoy

from pokesim.gen2.data import GameData
from pokesim.gen2.ram import read_snapshot
from pokesim.gen2.save import export


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom', type=Path)
    parser.add_argument('state', type=Path)
    parser.add_argument('--game', required=True, choices=('gold', 'silver', 'crystal'))
    parser.add_argument('--data', type=Path, default=Path('.release-local/gen2-data'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = GameData.load(args.data, args.game)
    raw = args.state.read_bytes()
    pb = PyBoy(str(args.rom), window='null', cgb=True, ram_file=io.BytesIO(bytes(32768)))
    try:
        pb.load_state(io.BytesIO(raw))
        snapshot = read_snapshot(pb.memory, data)
        missing = sorted(set(range(1, 252)) - snapshot.owned)
        if missing:
            raise ValueError(f'The cartridge still lacks {len(missing)} entries: {missing}')
        if not snapshot.valid or len(snapshot.owned) != 251:
            raise ValueError('The cartridge snapshot is not a valid complete Pokédex')
        result = {'game': args.game, 'source': str(args.state.resolve()),
            'checkpoint_sha256': hashlib.sha256(raw).hexdigest(),
            'owned': sorted(snapshot.owned), 'owned_count': len(snapshot.owned),
            'badges': snapshot.badges, 'hall_of_fame_count': snapshot.hall_of_fame_count,
            'physical_species': sorted({mon.species for mon in snapshot.party + snapshot.stored if not mon.egg})}
    finally:
        pb.stop(save=False)
    save = export(args.rom, raw, data)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / f'{args.game}-251.sav').write_bytes(save)
    result.update(portable_save_bytes=len(save), portable_save_sha256=hashlib.sha256(save).hexdigest(),
                  fresh_continue_verified=True)
    (args.output / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'{args.game}: all 251 entries verified, including fresh cartridge Continue')


if __name__ == '__main__':
    main()
