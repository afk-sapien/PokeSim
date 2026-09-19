"""Verified shared ROMs and reference data, independent of adventure state."""
import hashlib
import shutil
import tempfile
from pathlib import Path
import threading

from ..checkpoints import CheckpointStore
from ..desktop_setup import MAX_ROM, ROM_NAMES, ensure_game_data
from .. import game_data


class Assets:
    def __init__(self, registry, game_data_dir=None, reference_archive=None):
        self.registry = registry
        self.root = registry.root / 'assets'
        self.reference_source = Path(game_data_dir).resolve() if game_data_dir else None
        self.game_data_dir = self.root / 'reference' / game_data.SOURCE_REVISION
        self.reference_archive = reference_archive
        self.guard = threading.Lock()
        self.cancelled = threading.Event()

    def install_rom(self, raw):
        sha1 = hashlib.sha1(raw).hexdigest()
        if len(raw) > MAX_ROM or sha1 not in ROM_NAMES:
            raise ValueError('Choose a clean Pokémon Red or Blue (USA, Europe) ROM')
        sha256 = hashlib.sha256(raw).hexdigest()
        path = self.root / 'roms' / sha256 / 'rom.gb'
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
                raise ValueError('Stored ROM verification failed')
        else:
            CheckpointStore.atomic_write(path, raw)
        version = 'blue' if 'Blue' in ROM_NAMES[sha1] else 'red'
        return self.registry.add_rom(sha256, sha1, version)

    def rom_path(self, rom_id):
        if rom_id not in {item['id'] for item in self.registry.roms()}:
            raise ValueError('Unknown ROM')
        path = self.root / 'roms' / rom_id / 'rom.gb'
        if hashlib.sha256(path.read_bytes()).hexdigest() != rom_id:
            raise ValueError('Stored ROM verification failed')
        return path

    def sprite_path(self, adventure_id, dex):
        if not 1 <= dex <= 151:
            return None
        directories = (self.registry.root / 'adventures' / adventure_id / 'sprites',
                       self.root / 'sprites')
        for directory in directories:
            root = directory.resolve()
            path = (root / f'{dex}.png').resolve()
            if path.parent == root and path.is_file():
                return path
        return None

    def prepare(self, report=lambda message: None):
        with self.guard:
            if self.reference_source and not self.game_data_dir.exists():
                for name in game_data.FILES:
                    game_data.load(name, directory=self.reference_source)
                self.game_data_dir.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='.reference-', dir=self.game_data_dir.parent) as temporary:
                    copied = Path(temporary) / 'bundle'
                    shutil.copytree(self.reference_source, copied)
                    copied.rename(self.game_data_dir)
            ensure_game_data(self.game_data_dir, report, self.cancelled, self.reference_archive)
            if self.cancelled.is_set():
                raise RuntimeError('Application setup was cancelled')
        return self.game_data_dir
