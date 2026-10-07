"""Import missing entries through verified native exchanges between Gen II saves."""
import argparse
import json
from pathlib import Path

from collect_gen2_imports import inspect_modern, run
from pokesim.gen2.data import GameData


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--donor-game', required=True, choices=('gold', 'silver', 'crystal'))
    parser.add_argument('--donor-state', required=True, type=Path)
    parser.add_argument('--game', default='crystal', choices=('gold', 'silver', 'crystal'))
    parser.add_argument('--load', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--data', default=Path('.release-local/all-data'), type=Path)
    parser.add_argument('--offer-trained', action='store_true')
    args = parser.parse_args()
    data = GameData.load(args.data, args.game)
    donor_data = GameData.load(args.data, args.donor_game)
    rom = Path(f'.release-local/gen2/{args.game}.gbc')
    donor_rom = Path(f'.release-local/gen2/{args.donor_game}.gbc')
    args.output.mkdir(parents=True, exist_ok=True)
    cursor = args.output / 'progress.json'
    progress = json.loads(cursor.read_text()) if cursor.exists() else {
        'donor': str(args.donor_state.resolve()), 'modern': str(args.load.resolve()), 'trades': []}
    while True:
        donor, modern = Path(progress['donor']), Path(progress['modern'])
        _, donors = inspect_modern(donor_rom, donor, donor_data, offer_trained=args.offer_trained)
        owned, offered = inspect_modern(rom, modern, data)
        choices = [row for row in donors if {row['species'], row['arrived_dex']} - owned]
        if not choices or not offered:
            progress['remaining'] = sorted(set(range(1, 252)) - owned)
            progress['reason'] = 'No missing donor available' if not choices else 'No boxed return partner available'
            cursor.write_text(json.dumps(progress, indent=2))
            print(progress['reason'], progress['remaining'], flush=True)
            break
        incoming = min(choices, key=lambda row: (row['species'], row['level']))
        parents = {25, 35, 39, 41, 43, 60, 61, 79, 95, 106, 107, 113, 117, 123, 124, 125, 126, 132, 133, 137}
        outgoing = min(offered, key=lambda row: (row['last_copy'], row['species'] in parents,
            any(evo['species'] not in owned for evo in data.species[row['species']]['evolutions']),
            row['level'], row['species']))
        species = incoming['species']
        directory = args.output / f'{len(progress["trades"]) + 1:03d}-{species:03d}'
        directory.mkdir(exist_ok=True)
        print('Import', species, data.species[species]['name'], 'owned', len(owned), flush=True)
        for side, game, source, selected in (
                ('donor', args.donor_game, donor, incoming), ('modern', args.game, modern, outgoing)):
            if not (directory / side / 'receipt.json').exists():
                run(['tools/verify_gen2_trading.py', '--game', game, '--load', source,
                     '--species', selected['species'], '--trade-key', selected['trade_key'], '--output', directory / side,
                     *(['--offer-trained'] if side == 'donor' and args.offer_trained else [])], directory / f'{side}.log')
        if not all((directory / side / 'adopted.state').exists() for side in ('donor', 'modern')):
            run(['tools/verify_gen2_exchange.py', directory / 'donor', directory / 'modern',
                 '--data', args.data], directory / 'exchange.log')
        result = directory / 'modern/adopted.state'
        after, _ = inspect_modern(rom, result, data)
        if not owned < after or not {species, incoming['arrived_dex']} <= after:
            raise ValueError('The verified exchange did not add the requested Pokédex entries')
        progress.update(donor=str((directory / 'donor/adopted.state').resolve()),
                        modern=str(result.resolve()), owned=len(after))
        progress['trades'].append({'species': species, 'arrived': incoming['arrived_dex'],
            'returned': outgoing['species'], 'directory': str(directory.resolve()), 'owned': len(after)})
        cursor.write_text(json.dumps(progress, indent=2))
        print('Verified', species, 'owned', len(after), flush=True)


if __name__ == '__main__':
    main()
