"""Exercise managed Gen II PC preparation on a disposable adventure copy."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from pokesim.gen2.emulator import Emulator
from pokesim.gen2.ram import read_snapshot
from pokesim.gen2.trading import Participant
from pokesim.runtime.settings import SimulationSettings
from pokesim.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', required=True)
    parser.add_argument('--load', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--species', type=int)
    parser.add_argument('--trade-key', help='Select one exact boxed individual')
    parser.add_argument('--time-capsule', action='store_true')
    parser.add_argument('--offer-trained', action='store_true')
    parser.add_argument('--evolve', action='store_true', help='Swap the held item for an available evolution item through native menus')
    args = parser.parse_args()
    if args.evolve and args.time_capsule:
        parser.error('--evolve requires a Gen II Cable Club trade')
    args.output.mkdir(parents=True, exist_ok=True)
    settings = SimulationSettings(rom_path=str(Path(f'.release-local/gen2/{args.game}.gbc').resolve()),
        data_dir=str((args.output / 'store').resolve()), game_data_dir=str(Path('.release-local/gen2-data').resolve()),
        starter='random', speed=0)
    settings.install(managed=True)
    store = Store(Path(settings.data_dir))
    emu = Emulator(store)
    try:
        with args.load.open('rb') as source:
            emu.pb.load_state(source)
        metadata = args.load.with_suffix('.policy.json')
        if metadata.exists():
            emu.policy.load_state_dict(json.loads(metadata.read_text()))
        for _ in range(12):
            emu.pb.button_press('b')
            emu.pb.tick(8, True)
            emu.pb.button_release('b')
            emu.pb.tick(32, True)
        emu.snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
        for _ in range(6000):
            from pokesim.gen2.ram import Memory
            snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
            if (snapshot.started and not snapshot.in_battle and not emu.policy.in_league(snapshot)
                    and not Memory(emu.pb.memory, emu.data).byte('wScriptRunning')):
                break
            action = emu.policy.step(snapshot, emu.pb.memory)
            if action.button:
                emu.pb.button_press(action.button)
            if action.hold:
                emu.pb.tick(action.hold, True)
            if action.button:
                emu.pb.button_release(action.button)
            if action.gap:
                emu.pb.tick(action.gap, True)
            emu.frame += action.hold + action.gap
        emu.snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
        runtime = SimpleNamespace(store=store, emulator=emu, settings=settings)
        participant = Participant(runtime, SimpleNamespace(adventure_id=args.game, generation=1))
        if args.offer_trained:
            from pokesim.gen2.web import live_status
            from pokesim.trade.preferences import apply, update
            payload = apply(live_status(emu.snapshot.to_dict()), store.trade_preferences())
            for mon in payload['storage']['pokemon']:
                if mon['species'] == args.species and not mon['trade_ambiguous'] and tuple(mon['dvs']) != (15,) * 5:
                    update(store, payload, mon['trade_key'], 'offered')
        inventory = participant.inventory()
        assert inventory['offers'], 'No eligible boxed Pokémon in this scenario'
        offer = next((mon for mon in inventory['offers']
                      if (args.species is None or mon['species'] == args.species)
                      and (args.trade_key is None or mon['trade_key'] == args.trade_key)), None)
        assert offer, 'The requested species is not an eligible boxed offer'
        if args.evolve:
            from pokesim.gen2.cable_verification import available_trade_item, evolved_species
            item = available_trade_item(emu.data, offer['species'], offer['held_item'],
                                        dict(emu.snapshot.items), replace_held=True)
            if item is None and evolved_species(bytes((offer['species'], offer['held_item'])), emu.data) == offer['species']:
                raise ValueError('No evolution item is available for this partner')
        key = offer['trade_key']
        request = {'id': '0123456789abcdef0123456789abcdef', 'plan_digest': 'test', 'selected_key': key,
                   'time_capsule': args.time_capsule}
        receipt = participant.prepare(request)
        if args.evolve:
            emu.preparation.state['replace_held'] = True
        for step in range(4000):
            snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
            action = emu.preparation.step(snapshot)
            if action.button:
                emu.pb.button_press(action.button)
            if action.hold:
                emu.pb.tick(action.hold, True)
            if action.button:
                emu.pb.button_release(action.button)
            if action.gap:
                emu.pb.tick(action.gap, True)
            emu.frame += action.hold + action.gap
            emu.snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
            if step % 50 == 0:
                print(step, emu.snapshot.map_name, emu.snapshot.x, emu.snapshot.y, action,
                      vars(emu.preparation.menu) if emu.preparation.menu else None, flush=True)
            if emu.preparation.state['phase'] in {'ready', 'failed'}:
                receipt = participant.prepare(request)
                break
        assert receipt['phase'] == 'prepared', receipt
        (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2))
        print('Prepared boxed offer through the cartridge PC', receipt['source'], flush=True)
    finally:
        emu.pb.screen.image.save(args.output / 'final.png')
        with (args.output / 'final.state').open('wb') as output:
            emu.pb.save_state(output)
        emu.pb.stop(save=False)
        store.close()


if __name__ == '__main__':
    main()
