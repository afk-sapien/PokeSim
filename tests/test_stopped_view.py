"""A stopped adventure's pages load read only from its newest save, with no running emulator."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pokesim import game_data

PANELS = ('/', '/pokedex', '/team', '/journey', '/pc', '/journal', '/journal/stats', '/stats', '/stats/pokemon',
          '/stats/items', '/trading', '/api/state?storage=1', '/api/pokedex', '/api/pokedex/status',
          '/api/statistics', '/api/statistics/activity', '/api/trading', '/api/events', '/api/progress',
          '/frame.jpg', '/feed.xml')


def _reference():
    try:
        for name in game_data.FILES:
            game_data.load(name)
    except RuntimeError:
        pytest.skip('Gen I reference data is not prepared')
    return game_data.directory()


def _check(tmp_path, rom, data_dir):
    code = f"""
import hashlib, time
from pathlib import Path
from fastapi.testclient import TestClient
from pokesim.runtime.settings import SimulationSettings
from pokesim.runtime.simulation import SimulationRuntime
data = Path({str(tmp_path / 'adventure')!r})
settings = SimulationSettings(rom_path={str(rom)!r}, data_dir=str(data), game_data_dir={str(data_dir)!r}, speed=0)
with SimulationRuntime(settings) as runtime:
    # Save as soon as the game reads as valid instead of waiting for the timed autosave, which a
    # loaded machine can miss. The deadline is only a backstop for a game that never gets there.
    deadline = time.monotonic() + 540
    while not getattr(runtime.emulator.snapshot, 'valid', False):
        assert time.monotonic() < deadline, 'the game state never became valid'
        time.sleep(0.2)
    runtime.call(runtime.emulator._autosave)
    assert list((data / 'states').glob('*')), 'no autosave was written'
def digest():
    return {{p: hashlib.sha1(p.read_bytes()).hexdigest() for p in sorted(data.rglob('*')) if p.is_file()}}
before = digest()
with SimulationRuntime(settings, frozen=True) as runtime:
    assert not runtime.emulator.thread.is_alive()
    client = TestClient(runtime.create_app())
    for path in {PANELS!r}:
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code, response.text[:300])
    state = client.get('/api/state').json()
    assert state['stopped'] is True
    assert client.post('/api/control', json={{'action': 'pause'}}).status_code == 409
assert digest() == before, 'the stopped view changed the adventure on disk'
"""
    env = {**os.environ, 'GAME_DATA_DIR': str(data_dir)}
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True,
                            cwd=Path(__file__).parents[1], timeout=600)
    assert result.returncode == 0, result.stderr[-3000:]


def test_stopped_red_adventure_renders_every_panel_read_only(tmp_path):
    rom = Path(os.environ.get('ROM_PATH', 'roms/pokered.gb'))
    if not rom.is_file():
        pytest.skip('Set ROM_PATH to a Pokemon Red cartridge')
    _check(tmp_path, rom, _reference())


def test_stopped_crystal_adventure_renders_every_panel_read_only(tmp_path):
    if not (os.environ.get('GEN2_CARTRIDGE_DIR') and os.environ.get('GEN2_DATA_DIR')):
        pytest.skip('Set GEN2_CARTRIDGE_DIR and GEN2_DATA_DIR')
    combined = tmp_path / 'game-data'
    shutil.copytree(_reference(), combined)
    shutil.copytree(Path(os.environ['GEN2_DATA_DIR']) / 'gen2', combined / 'gen2', dirs_exist_ok=True)
    _check(tmp_path, Path(os.environ['GEN2_CARTRIDGE_DIR']) / 'crystal.gbc', combined)
