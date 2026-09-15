"""Build a desktop download for the current operating system and architecture."""
from pathlib import Path
import platform
import hashlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / 'dist' / 'desktop'
    work = ROOT / 'build' / 'desktop'
    notices = work / 'notices'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / 'tools' / 'bundle_dependency_sources.py'), str(notices)],
                   cwd=ROOT, check=True)
    source = notices / 'source' / 'pokesim'
    if source.exists():
        shutil.rmtree(source)
    shutil.copytree(ROOT / 'pokesim', source,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'data', 'sprites',
                                                 '*.gb', '*.gbc', '*.sav', '*.state', '*.sqlite*'))
    assets = work / 'assets'
    if assets.exists():
        shutil.rmtree(assets)
    for relative in ['web/static', 'broker/static']:
        target = assets / relative
        target.mkdir(parents=True, exist_ok=True)
        for path in (ROOT / 'pokesim' / relative).iterdir():
            if path.is_file() and path.suffix in {'.html', '.css', '.js'}:
                shutil.copy2(path, target / path.name)
    for name in ['LICENSE', 'THIRD_PARTY_NOTICES.md', 'pyproject.toml', 'uv.lock']:
        shutil.copy2(ROOT / name, notices / 'source' / name)
    shutil.copytree(ROOT / 'licenses', notices / 'licenses' / 'project', dirs_exist_ok=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--noupx',
               '--name', 'PokeSim', '--onedir', '--distpath', str(output), '--workpath', str(work / 'pyinstaller'),
               '--specpath', str(work), '--paths', str(ROOT),
               '--add-data', f'{assets / "web/static"}:pokesim/web/static',
               '--add-data', f'{assets / "broker/static"}:pokesim/broker/static',
               '--collect-all', 'pyboy', '--collect-all', 'sdl2', '--collect-all', 'sdl2dll',
               '--exclude-module', 'pyboy.conftest', '--exclude-module', 'pytest',
               '--recursive-copy-metadata', 'pokesim', '--collect-submodules', 'uvicorn',
               '--add-data', f'{notices}:notices']
    if sys.platform in {'win32', 'darwin'}:
        command.append('--windowed')
    if sys.platform == 'darwin':
        command.extend(['--osx-bundle-identifier', 'io.github.afk-sapien.pokesim'])
    command.append(str(ROOT / 'tools' / 'desktop_entry.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    folder = output / ('PokeSim.app' if sys.platform == 'darwin' else 'PokeSim')
    if sys.platform != 'darwin':
        shutil.copy2(ROOT / 'docs' / 'desktop.md', folder / 'README.md')
    name = f'PokeSim-{platform.system().lower()}-{platform.machine().lower()}'
    if sys.platform == 'darwin':
        # ditto preserves executable permissions and bundle symlinks.
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(folder),
                        str(output / f'{name}.zip')], check=True)
    else:
        extension = 'zip' if sys.platform == 'win32' else 'gztar'
        shutil.make_archive(str(output / name), extension, root_dir=output, base_dir=folder.name)
    for archive in output.glob(f'{name}.*'):
        if archive.name.endswith(('.zip', '.tar.gz')):
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            archive.with_name(archive.name + '.sha256').write_text(f'{digest}  {archive.name}\n')
    print(f'Desktop download created in {output}')


if __name__ == '__main__':
    main()
