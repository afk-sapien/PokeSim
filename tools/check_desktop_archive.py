"""Extract and test the desktop archive users will download."""
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    name = f'PokeSim-{platform.system().lower()}-{platform.machine().lower()}'
    extension = '.tar.gz' if sys.platform.startswith('linux') else '.zip'
    archive = ROOT / 'dist' / 'desktop' / (name + extension)
    with tempfile.TemporaryDirectory(prefix='pokesim-download-') as temporary:
        destination = Path(temporary)
        if sys.platform == 'darwin':
            subprocess.run(['ditto', '-x', '-k', str(archive), str(destination)], check=True)
            executable = destination / 'PokeSim.app' / 'Contents' / 'MacOS' / 'PokeSim'
        elif sys.platform == 'win32':
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(destination)
            executable = destination / 'PokeSim' / 'PokeSim.exe'
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(destination, filter='data')
            executable = destination / 'PokeSim' / 'PokeSim'
        subprocess.run([sys.executable, str(ROOT / 'tools' / 'smoke_desktop.py'), str(executable)],
                       cwd=destination, check=True, timeout=150)
        subprocess.run([str(executable), '--check-runtime'], cwd=destination, check=True, timeout=180)
    print(f'Downloaded archive layout and runtime passed: {archive.name}')


if __name__ == '__main__':
    main()
