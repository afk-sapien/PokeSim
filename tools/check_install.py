"""Check the built packages, the installers and an installed PokeSim outside the source checkout.

Only the standard library loads at import. The smoke and runtime checks run under the installed Python,
and the container check mounts this file into the image to run the runtime check there.
"""
import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import tomllib
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
import zipfile

# parent.parent, not parents[1], so the file also loads from the root of a container.
ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / 'tools' / 'check_install.py'
REQUIRED = {
    'pokesim/cartridges.py',
    'pokesim/gen2/data.py',
    'pokesim/gen2/emulator.py',
    'pokesim/gen2/policy/__init__.py',
    'pokesim/gen2/policy/battle.py',
    'pokesim/gen2/policy/errands.py',
    'pokesim/gen2/policy/items.py',
    'pokesim/gen2/policy/menus.py',
    'pokesim/gen2/policy/navigation.py',
    'pokesim/gen2/policy/pins.py',
    'pokesim/gen2/policy/state.py',
    'pokesim/gen2/policy/storage.py',
    'pokesim/gen2/policy/story.py',
    'pokesim/gen2/save.py',
    'pokesim/gen2/steps.py',
    'pokesim/gen2/rewards.py',
    'pokesim/gen2/link_worker.py',
    'pokesim/gen2/trading.py',
    'pokesim/gen2/timecapsule.py',
    'pokesim/gen2/timecapsule_conversion.py',
    'pokesim/gen2/timecapsule_worker.py',
    'pokesim/gen2/timecapsule_records.py',
    'pokesim/gen2/ruins.py',
    'pokesim/gen2/tower.py',
    'pokesim/gen2/teams.py',
    'pokesim/gen2/celebi.py',
    'pokesim/gen2/contest.py',
    'pokesim/gen2/gamecorner.py',
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
    'pokesim/app/portrait_packs.py',
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
    'pokesim/web/static/trade-tabs.js',
    'pokesim/web/static/library.html',
    'pokesim/web/static/library.js',
    'pokesim/web/static/panel-library.css',
    'pokesim/desktop.py',
    'pokesim/desktop_setup.py',
    'pokesim/desktop_check.py',
    'pokesim/platform_io.py',
    'pokesim/web/static/desktop.html',
    'pokesim/web/static/desktop.js',
    'pokesim/web/static/panel-desktop.css',
    'pokesim/web/static/tokens.css',
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
    'pokesim/shiny.py',
    'pokesim/palettes.py',
    'pokesim/app/deletion.py',
    'pokesim/play_clock.py',
    'pokesim/web/static/index.html',
    'pokesim/web/static/journal.html',
    'pokesim/web/static/pc.html',
    'pokesim/web/static/pc.js',
    'pokesim/web/static/panel.css',
    'pokesim/web/static/panel.js',
    'pokesim/web/static/app.js',
    'pokesim/web/static/screen.js',
    'pokesim/web/static/audio-buffer.js',
    'pokesim/web/static/frame-delay.js',
    'pokesim/web/static/frame-stream.js',
    'pokesim/web/static/pokedex.html',
    'pokesim/web/static/pokedex.js',
    'pokesim/web/static/panel-pokedex.css',
    'pokesim/web/pokedex.py',
    'pokesim/healthcheck.py',
    'pokesim/prepare_data.py',
    'pokesim/checkpoints.py',
    'pokesim/web/feed.py',
    'pokesim/data_tools/strategy.py',
}


def version():
    return tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']


def package(args):
    """Verify runtime resources and exclude private artifacts from built packages."""
    release_version = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    artifacts = (list(Path('dist').glob(f'pokesim-{release_version}-*.whl'))
                 + list(Path('dist').glob(f'pokesim-{release_version}.tar.gz')))
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
                    'compose.build.yaml', 'compose.quickstart.yaml',
                    'install.sh', 'install.ps1',
                    'docs/README.md', 'docs/images/gen1-live.gif',
                    'docs/images/gen2-live.gif',
                    'docs/images/pc-panel.jpg', 'docs/images/pokedex-panel.jpg',
                    'docs/images/journal-panel.jpg', 'docs/images/stats-panel.jpg',
                    'docs/images/library.jpg',
                    'tools/check_web.py', 'tools/check_docs.py',
                    'docs/validation/README.md'} <= names
        missing = REQUIRED - names
        assert identity['version'] == release_version, f'{artifact}: build version mismatch'
        assert not missing, f'{artifact}: missing runtime files {missing}'
        for name in names:
            path = Path(name)
            assert path.suffix not in {'.gb', '.gbc', '.sav', '.state', '.sqlite', '.nbi', '.nbc'}, name
            assert path.name != '.env', name
            assert not name.startswith(('pokesim/data/', 'pokesim/web/static/sprites/')), name
        print(f'{artifact.name}: runtime resources verified')


