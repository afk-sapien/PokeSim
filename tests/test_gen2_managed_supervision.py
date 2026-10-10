"""A managed Generation II worker must stay up under the real supervisor.

Skips unless GEN2_CARTRIDGE_DIR (extracted gold.gbc, silver.gbc, crystal.gbc) and GEN2_DATA_DIR
(generated local game data) are set. Set POKESIM_GEN2_SOAK_SECONDS to change the 80 second soak.
"""
import os
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim.app.registry import Registry, identifier
from pokesim.app.supervisor import Supervisor

SOAK = float(os.environ.get('POKESIM_GEN2_SOAK_SECONDS', '80'))


@pytest.mark.parametrize('version', ['gold', 'silver', 'crystal'])
def test_real_gen2_worker_stays_healthy_past_the_monitor_sync_interval(tmp_path, version):
    cartridges, data = os.environ.get('GEN2_CARTRIDGE_DIR'), os.environ.get('GEN2_DATA_DIR')
    if not cartridges or not data:
        pytest.skip('Set GEN2_CARTRIDGE_DIR and GEN2_DATA_DIR to run a real Generation II worker')
    rom = Path(cartridges) / f'{version}.gbc'
    if not rom.is_file():
        pytest.skip(f'{rom.name} is not available')
    if version != 'gold' and os.environ.get('POKESIM_GEN2_SOAK_ALL') != '1':
        pytest.skip('Set POKESIM_GEN2_SOAK_ALL=1 to soak Silver and Crystal as well')
    # A prepared library holds the shared Gen I tables beside the Gen II bundles.
    from test_gen2_only_library import _reference
    combined = tmp_path / 'game-data'
    shutil.copytree(_reference(tmp_path), combined)
    shutil.copytree(Path(data) / 'gen2', combined / 'gen2', dirs_exist_ok=True)
    data = str(combined)
    registry = Registry(tmp_path / 'library')
    registry.add_rom('digest', 'sha1', version)
    assets = SimpleNamespace(rom_path=lambda rid: rom, game_data_dir=Path(data),
                             prepare_gen2=lambda game, report: Path(data), install_portraits=lambda raw: 0,
                             cancelled=threading.Event())
    supervisor = Supervisor(registry, assets, 'http://127.0.0.1:8000')
    try:
        row = registry.create('Johto', 'digest', {'starter': 'random', 'celebi_event': False}, identifier())
        registry.request_lifecycle(row['id'], 'start', identifier())
        aid = row['id']
        supervisor.start(aid)
        first = supervisor.children[aid]
        supervisor.run_monitor()
        deadline = time.monotonic() + SOAK
        while time.monotonic() < deadline:
            time.sleep(2)
            current = registry.adventure(aid)
            assert current['state'] == 'running', current['error']
            assert supervisor.children.get(aid) is first, 'the worker was restarted'
            assert first.process.poll() is None
        assert supervisor.retries.get(aid, []) == []
        assert not supervisor.unhealthy_since
        assert first.request('GET', '/healthz', timeout=3)
        summary = registry.adventure(aid)['summary']
        assert time.time() - summary['last_response'] < 15, 'health reporting stopped'
    finally:
        supervisor.close()
        registry.close()
