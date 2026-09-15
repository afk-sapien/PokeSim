"""Install the release wheel in isolation and exercise its launcher and workers."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acceleration', action='store_true', help='Install and verify optional Numba support')
    args = parser.parse_args()
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    wheels = list((ROOT / 'dist').glob(f'pokesim-{version}-*.whl'))
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
        raise SystemExit('Run tools/prepare_test_data.py first or set GAME_DATA_DIR')
    environment['GAME_DATA_DIR'] = str(reference)
    with tempfile.TemporaryDirectory(prefix='pokesim-installed-') as temporary:
        root = Path(temporary)
        target = root / 'environment'
        subprocess.run([uv, 'venv', '--python', sys.executable, str(target)],
                       check=True, env=environment, cwd=root)
        executable = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        launcher = target / ('Scripts/pokesim-desktop.exe' if os.name == 'nt' else 'bin/pokesim-desktop')
        package = str(wheels[0]) + ('[acceleration]' if args.acceleration else '')
        subprocess.run([uv, 'pip', 'install', '--python', str(executable), package],
                       check=True, env=environment, cwd=root)
        if args.acceleration:
            subprocess.run([str(executable), '-c',
                'from pokesim.policies.navigation_numba import kernel\nassert kernel() is not None'],
                check=True, env=environment, cwd=root)
        subprocess.run([str(executable), str(ROOT / 'tools' / 'smoke_desktop.py'), str(launcher)],
                       check=True, env=environment, cwd=root, timeout=150)
        subprocess.run([str(executable), str(ROOT / 'tools' / 'check_python_runtime.py')],
                       check=True, env=environment, cwd=root, timeout=180)
    print('Fresh wheel installation passed outside the source checkout')


if __name__ == '__main__':
    main()