def installer(args):
    """Exercise the user-facing installer twice in disposable tool directories."""
    package = args.package or str(ROOT / 'dist' / f'pokesim-{version()}-py3-none-any.whl')
    with (tempfile.TemporaryDirectory(prefix='pokesim installer ') as temporary,
          tempfile.TemporaryDirectory(prefix='pokesim-workspace-pokecore-') as workspace):
        root = Path(temporary)
        bin_dir = root / 'commands with spaces'
        env = {**os.environ, 'UV_TOOL_DIR': str(root / 'tools'), 'UV_TOOL_BIN_DIR': str(bin_dir),
               'POKESIM_INSTALL_PACKAGE': package}
        env.pop('PYTHONPATH', None)
        env.pop('VIRTUAL_ENV', None)
        if args.workspace_pokecore:
            # The installer runs uv tool install, which reads overrides from UV_OVERRIDE. uv splits that
            # variable at spaces, so the file sits outside the test folder, whose name has spaces on purpose.
            built = Path(workspace)
            subprocess.run(['uv', 'build', '--package', 'pokecore', '--wheel', '--out-dir', str(built)],
                           check=True, cwd=ROOT)
            wheel, = built.glob('pokecore-*.whl')
            overrides = built / 'overrides.txt'
            overrides.write_text(f'pokecore @ {wheel.as_uri()}\n', encoding='utf-8')
            env['UV_OVERRIDE'] = str(overrides)
        if sys.platform == 'win32':
            command = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                       '-File', str(ROOT / 'install.ps1')]
            launcher = bin_dir / 'pokesim-desktop.exe'
        else:
            command = ['sh', str(ROOT / 'install.sh')]
            launcher = bin_dir / 'pokesim-desktop'
        for attempt in range(2):
            subprocess.run(command, cwd=root, env=env, check=True, timeout=300)
            subprocess.run([sys.executable, str(TOOL), 'smoke', str(launcher)],
                           cwd=root, env=env, check=True, timeout=150)
    print('Installer passed: install, launch outside checkout, and repeat installation with spaces in paths')


