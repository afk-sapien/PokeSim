"""Continue verified Time Capsule imports from two disposable adventure copies."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from pyboy import PyBoy


def inspect_classic(rom, state, *, offer_trained=False):
    from pokesim.ram import read_snapshot
    from pokesim.web.pokedex import live_status
    from pokesim.broker.inventory import normalise
    from pokesim.broker.routine import offers
    from pokesim.trade.preferences import apply, identity
    pb = PyBoy(str(rom), ram_file=io.BytesIO(bytes(32768)), window='null', sound_emulated=False)
    try:
        with state.open('rb') as stream:
            pb.load_state(stream)
        snapshot = read_snapshot(pb.memory, 0)
        payload = live_status(snapshot.to_dict())
        preferences = {identity(mon): {'state': 'offered'} for mon in payload['storage']['pokemon']
                       if offer_trained and tuple(mon['dvs']) != (15,) * 5}
        inventory = normalise('classic', '', apply(payload, preferences))
        return snapshot.owned, [mon.as_side() for mon in offers(inventory, True)]
    finally:
        pb.stop(save=False)


def inspect_modern(rom, state, data, *, offer_trained=False):
    from types import SimpleNamespace
    from pokesim.trade.preferences import apply, identity
    from pokesim.gen2.policy import Policy
    from pokesim.gen2.ram import read_snapshot
    from pokesim.gen2.trading import offers
    from pokesim.gen2.web import live_status
    pb = PyBoy(str(rom), ram_file=io.BytesIO(bytes(32768)), window='null', cgb=True, sound_emulated=True)
    try:
        with state.open('rb') as stream:
            pb.load_state(stream)
        snapshot = read_snapshot(pb.memory, data)
        policy = Policy(data)
        policy.load_state_dict(json.loads(state.with_suffix('.policy.json').read_text()))
        emu = SimpleNamespace(snapshot=snapshot, data=data, policy=policy)
        payload = live_status(snapshot.to_dict())
        preferences = {identity(mon): {'state': 'offered'} for mon in payload['storage']['pokemon']
                       if offer_trained and tuple(mon['dvs']) != (15,) * 5}
        return snapshot.owned, offers(emu, apply(payload, preferences))
    finally:
        pb.stop(save=False)


def run(arguments, log):
    with log.open('w') as output:
        subprocess.run([sys.executable, *map(str, arguments)], stdout=output, stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--classic-rom', type=Path, required=True)
    parser.add_argument('--classic-state', type=Path, required=True)
    parser.add_argument('--modern-state', type=Path, required=True)
    parser.add_argument('--game', default='crystal', choices=('gold', 'silver', 'crystal'))
    parser.add_argument('--data', type=Path, default=Path('.release-local/all-data'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=151)
    parser.add_argument('--offer-trained', action='store_true')
    args = parser.parse_args()
    os.environ['GAME_DATA_DIR'] = str(args.data.resolve())
    from pokesim.gen2.data import GameData
    data = GameData.load(args.data, args.game)
    rom = Path(f'.release-local/gen2/{args.game}.gbc')
    args.output.mkdir(parents=True, exist_ok=True)
    cursor = args.output / 'progress.json'
    if cursor.exists():
        progress = json.loads(cursor.read_text())
    else:
        progress = {'classic': str(args.classic_state.resolve()), 'modern': str(args.modern_state.resolve()), 'trades': []}
    for _ in range(args.limit):
        classic, modern = Path(progress['classic']), Path(progress['modern'])
        _, donors = inspect_classic(args.classic_rom, classic, offer_trained=args.offer_trained)
        owned, offered = inspect_modern(rom, modern, data)
        choices = sorted({row['dex'] for row in donors if row['dex'] not in owned}, key=lambda sid: (sid != 132, sid))
        spare = [row for row in offered if row['time_capsule_compatible']]
        if not choices or not spare:
            progress['remaining_gen1'] = sorted(set(range(1, 152)) - owned)
            progress['reason'] = 'No eligible missing donor' if not choices else 'No compatible boxed return partner'
            cursor.write_text(json.dumps(progress, indent=2))
            print(progress['reason'], progress['remaining_gen1'], flush=True)
            break
        species = choices[0]
        parents = {25, 35, 39, 41, 43, 60, 61, 79, 95, 106, 107, 113, 117, 123, 124, 125, 126, 132, 133, 137}
        outgoing = min(spare, key=lambda row: (row['species'] in parents, row['last_copy'], row['level'], row['species']))
        directory = args.output / f'{len(progress["trades"]) + 1:03d}-{species:03d}'
        directory.mkdir(exist_ok=True)
        print('Prepare import', species, data.species[species]['name'], 'owned', len(owned), flush=True)
        if not (directory / 'classic/receipt.json').exists():
            run(['tools/prepare_gen1_trade.py', '--rom', args.classic_rom, '--load', classic,
                 '--data', args.data, '--dex', species, '--output', directory / 'classic',
                 *(['--offer-trained'] if args.offer_trained else [])], directory / 'classic.log')
        if not (directory / 'modern/receipt.json').exists():
            run(['tools/verify_gen2_trading.py', '--game', args.game, '--load', modern,
                 '--species', outgoing['species'], '--time-capsule', '--output', directory / 'modern'], directory / 'modern.log')
        if not all((directory / side / 'adopted.state').exists() for side in ('classic', 'modern')):
            run(['tools/verify_gen2_exchange.py', directory / 'classic', directory / 'modern', '--data', args.data], directory / 'exchange.log')
        if not (directory / 'restored/final.json').exists():
            run(['tools/play_gen2.py', rom, '--game', args.game, '--load', directory / 'modern/adopted.state',
                 '--real-clock', '--frames', 60000, '--stall-frames', 20000, '--focus', 'restore', '--until', 'restore',
                 '--output', directory / 'restored'], directory / 'restore.log')
        final = json.loads((directory / 'restored/final.json').read_text())
        if final['stopped'] or 'restore' not in final['policy']['completed'] or species not in final['game']['dex_owned']:
            raise ValueError('The traded species or restored team did not verify')
        progress.update(classic=str((directory / 'classic/adopted.state').resolve()),
                        modern=str((directory / 'restored/final.state').resolve()), owned=final['game']['owned'])
        progress.pop('reason', None)
        progress.pop('remaining_gen1', None)
        progress['trades'].append({'species': species, 'returned': outgoing['species'], 'directory': str(directory.resolve()),
                                   'owned': final['game']['owned']})
        cursor.write_text(json.dumps(progress, indent=2))
        print('Verified', species, 'owned', progress['owned'], flush=True)


if __name__ == '__main__':
    main()
