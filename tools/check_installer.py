"""Exercise the user-facing installer twice in disposable tool directories."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', help='Wheel path or URL, defaults to the current built wheel')
    args = parser.parse_args()
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    package = args.package or str(ROOT / 'dist' / f'pokesim-{version}-py3-none-any.whl')
    with tempfile.TemporaryDirectory(prefix='pokesim installer ') as temporary:
        root = Path(temporary)
        bin_dir = root / 'commands with spaces'
        env = {**os.environ, 'UV_TOOL_DIR': str(root / 'tools'), 'UV_TOOL_BIN_DIR': str(bin_dir),
               'POKESIM_INSTALL_PACKAGE': package}
        env.pop('PYTHONPATH', None)
        env.pop('VIRTUAL_ENV', None)
        if sys.platform == 'win32':
            command = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                       '-File', str(ROOT / 'install.ps1')]
            launcher = bin_dir / 'pokesim-desktop.exe'
        else:
            command = ['sh', str(ROOT / 'install.sh')]
            launcher = bin_dir / 'pokesim-desktop'
        for attempt in range(2):
            subprocess.run(command, cwd=root, env=env, check=True, timeout=300)
            subprocess.run([sys.executable, str(ROOT / 'tools/smoke_desktop.py'), str(launcher)],
                           cwd=root, env=env, check=True, timeout=150)
    print('Installer passed: install, launch outside checkout, and repeat installation with spaces in paths')


if __name__ == '__main__':
    main()
