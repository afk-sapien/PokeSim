"""Verify optional Gen II gift delivery, rewind barriers and durable recovery."""
import argparse
import time
from pathlib import Path
import tempfile

from pokesim import rewards
from pokesim.gen2.ram import Memory, read_snapshot
from pokesim.gen2.rewards import deliver
from pokesim.runtime.settings import SimulationSettings
from pokesim.runtime.simulation import SimulationRuntime
from pokesim.runtime.reward_delivery import recover_storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom', type=Path)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output) as directory:
        settings = SimulationSettings(rom_path=str(args.rom.resolve()), game_data_dir=str(args.data.resolve()),
                                      data_dir=str(Path(directory).resolve()), speed=0, starter='cyndaquil',
                                      league_rewards=True)
        with SimulationRuntime(settings) as runtime:
            emu = runtime.emulator
            def pause():
                snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
                if (snapshot.party and not snapshot.in_battle and not Memory(emu.pb.memory, emu.data).byte('wScriptRunning')
                        and '┌' not in snapshot.tiles[12] and not emu.policy.menu):
                    emu._handle_command('pause', None)
                    return True
                return False
            deadline = time.monotonic() + 40
            while not emu.call(pause):
                assert time.monotonic() < deadline, emu.fatal_error
                time.sleep(0.02)
            source = emu.call(emu._autosave)
            before = emu.snapshot
            rewards.earn(runtime.store, 1, enabled=True)
            def claim():
                emu.paused = False
                try:
                    result = deliver(emu)
                    assert result and deliver(emu) is None
                finally:
                    emu.paused = True
                return result
            record = emu.call(claim)
            after = emu.snapshot
            assert after.party == before.party
            assert len(after.stored) == len(before.stored) + 1
            assert after.stored[-1].species in (152, 155, 158)
            assert rewards.status(runtime.store)['delivered'] == 1
            assert recover_storage(runtime.store) is None
            try:
                emu.call(lambda: emu._load_state_file(source))
            except ValueError as error:
                assert 'predates' in str(error)
            else:
                raise AssertionError('A pre-gift rewind was accepted')
            emu.call(emu._autosave)
            pending = runtime.store.get('custom-reward-pending-v1')
            runtime.store.set('custom-reward-pending-v1', {**pending, 'phase': 'committed'})
            assert recover_storage(runtime.store)
            assert recover_storage(runtime.store) is None
        with SimulationRuntime(settings) as runtime:
            emu = runtime.emulator
            emu.call(lambda: emu._handle_command('pause', None))
            assert emu.snapshot.stored == after.stored
            assert rewards.status(runtime.store)['delivered'] == 1
            assert emu.health()['ok']
        (args.output / 'result.txt').write_text('Delivery, replay protection, commitment recovery and restart passed\n')
        print('Delivery, replay protection, commitment recovery and restart passed', record['species'])


if __name__ == '__main__':
    main()
