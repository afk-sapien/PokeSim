"""Check a Gen II adventure through the shared web API and checkpoint restart."""
import argparse
import json
from pathlib import Path
import tempfile
import time

from fastapi.testclient import TestClient

from pokesim.runtime.settings import SimulationSettings
from pokesim.runtime.simulation import SimulationRuntime
from pokesim.gen2.ram import Memory, read_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom', type=Path)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output) as directory:
        settings = SimulationSettings(rom_path=str(args.rom.resolve()), data_dir=str(Path(directory).resolve()),
                                      game_data_dir=str(args.data.resolve()), speed=0, starter='cyndaquil',
                                      trainer_name='TY', rival_name='SILVER')
        with SimulationRuntime(settings) as runtime:
            emu = runtime.emulator
            deadline = time.monotonic() + 20
            while not emu.snapshot or not emu.snapshot.party:
                if not emu.thread.is_alive() or time.monotonic() > deadline:
                    raise AssertionError(f'The adventure did not start: {emu.fatal_error}')
                time.sleep(0.05)
            def pause_when_walking():
                snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
                if (snapshot.party and not snapshot.in_battle and not Memory(emu.pb.memory, emu.data).byte('wScriptRunning')
                        and '┌' not in snapshot.tiles[12] and not emu.policy.menu and emu.policy.mode not in {'opening', 'naming'}):
                    emu._handle_command('pause', None)
                    return True
                return False

            deadline = time.monotonic() + 30
            while not emu.call(pause_when_walking):
                assert time.monotonic() < deadline, 'No walking state available for export'
                time.sleep(0.02)
            app = runtime.create_app()
            with TestClient(app) as client:
                for route in ('/', '/pokedex', '/pc', '/journal', '/api/state', '/api/pokedex',
                              '/api/pokedex/status', '/api/progress', '/api/statistics', '/api/trading', '/healthz'):
                    response = client.get(route)
                    assert response.status_code == 200, (route, response.status_code, response.text[:300])
                state = client.get('/api/state').json()
                assert state['generation'] == 2
                assert state['game']['player_name'] == 'TY', state['game']['player_name']
                assert len(client.get('/api/pokedex').json()['entries']) == 251
                audio = client.get('/api/audio')
                assert audio.status_code == 200 and audio.headers['x-audio-state'] == 'paused'
                assert int(audio.headers['x-audio-rate']) > 0
                frame = client.get('/frame.jpg')
                assert frame.status_code == 200 and frame.content.startswith(b'\x89PNG')
                exported = client.post('/api/export-save')
                assert exported.status_code == 200, exported.text[:300] if exported.status_code != 200 else ''
                assert len(exported.content) == 32768
                assert client.post('/api/control', json={'action': 'press', 'value': 'bad'}).status_code == 400
                assert client.post('/api/control', json={'action': 'take_control'}).status_code == 200
                emu.call(lambda: None)
                assert emu.manual_mode
                before = emu.frame
                assert client.post('/api/control', json={'action': 'press', 'value': 'right'}).status_code == 200
                deadline = time.monotonic() + 5
                while emu.frame <= before:
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
                assert client.post('/api/control', json={'action': 'pause'}).status_code == 200
                emu.call(lambda: None)
                assert emu.paused and not emu.manual_mode
                assert client.post('/api/control', json={'action': 'save'}).status_code == 200
            saved = emu.call(emu._autosave)
            previous = emu.snapshot.to_dict()
            steps = runtime.store.get('cartridge-steps-v1')['total']
            assert steps > 0, 'No completed cartridge walking steps were recorded'
            assert saved.exists()
        with SimulationRuntime(settings) as runtime:
            emu = runtime.emulator
            emu.call(lambda: emu._handle_command('pause', None))
            restored = emu.status()['game']
            assert restored['player_name'] == previous['player_name']
            assert restored['dex_owned'] == previous['dex_owned']
            assert restored['party'][0]['species'] == previous['party'][0]['species']
            assert runtime.store.get('cartridge-steps-v1')['total'] >= steps
            assert emu.health()['ok']
        (args.output / 'report.json').write_text(json.dumps({'game': previous, 'routes': 'passed', 'restart': 'passed'}, indent=2))
        print('API routes and checkpoint restart passed')


if __name__ == '__main__':
    main()
