"""Check durable capture receipts and replay protection on a private battle copy."""
import argparse
from dataclasses import replace
import io
from pathlib import Path
import tempfile

from pyboy import PyBoy

from pokesim.gen2.data import GameData
from pokesim.gen2.policy import Action, Policy
from pokesim.gen2.ram import Memory, read_snapshot
from pokesim.gen2.tracking import CAPTURES, Tracker
from pokesim.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom', type=Path)
    parser.add_argument('state', type=Path)
    parser.add_argument('--game', required=True, choices=('gold', 'silver', 'crystal'))
    parser.add_argument('--data', type=Path, default=Path('.release-local/gen2-data'))
    args = parser.parse_args()
    data = GameData.load(args.data, args.game)
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory))
        tracker = Tracker(store, data, fresh=False)
        pb = PyBoy(str(args.rom), window='null', cgb=True, ram_file=io.BytesIO(bytes(32768)))
        pb.set_emulation_speed(0)
        tracker.attach(pb)
        try:
            for replay in range(2):
                pb.load_state(io.BytesIO(args.state.read_bytes()))
                initial = read_snapshot(pb.memory, data)
                assert initial.in_battle == 1 and initial.enemy_hp and initial.pockets['balls'] and initial.can_catch
                policy = Policy(data)
                for step in range(2500):
                    snapshot = read_snapshot(pb.memory, data)
                    mem = Memory(pb.memory, data)
                    naming = policy.naming.step(snapshot, mem)
                    action = Action(naming, 6, 18) if naming else policy.battle(replace(snapshot, owned=frozenset()), mem)
                    if action.button:
                        pb.button_press(action.button)
                    pb.tick(action.hold, True)
                    if action.button:
                        pb.button_release(action.button)
                    pb.tick(action.gap, True)
                    if not snapshot.in_battle:
                        break
                value = store.get(CAPTURES)
                assert value['total'] == 1, value
                print(f'Capture completion and replay {replay}: {value}', flush=True)
        finally:
            pb.stop(save=False)
            store.close()


if __name__ == '__main__':
    main()