def python_install(args):
    """Install the release wheel in isolation and exercise its launcher and workers."""
    wheels = list((ROOT / 'dist').glob(f'pokesim-{version()}-*.whl'))
    if len(wheels) != 1:
        raise SystemExit('Build exactly one current wheel with uv build first')
    uv = shutil.which('uv')
    if uv is None:
        raise SystemExit('Install uv before running the isolated package check')
    environment = os.environ.copy()
    environment.pop('PYTHONPATH', None)
    environment.pop('PYTHONHOME', None)
    environment.pop('VIRTUAL_ENV', None)
    environment['PYTHONNOUSERSITE'] = '1'
    reference = Path(environment.get('GAME_DATA_DIR', ROOT / 'data' / 'game-data')).resolve()
    if not (reference / 'current.json').is_file():
        raise SystemExit('Run tools/check_install.py prepare-data first or set GAME_DATA_DIR')
    environment['GAME_DATA_DIR'] = str(reference)
    with tempfile.TemporaryDirectory(prefix='pokesim-installed-') as temporary:
        root = Path(temporary)
        target = root / 'environment'
        subprocess.run([uv, 'venv', '--python', sys.executable, str(target)],
                       check=True, env=environment, cwd=root)
        executable = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        launcher = target / ('Scripts/pokesim-desktop.exe' if os.name == 'nt' else 'bin/pokesim-desktop')
        package = str(wheels[0]) + ('[acceleration]' if args.acceleration else '')
        dependencies = [path.resolve() for path in args.dependency_wheel]
        if args.workspace_pokecore:
            subprocess.run([uv, 'build', '--package', 'pokecore', '--wheel', '--out-dir', str(root / 'pokecore')],
                           check=True, cwd=ROOT)
            dependencies += sorted((root / 'pokecore').glob('pokecore-*.whl'))
        install = [uv, 'pip', 'install', '--python', str(executable)]
        if dependencies:
            # An override replaces the pinned release URL, which a second wheel of the same name would conflict with.
            overrides = root / 'overrides.txt'
            overrides.write_text(''.join(f'{wheel.name.split("-")[0]} @ {wheel.as_uri()}\n' for wheel in dependencies),
                                 encoding='utf-8')
            install += ['--override', str(overrides)]
        subprocess.run([*install, package, *map(str, dependencies)], check=True, env=environment, cwd=root)
        if args.acceleration:
            subprocess.run([str(executable), '-c',
                'from pokesim.policies.navigation_numba import kernel\nassert kernel() is not None'],
                check=True, env=environment, cwd=root)
        subprocess.run([str(executable), str(TOOL), 'smoke', str(launcher)],
                       check=True, env=environment, cwd=root, timeout=150)
        subprocess.run([str(executable), str(TOOL), 'runtime'],
                       check=True, env=environment, cwd=root, timeout=180)
    print('Fresh wheel installation passed outside the source checkout')


def installed_wheel(args):
    """Install the wheel into a fresh environment and launch it outside the checkout."""
    wheel = ROOT / 'dist' / f'pokesim-{version()}-py3-none-any.whl'
    with tempfile.TemporaryDirectory(prefix='pokesim-wheel-') as temporary:
        root = Path(temporary)
        environment = root / 'environment'
        subprocess.run(['uv', 'venv', '--python', '3.12', str(environment)], check=True)
        executable = environment / 'bin' / 'pokesim-desktop'
        python = environment / 'bin' / 'python'
        subprocess.run(['uv', 'pip', 'install', '--python', str(python), str(wheel)],
                       cwd=root, check=True, timeout=180)
        subprocess.run([str(python), str(TOOL), 'smoke', str(executable)],
                       cwd=root, check=True, timeout=150)
    print('Installed wheel launcher passed outside the source checkout')


def runtime(args):
    """Check installed Python workers and real child-process supervision using PyBoy's demo."""
    os.environ.setdefault('POKESIM_WORKER_STACK_DUMP', '30')
    import httpx
    from pokecore import emulator as pyboy
    from pokesim.app.supervisor import Child
    from pokesim import game_data
    reference = game_data.directory().resolve()
    for name in game_data.FILES:
        game_data.load(name, directory=reference)
    demo = pyboy.demo_rom().resolve()
    with tempfile.TemporaryDirectory(prefix='pokesim-python-workers-') as temporary:
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
                child = Child(bootstrap, command=[sys.executable, '-m', 'pokesim.runtime.worker'])
                children.append(child)
                child.start(timeout=45)
                with httpx.Client(trust_env=False, timeout=5) as client:
                    assert client.get(child.url + '/internal/health').status_code == 401
                    response = client.get(child.url + '/internal/health',
                        headers={'Authorization': 'Bearer ' + child.token})
                    response.raise_for_status()
                    assert response.json()['adventure_id'] == bootstrap['adventure_id']
            assert children[0].process.pid != children[1].process.pid
            for child in children:
                for pace in (0, 1, 16):
                    assert child.request('POST', '/internal/speed', {'speed': pace}) == {'speed': pace}
                    assert child.request('GET', '/api/state')['speed'] == pace
                with httpx.Client(trust_env=False, timeout=5) as client:
                    assert client.post(child.url + '/internal/speed', json={'speed': 0}).status_code == 401
                    response = client.post(child.url + '/api/control', json={'action': 'speed', 'value': 0},
                        headers={'Authorization': 'Bearer ' + child.token})
                    assert response.status_code == 409
            for number, child in enumerate(children):
                child.process.stdin.close()
                child.process.wait(timeout=30)
                assert child.process.returncode == 0, list(child.logs)
                assert list((root / str(number) / 'states').glob('*.state'))
        finally:
            for child in children:
                child.stop(timeout=5)
    print('Installed Python workers passed: two independent processes, private credentials, parent-loss saves and exit')


