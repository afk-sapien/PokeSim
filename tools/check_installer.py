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
    parser.add_argument('--workspace-pokecore', action='store_true',
                        help='Install pokecore built from packages/pokecore in place of its pinned release')
    args = parser.parse_args()
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    package = args.package or str(ROOT / 'dist' / f'pokesim-{version}-py3-none-any.whl')
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
            subprocess.run([sys.executable, str(ROOT / 'tools/smoke_desktop.py'), str(launcher)],
                           cwd=root, env=env, check=True, timeout=150)
    print('Installer passed: install, launch outside checkout, and repeat installation with spaces in paths')


if __name__ == '__main__':
    main()
