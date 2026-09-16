"""Verified, Git-free first-run setup for the desktop launcher."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import sys
import ssl
import tempfile
import zipfile
from urllib.request import urlopen

import certifi

from . import game_data
from .checkpoints import CheckpointStore

REFERENCE_URL = f'https://codeload.github.com/pret/pokered/zip/{game_data.SOURCE_REVISION}'
REFERENCE_SHA256 = 'd651b4495b353b1521b42494e635aae2ffe9c89c3609f8cf166975c0bc723fcc'
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_ROM = 1024 * 1024
ROM_NAMES = {
    'ea9bcae617fdf159b045185467ae58b2e4a48b9a': 'Pokémon Red',
    'd7037c83e1ae5b39bde3c30787637ba1d4c48ce2': 'Pokémon Blue (experimental)',
}


def user_directory():
    home = Path.home()
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local')) / 'PokeSim'
    if sys.platform == 'darwin':
        return home / 'Library' / 'Application Support' / 'PokeSim'
    base = Path(os.environ.get('XDG_DATA_HOME', home / '.local' / 'share'))
    if not base.is_absolute():
        base = home / '.local' / 'share'
    return base / 'pokesim'


def read_settings(root):
    path = root / 'settings.json'
    if not path.exists():
        return {'starter': 'random'}
    try:
        settings = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(settings, dict) or settings.get('starter') not in {
            'random', 'bulbasaur', 'charmander', 'squirtle'
        }:
            raise ValueError('Invalid starter')
        return settings
    except (ValueError, OSError) as error:
        raise ValueError(f'Cannot read {path}. Restore this file from a backup or rename it to use defaults.') from error


def install_rom(root, raw, starter):
    if starter not in {'random', 'bulbasaur', 'charmander', 'squirtle'}:
        raise ValueError('Choose one of the listed starters')
    if len(raw) > MAX_ROM or hashlib.sha1(raw).hexdigest() not in ROM_NAMES:
        raise ValueError('Choose a clean Pokémon Red or Blue (USA, Europe) .gb file. ZIP files and modified ROMs are not supported.')
    if (root / 'rom.gb').exists():
        raise ValueError('This adventure already has a ROM. Use a separate data folder for another adventure.')
    CheckpointStore.atomic_write(root / 'settings.json', json.dumps({'starter': starter}).encode())
    CheckpointStore.atomic_write(root / 'rom.gb', raw)


def prepare_archive(raw, destination):
    if len(raw) > MAX_ARCHIVE or hashlib.sha256(raw).hexdigest() != REFERENCE_SHA256:
        raise ValueError('Reference download failed verification. Retry setup with an unchanged reference archive.')
    from .prepare_data import generate_bundle
    prefix = f'pokered-{game_data.SOURCE_REVISION}'
    with tempfile.TemporaryDirectory(prefix='pokesim-reference-') as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            total = 0
            for info in archive.infolist():
                path = PurePosixPath(info.filename)
                total += info.file_size
                if (not path.parts or path.parts[0] != prefix or path.is_absolute()
                        or '..' in path.parts or '\\' in info.filename or total > 64 * 1024 * 1024):
                    raise ValueError('Invalid reference archive contents')
                target = root.joinpath(*path.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(info))
        return generate_bundle(root / prefix, destination, game_data.SOURCE_REVISION)


def ensure_game_data(destination, report, cancelled, archive_path=None):
    try:
        for name in game_data.FILES:
            game_data.load(name, directory=destination)
        return
    except RuntimeError:
        pass
    if archive_path:
        report('Preparing adventure data from your reference archive…')
        with Path(archive_path).open('rb') as stream:
            raw = stream.read(MAX_ARCHIVE + 1)
    else:
        report('Downloading reference data (about 2 MB)…')
        chunks = []
        total = 0
        context = ssl.create_default_context(cafile=os.environ.get('SSL_CERT_FILE') or certifi.where())
        with urlopen(REFERENCE_URL, timeout=30, context=context) as response:
            while chunk := response.read(65536):
                if cancelled.is_set():
                    return
                total += len(chunk)
                if total > MAX_ARCHIVE:
                    raise ValueError('Reference download is unexpectedly large')
                chunks.append(chunk)
        raw = b''.join(chunks)
    if cancelled.is_set():
        return
    report('Preparing maps and the Pokédex…')
    prepare_archive(raw, destination)