def smoke(args):
    """Exercise the installed library launcher without a Pokémon ROM."""
    cookies = CookieJar()
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
    with tempfile.TemporaryDirectory(prefix='pokesim-smoke-', ignore_cleanup_errors=True) as temporary:
        root = Path(temporary)
        command = [*args.launch, '--no-browser', '--data-dir', str(root)]
        with (root / 'process.log').open('w', encoding='utf-8') as output:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 60
                while True:
                    if process.poll() is not None:
                        raise RuntimeError((root / 'process.log').read_text(encoding='utf-8'))
                    try:
                        identity = json.loads((root / 'manager.json').read_text(encoding='utf-8'))
                        url = identity['url']
                        with opener.open(url + '/health/ready', timeout=1) as response:
                            assert json.load(response)['ok']
                        break
                    except (OSError, ValueError, URLError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Library did not become ready')
                        time.sleep(0.1)
                with opener.open(url) as response:
                    assert b'Your adventure library' in response.read()
                for path in ('/static/library.js', '/static/tokens.css',
                             '/static/panel.css', '/static/panel-library.css'):
                    with opener.open(url + path) as response:
                        assert response.status == 200
                with opener.open(url + '/api/v1/session') as response:
                    session = json.load(response)
                assert session['csrf_token']
                assert list(cookies), 'Session endpoint did not set a cookie'
                assert not (root / 'owner.token').exists()
                try:
                    opener.open(Request(url + '/api/v1/shutdown', data=b'{}', method='POST'))
                    raise AssertionError('Shutdown without CSRF protection was allowed')
                except HTTPError as error:
                    assert error.code in (401, 403)
                second = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                assert second.returncode == 0, second.stderr
                with opener.open(Request(url + '/api/v1/shutdown', data=b'{}', method='POST',
                                 headers={'X-PokeSim-CSRF': session['csrf_token'],
                                          'Origin': url, 'Content-Type': 'application/json'})) as response:
                    assert json.load(response)['ok']
                assert process.wait(timeout=90) == 0
                print('Python launcher smoke passed: keyless library, assets, duplicate launch, CSRF-protected shutdown, clean exit')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


def prepare_data(args):
    """Test the verified application data preparation path without Git or a ROM."""
    from pokesim.desktop_setup import ensure_game_data
    ensure_game_data(Path('data/game-data'), print, threading.Event())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name, run in (('package', package), ('installed-wheel', installed_wheel),
                      ('runtime', runtime), ('prepare-data', prepare_data)):
        commands.add_parser(name, help=run.__doc__, description=run.__doc__).set_defaults(run=run)
    check = commands.add_parser('installer', help=installer.__doc__, description=installer.__doc__)
    check.add_argument('--package', help='Wheel path or URL, defaults to the current built wheel')
    check.add_argument('--workspace-pokecore', action='store_true',
                       help='Install pokecore built from packages/pokecore in place of its pinned release')
    check.set_defaults(run=installer)
    check = commands.add_parser('python-install', help=python_install.__doc__, description=python_install.__doc__)
    check.add_argument('--acceleration', action='store_true', help='Install and verify optional Numba support')
    check.add_argument('--dependency-wheel', type=Path, action='append', default=[],
                       help='Explicit local dependency wheel for unreleased stack validation')
    check.add_argument('--workspace-pokecore', action='store_true',
                       help='Install pokecore built from packages/pokecore in place of its pinned release')
    check.set_defaults(run=python_install)
    launch = commands.add_parser('smoke', help=smoke.__doc__, description=smoke.__doc__)
    launch.add_argument('launch', nargs=argparse.REMAINDER)
    launch.set_defaults(run=smoke)
    args = parser.parse_args()
    if args.command == 'smoke' and not args.launch:
        launch.error('Supply pokesim-desktop or python -m pokesim.desktop')
    args.run(args)


if __name__ == '__main__':
    main()
