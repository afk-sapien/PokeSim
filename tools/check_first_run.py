"""Check first ROM upload and automatic setup in an empty application directory."""
import argparse
import hashlib
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--game-data', type=Path)
    parser.add_argument('--rom', type=Path)
    args = parser.parse_args()

    from fastapi.testclient import TestClient
    from pokesim_core import emulator as pyboy
    from pokesim import desktop_setup, sprites
    from pokesim.app.manager import Manager, create_app
    from pokesim.app.registry import identifier

    raw = (args.rom or pyboy.demo_rom()).read_bytes()
    if not args.rom:
        # Only this isolated probe accepts the redistributable demo cartridge.
        desktop_setup.ROM_NAMES[hashlib.sha1(raw).hexdigest()] = 'Pokémon Red'

        def demo_portraits(rom, species):
            assert rom == raw
            assert all(isinstance(key, int) for key in species)
            assert {entry['dex'] for entry in species.values()} >= set(range(1, 152))
            return {dex: sprites._png([[0]]) for dex in range(1, 152)}

        sprites.extract = demo_portraits

    with tempfile.TemporaryDirectory(prefix='pokesim-first-run-', dir=args.data_dir) as temporary:
        root = Path(temporary)
        os.environ['DATA_DIR'] = str(root / 'legacy')
        os.environ['GAME_DATA_DIR'] = str(root / 'missing-reference')
        manager = Manager(root / 'library', 'http://testserver', game_data_dir=args.game_data)
        with TestClient(create_app(manager)) as client:
            csrf = client.get('/api/v1/session').json()['csrf_token']
            response = client.post('/api/v1/assets/rom', content=raw,
                                   headers={'X-PokeSim-CSRF': csrf})
            assert response.status_code == 200, response.text
            assert not manager.assets.game_data_dir.exists(), 'Upload must not require reference setup'
            assert 'pokesim.strategy_data' not in sys.modules
            rom = response.json()
            adventure = manager.registry.create('First adventure', rom['id'], {}, identifier())
            aid = adventure['id']
            manager.registry.request_lifecycle(aid, 'start', identifier())
            assert manager.start_adventure(aid)['state'] == 'running'
            assert (manager.assets.game_data_dir / 'current.json').is_file()
            portraits = list((manager.assets.root / 'sprites').glob('*.png'))
            assert len(portraits) == 151, len(portraits)
            assert 'pokesim.strategy_data' not in sys.modules
            assert not (root / 'missing-reference').exists()
            assert not (root / 'legacy').exists()
            manager.supervisor.stop(aid)
            assert list((manager.root / 'adventures' / aid / 'states').glob('*.state'))
            custom = manager.assets.root / 'sprites' / '1.png'
            custom_art = sprites._png([[1]])
            custom.write_bytes(custom_art)

            def unexpected_download(*args, **kwargs):
                raise AssertionError('A prepared library must restart without downloading reference data')

            desktop_setup.urlopen = unexpected_download
            manager.registry.request_lifecycle(aid, 'start', identifier())
            assert manager.start_adventure(aid)['state'] == 'running'
            assert custom.read_bytes() == custom_art
            manager.supervisor.stop(aid)
    print('First run passed: upload without legacy data, automatic setup, portraits, worker start, save, and offline restart')


if __name__ == '__main__':
    main()
