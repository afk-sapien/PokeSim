"""Prepare a saved Gen I partner through native PC and Cable Club controls."""
import argparse
import json
from pathlib import Path
import time
from types import SimpleNamespace

from pokesim.runtime.settings import SimulationSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--load', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dex', type=int, required=True)
    parser.add_argument('--offer-trained', action='store_true', help='Offer a nonperfect boxed partner in this disposable copy')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    settings = SimulationSettings(rom_path=str(args.rom.resolve()), data_dir=str((args.output / 'store').resolve()),
        game_data_dir=str(args.data.resolve()), speed=0)
    settings.install(managed=True)
    from pokesim.emulator import Emulator
    from pokesim.policies.base import PolicyContext, stack_pointer
    from pokesim.ram import read_snapshot
    from pokesim.runtime.participant import Participant
    from pokesim.store import Store
    store = Store(Path(settings.data_dir))
    emu = Emulator(store, isolated_ram=True)
    try:
        with args.load.open('rb') as source:
            emu.pb.load_state(source)
        metadata = args.load.with_suffix('.json')
        if metadata.exists():
            saved = json.loads(metadata.read_text())
            emu.policy.load_state_dict(saved.get('policy_state', {}))
        emu.snapshot = read_snapshot(emu.pb.memory, emu.frame)
        runtime = SimpleNamespace(store=store, emulator=emu, settings=settings)
        participant = Participant(runtime, SimpleNamespace(adventure_id='classic', generation=1))
        if args.offer_trained:
            from pokesim.web.pokedex import live_status
            from pokesim.trade.preferences import apply, update
            payload = apply(live_status(emu.snapshot.to_dict()), store.trade_preferences())
            for mon in payload['storage']['pokemon']:
                if mon['dex'] == args.dex and not mon['trade_ambiguous'] and tuple(mon['dvs']) != (15,) * 5:
                    update(store, payload, mon['trade_key'], 'offered')
        inventory = participant.inventory()
        offer = next((mon for mon in inventory['offers'] if mon['dex'] == args.dex), None)
        if offer is None:
            raise ValueError(f'No eligible boxed offer for Pokédex entry {args.dex}')
        request = {'id': '0123456789abcdef0123456789abcdef', 'plan_digest': 'test',
                   'selected_key': offer['trade_key'], 'time_capsule': True}
        receipt = participant.prepare(request)
        for step in range(12000):
            snapshot = read_snapshot(emu.pb.memory, emu.frame)
            actions = emu.preparation.step(PolicyContext(snapshot, 0, time.monotonic(), emu.pb.memory, stack_pointer(emu.pb)))
            for action in actions:
                if action.button:
                    emu.pb.button_press(action.button)
                emu.pb.tick(action.hold, True)
                if action.button:
                    emu.pb.button_release(action.button)
                emu.pb.tick(action.gap, True)
                emu.frame += action.hold + action.gap
            emu.snapshot = read_snapshot(emu.pb.memory, emu.frame)
            if step % 100 == 0:
                print(step, emu.snapshot.map, emu.snapshot.x, emu.snapshot.y,
                      store.get('interaction_preparation')['phase'], flush=True)
            state = store.get('interaction_preparation')
            if state['phase'] in {'ready', 'failed'}:
                receipt = participant.prepare(request)
                break
        if receipt['phase'] != 'prepared':
            raise ValueError(f'Trade preparation did not finish: {receipt.get("phase")}')
        (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2))
        print('Prepared native Gen I offer', args.dex, flush=True)
    finally:
        emu.pb.screen.image.save(args.output / 'final.png')
        with (args.output / 'final.state').open('wb') as output:
            emu.pb.save_state(output)
        (args.output / 'final.json').write_text(json.dumps({'policy_state': emu.policy.state_dict()}))
        emu.pb.stop(save=False)
        store.close()


if __name__ == '__main__':
    main()
