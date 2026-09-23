"""Verify runtime resources and exclude private artifacts from built packages."""
from pathlib import Path
import tarfile
import zipfile
import tomllib
import json

required = {
    'pokesim/_build.json',
    'pokesim/build_info.py',
    'pokesim/runtime/legacy.py',
    'pokesim/policies/menus.py',
    'pokesim/policies/shopping.py',
    'pokesim/policies/storage.py',
    'pokesim/web/event_page.py',
    'pokesim/web/static/event.js',
    'pokesim/web/trading.py',
    'pokesim/trade/preferences.py',
    'pokesim/web/static/trade-ui.js',
    'pokesim/web/static/trading.html',
    'pokesim/web/static/trading.js',
    'pokesim/policies/navigation_numba.py',
    'pokesim/app/manager.py',
    'pokesim/app/coordinator.py',
    'pokesim/app/supervisor.py',
    'pokesim/app/cli.py',
    'pokesim/runtime/worker.py',
    'pokesim/runtime/simulation.py',
    'pokesim/runtime/preparation.py',
    'pokesim/runtime/reward_delivery.py',
    'pokesim/runtime/participant.py',
    'pokesim/interactions/link_worker.py',
    'pokesim/interactions/cable_metadata.py',
    'pokesim/web/library.py',
    'pokesim/web/pages.py',
    'pokesim/web/static/adventure-trading.html',
    'pokesim/web/static/adventure-trading.js',
    'pokesim/web/static/library.html',
    'pokesim/web/static/library.js',
    'pokesim/web/static/library.css',
    'pokesim/desktop.py',
    'pokesim/desktop_setup.py',
    'pokesim/desktop_check.py',
    'pokesim/platform_io.py',
    'pokesim/web/static/desktop.html',
    'pokesim/web/static/desktop.js',
    'pokesim/web/static/desktop.css',
    'pokesim/policies/director.py',
    'pokesim/policies/pickups.py',
    'pokesim/ground_items.py',
    'pokesim/broker/app.py',
    'pokesim/broker/inventory.py',
    'pokesim/broker/negotiation.py',
    'pokesim/broker/static/board.css',
    'pokesim/trade/execute.py',
    'pokesim/trade/event.py',
    'pokesim/rewards.py',
    'pokesim/legendary.py',
    'pokesim/trade/pair.py',
    'pokesim/trade/service.py',
    'pokesim/broker/routine.py',
    'pokesim/trade/boxes.py',
    'pokesim/duplicates.py',
    'pokesim/milestones.py',
    'pokesim/catches.py',
    'pokesim/play_clock.py',
    'pokesim/web/static/index.html',
    'pokesim/web/static/journal.html',
    'pokesim/web/static/pc.html',
    'pokesim/web/static/pc.js',
    'pokesim/web/static/pages.css',
    'pokesim/web/static/live.css',
    'pokesim/web/static/app.js',
    'pokesim/web/static/screen.js',
    'pokesim/web/static/style.css',
    'pokesim/web/static/pokedex.html',
    'pokesim/web/static/pokedex.js',
    'pokesim/web/static/pokedex.css',
    'pokesim/web/pokedex.py',
    'pokesim/healthcheck.py',
    'pokesim/prepare_data.py',
    'pokesim/checkpoints.py',
    'pokesim/web/feed.py',
    'pokesim/data_tools/strategy.py',
}
release_version = tomllib.loads(Path('pyproject.toml').read_text())['project']['version']
artifacts = list(Path('dist').glob(f'pokesim-{release_version}-*.whl')) + list(Path('dist').glob(f'pokesim-{release_version}.tar.gz'))
if len(artifacts) != 2 or sum(path.suffix == '.whl' for path in artifacts) != 1:
    raise SystemExit('Build exactly one wheel and one source archive first with uv build')
for artifact in artifacts:
    if artifact.suffix == '.whl':
        with zipfile.ZipFile(artifact) as archive:
            names = set(archive.namelist())
            identity = json.loads(archive.read('pokesim/_build.json'))
    else:
        with tarfile.open(artifact) as archive:
            names = {name.partition('/')[2] for name in archive.getnames()}
            identity = json.load(archive.extractfile(f'pokesim-{release_version}/pokesim/_build.json'))
        assert {'uv.lock', 'setup.py', 'THIRD_PARTY_NOTICES.md', 'RELEASE_STATUS.md',
                'Dockerfile', '.dockerignore', '.env.example', 'compose.yaml',
                'compose.build.yaml', 'compose.proxy.yaml', 'deploy/Caddyfile',
                'docs/README.md', 'docs/images/live-adventure.jpg',
                'docs/images/pc-storage.jpg', 'docs/images/pokedex.jpg',
                'docs/images/journal.jpg',
                'tools/check_web.py', 'tools/check_docs.py',
                'deploy/proxy.env.example', 'docs/validation/public-install-0.2.0rc2.json'} <= names
    missing = required - names
    assert identity['version'] == release_version, f'{artifact}: build version mismatch'
    assert not missing, f'{artifact}: missing runtime files {missing}'
    for name in names:
        path = Path(name)
        assert path.suffix not in {'.gb', '.gbc', '.sav', '.state', '.sqlite', '.nbi', '.nbc'}, name
        assert path.name != '.env', name
        assert not name.startswith(('pokesim/data/', 'pokesim/web/static/sprites/')), name
    print(f'{artifact.name}: runtime resources verified')
