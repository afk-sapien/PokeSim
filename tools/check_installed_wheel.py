"""Install the wheel into a fresh environment and launch it outside the checkout."""
from pathlib import Path
import subprocess
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def main():
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    wheel = ROOT / 'dist' / f'pokesim-{version}-py3-none-any.whl'
    with tempfile.TemporaryDirectory(prefix='pokesim-wheel-') as temporary:
        root = Path(temporary)
        environment = root / 'environment'
        subprocess.run(['uv', 'venv', '--python', '3.12', str(environment)], check=True)
        executable = environment / 'bin' / 'pokesim-desktop'
        python = environment / 'bin' / 'python'
        subprocess.run(['uv', 'pip', 'install', '--python', str(python), str(wheel)],
                       cwd=root, check=True, timeout=180)
        subprocess.run([str(python), str(ROOT / 'tools' / 'smoke_desktop.py'), str(executable)],
                       cwd=root, check=True, timeout=150)
    print('Installed wheel launcher passed outside the source checkout')


if __name__ == '__main__':
    main()
