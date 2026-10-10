"""A library that only holds Gen II adventures must still be able to start a worker."""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim import game_data


def test_gen2_worker_modules_import_without_gen1_game_data(tmp_path):
    code = 'import pokesim.web.app, pokesim.gen2.trading, pokesim.runtime.worker, pokesim.runtime.participant'
    env = {**os.environ, 'GAME_DATA_DIR': str(tmp_path / 'missing')}
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, cwd=Path(__file__).parents[1])
    assert result.returncode == 0, result.stderr


def _reference(tmp_path):
    try:
        for name in game_data.FILES:
            game_data.load(name)
    except RuntimeError:
        pytest.skip('Gen I reference data is not prepared')
    return game_data.directory()


def test_gen2_preparation_also_prepares_gen1_tables_without_a_download(tmp_path, monkeypatch):
    from pokesim.app import assets as assets_module
    from pokesim.app.assets import Assets
    from pokesim.gen2 import data as gen2_data
    reference = _reference(tmp_path)
    registry = SimpleNamespace(root=tmp_path / 'library', roms=lambda: [])
    assets = Assets(registry, game_data_dir=reference)
    # A Gen II-only library: the folder exists and holds a Gen II bundle but no Gen I pointer.
    (assets.game_data_dir / 'gen2' / 'gold').mkdir(parents=True)
    (assets.game_data_dir / 'gen2' / 'gold' / 'data.json').write_text('{}')
    monkeypatch.setattr(gen2_data, 'ensure', lambda *args: None)
    monkeypatch.setattr(assets_module, 'ensure_game_data', lambda *a: None if assets._has_gen1_data() else pytest.fail('download'))

    assets.prepare_gen2('gold')

    for name in game_data.FILES:
        assert game_data.load(name, directory=assets.game_data_dir) == game_data.load(name, directory=reference)
    assert (assets.game_data_dir / 'gen2' / 'gold' / 'data.json').read_text() == '{}'


def test_gen1_preparation_copies_the_reference_into_a_folder_that_already_exists(tmp_path, monkeypatch):
    from pokesim.app import assets as assets_module
    from pokesim.app.assets import Assets
    reference = _reference(tmp_path)
    registry = SimpleNamespace(root=tmp_path / 'library', roms=lambda: [])
    assets = Assets(registry, game_data_dir=reference)
    assets.game_data_dir.mkdir(parents=True)
    monkeypatch.setattr(assets_module, 'ensure_game_data', lambda *a: None if assets._has_gen1_data() else pytest.fail('download'))
    assets.prepare()
    assert assets._has_gen1_data()


def _run_runtime(tmp_path, game, data_dir):
    code = f"""
from fastapi.testclient import TestClient
from pokesim.runtime.settings import SimulationSettings
from pokesim.runtime.simulation import SimulationRuntime
settings = SimulationSettings(rom_path={str(Path(os.environ['GEN2_CARTRIDGE_DIR']) / (game + '.gbc'))!r},
                              data_dir={str(tmp_path / 'adventure')!r}, game_data_dir={str(data_dir)!r}, speed=0)
with SimulationRuntime(settings) as runtime:
    client = TestClient(runtime.create_app())
    assert client.get('/api/pokedex/status').status_code == 200
"""
    env = {**os.environ, 'GAME_DATA_DIR': str(tmp_path / 'missing')}
    return subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, cwd=Path(__file__).parents[1])


@pytest.fixture
def real_gen2():
    if not (os.environ.get('GEN2_CARTRIDGE_DIR') and os.environ.get('GEN2_DATA_DIR')):
        pytest.skip('Set GEN2_CARTRIDGE_DIR and GEN2_DATA_DIR')


@pytest.mark.parametrize('game', ['gold', 'crystal'])
def test_real_gen2_runtime_serves_once_the_shared_tables_are_prepared(tmp_path, real_gen2, game):
    combined = tmp_path / 'game-data'
    shutil.copytree(_reference(tmp_path), combined)
    shutil.copytree(Path(os.environ['GEN2_DATA_DIR']) / 'gen2', combined / 'gen2', dirs_exist_ok=True)
    result = _run_runtime(tmp_path, game, combined)
    assert result.returncode == 0, result.stderr[-2000:]


def test_real_gen2_runtime_without_the_shared_tables_fails_with_a_clear_message(tmp_path, real_gen2):
    result = _run_runtime(tmp_path, 'gold', os.environ['GEN2_DATA_DIR'])
    assert result.returncode != 0
    assert 'Gen I reference tables' in result.stderr
