"""Exercise Gen II installation, real Library workers and automatic trading."""
import argparse
from pokesim_core.emulator_state import checkpoint_metadata
import json
from pathlib import Path
import time

from pokesim import __version__
from pokesim.app.manager import Manager
from pokesim.app.registry import identifier
from pokesim.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roms', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--states', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manager = Manager(args.output, game_data_dir=args.data)
    adventures = []
    try:
        for game, source in [('gold', 'gold-40'), ('silver', 'silver-41'), ('crystal', 'crystal-76')]:
            rom = manager.assets.install_rom((args.roms / (game + '.gbc')).read_bytes())
            manager.assets.prepare_gen2(game)
            assert manager.assets.install_portraits(manager.assets.rom_path(rom['id']).read_bytes()) == 251
            row = manager.registry.create(game.title(), rom['id'],
                {'starter': 'cyndaquil', 'speed': 0, 'policy': 'strategic', 'league_rewards': False, 'mew_event': False}, identifier())
            aid = row['id']
            path = args.states / source / 'final.state'
            store = Store(manager.root / 'adventures' / aid)
            try:
                metadata = {'app_version': __version__, **checkpoint_metadata(),
                            'generation': 2, 'rom_sha1': rom['sha1'], 'frame': 0, 'policy': 'strategic',
                            'policy_state': json.loads(path.with_suffix('.policy.json').read_text()),
                            'run_memory': {}, 'play_clock': {}, 'trade_id': None, 'reward_id': None}
                store.write_checkpoint(path.read_bytes(), metadata)
            finally:
                store.close()
            manager.registry.update(aid, desired_state='running')
            manager.supervisor.start(aid)
            child = manager.supervisor.child(aid)
            deadline = time.monotonic() + 30
            while not (state := child.request('GET', '/api/state')).get('game'):
                assert time.monotonic() < deadline
                time.sleep(0.05)
            assert state['generation'] == 2 and len(state['game']['badges']) == 16
            assert len(child.request('GET', '/api/pokedex')['entries']) == 251
            assert child.request('GET', '/healthz')['ok']
            adventures.append(aid)
            print('Installed and started', game, aid, flush=True)
        aid = adventures[0]
        offer = manager.coordinator.inventory(aid)['offers'][0]
        request = {'id': identifier(), 'plan_digest': 'restart-check', 'selected_key': offer['trade_key']}
        child = manager.supervisor.child(aid)
        receipt = child.request('POST', '/internal/participant/prepare', request)
        assert receipt['phase'] == 'preparing'
        manager.supervisor.stop(aid, preserve_desired=True)
        manager.supervisor.start(aid)
        child = manager.supervisor.child(aid)
        try:
            child.request('POST', '/internal/participant/prepare', request)
        except RuntimeError as error:
            assert 'interrupted' in str(error), error
        else:
            raise AssertionError('Interrupted preparation did not request release')
        assert child.request('POST', '/internal/participant/abort', {'id': request['id']})['phase'] == 'aborted'
        assert not manager.coordinator.inventory(aid)['holding']
        assert not child.request('GET', '/api/state')['paused']
        print('Worker restart during preparation released its reservation and resumed play.', flush=True)
        manager.coordinator.prepare_timeout = 240
        manager.coordinator.session_timeout = 240
        result = manager.coordinator.schedule_once()
        assert result and result['phase'] == 'completed', result
        assert result['decision'] == 'COMMIT'
        for aid in result['plan']['participants']:
            state = manager.supervisor.child(aid).request('GET', '/api/state')
            assert state['generation'] == 2 and state['health']['ok']
            assert not manager.coordinator.inventory(aid)['holding']
        (args.output / 'result.json').write_text(json.dumps(result, indent=2))
        print('All three real workers passed. Automatic Gen II trade completed and released both adventures.', flush=True)
    finally:
        manager.close()


if __name__ == '__main__':
    main()
