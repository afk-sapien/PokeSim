"""Check bundled imports and real child-process supervision using PyBoy's demo."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: check_desktop_runtime.py /path/to/PokeSim')
    executable = str(Path(sys.argv[1]).resolve())
    subprocess.run([executable, '--check-runtime'], check=True, timeout=180)
    import httpx
    import pyboy
    from pokesim.app.supervisor import Child
    from pokesim import game_data
    reference = game_data.directory().resolve()
    for name in game_data.FILES:
        game_data.load(name, directory=reference)
    demo = Path(pyboy.__file__).with_name('default_rom.gb').resolve()
    with tempfile.TemporaryDirectory(prefix='pokesim-bundled-workers-') as temporary:
        root = Path(temporary)
        children = []
        try:
            for number in range(2):
                bootstrap = {'protocol': 1, 'adventure_id': f'demo-{number}',
                    'adventure_name': f'Demo {number}', 'generation': f'check-{number}',
                    'token': secrets.token_hex(32), 'settings': {
                        'rom_path': str(demo), 'data_dir': str(root / str(number)),
                        'game_data_dir': str(reference),
                        'public_url': f'http://127.0.0.1:8000/games/demo-{number}'}}
                child = Child(bootstrap, command=[executable, '--worker'])
                children.append(child)
                child.start(timeout=45)
                with httpx.Client(trust_env=False, timeout=5) as client:
                    assert client.get(child.url + '/internal/health').status_code == 401
                    response = client.get(child.url + '/internal/health',
                        headers={'Authorization': 'Bearer ' + child.token})
                    response.raise_for_status()
                    assert response.json()['adventure_id'] == bootstrap['adventure_id']
            assert children[0].process.pid != children[1].process.pid
            for number, child in enumerate(children):
                child.process.stdin.close()
                child.process.wait(timeout=30)
                assert child.process.returncode == 0, list(child.logs)
                assert list((root / str(number) / 'states').glob('*.state'))
        finally:
            for child in children:
                child.stop(timeout=5)
    print('Bundled workers passed: two independent processes, private credentials, parent-loss saves and exit')


if __name__ == '__main__':
    main()
