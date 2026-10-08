"""Verified shared ROMs and reference data, independent of adventure state."""
import hashlib
import logging
import shutil
import tempfile
from pathlib import Path
import threading

from ..checkpoints import CheckpointStore
from ..desktop_setup import MAX_ROM, ROM_NAMES, ensure_game_data
from .. import game_data

log = logging.getLogger(__name__)


class Assets:
    def __init__(self, registry, game_data_dir=None, reference_archive=None):
        self.registry = registry
        self.root = registry.root / 'assets'
        self.reference_source = Path(game_data_dir).resolve() if game_data_dir else None
        self.game_data_dir = self.root / 'reference' / game_data.SOURCE_REVISION
        self.reference_archive = reference_archive
        self.guard = threading.Lock()
        self.cancelled = threading.Event()
        from .portrait_packs import PortraitPacks
        self.portraits = PortraitPacks(registry, self.cancelled)
        from .item_artwork import IMAGES
        self.item_artwork = PortraitPacks(registry, self.cancelled, images=IMAGES,
                                         folder='/sprites/items/', pack='item-artwork', setting='item_artwork')

    def install_rom(self, raw):
        from ..cartridges import identify, unpack
        if len(raw) > MAX_ROM:
            raise ValueError('The cartridge file is too large')
        if raw[:4] == b'PK\x03\x04':
            raw = unpack(raw)
        cartridge = identify(raw)
        sha1 = hashlib.sha1(raw).hexdigest()
        if len(raw) > MAX_ROM or sha1 not in ROM_NAMES:
            raise ValueError('Choose a clean supported Red, Blue, Gold, Silver or Crystal ROM')
        sha256 = hashlib.sha256(raw).hexdigest()
        path = self.root / 'roms' / sha256 / 'rom.gb'
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
                raise ValueError('Stored ROM verification failed')
        else:
            CheckpointStore.atomic_write(path, raw)
        version = cartridge.version if cartridge else ROM_NAMES[sha1].split()[1].lower()
        return self.registry.add_rom(sha256, sha1, version)

    def install_portraits(self, raw) -> int:
        """Decode the 151 front portraits out of the cartridge the owner just supplied.

        The artwork is in their own ROM, so nothing is shipped and nothing is downloaded.
        An existing file is never replaced, so a hand-installed pack still wins.
        """
        from ..cartridges import identify
        cartridge = identify(raw)
        if cartridge and cartridge.generation == 2:
            from ..gen2.sprites import install
            return install(raw, self.game_data_dir, self.root / 'sprites' / cartridge.version, cartridge.version)
        from ..sprites import extract
        data = game_data.load('strategy.json', directory=self.game_data_dir)
        species = {int(key): value for key, value in data['species'].items()}

        directory = self.root / 'sprites'
        directory.mkdir(parents=True, exist_ok=True)
        written = 0
        try:
            portraits = extract(bytes(raw), species)
        except Exception:
            log.exception('Could not read portraits from this ROM; the placeholder stays in use')
            return 0
        for dex, png in portraits.items():
            path = directory / f'{dex}.png'
            if path.exists():
                continue
            try:
                CheckpointStore.atomic_write(path, png)
                written += 1
            except OSError:
                log.exception('Could not write the portrait for %s', dex)
                break
        if written:
            log.info('extracted %d portraits from the cartridge', written)
        return written

    def rom_path(self, rom_id):
        if rom_id not in {item['id'] for item in self.registry.roms()}:
            raise ValueError('Unknown ROM')
        path = self.root / 'roms' / rom_id / 'rom.gb'
        if hashlib.sha256(path.read_bytes()).hexdigest() != rom_id:
            raise ValueError('Stored ROM verification failed')
        return path

    def sprite_path(self, adventure_id, dex):
        if not 1 <= dex <= 251:
            return None
        adventure = self.registry.adventure(adventure_id)
        if adventure['version'] in {'gold', 'silver', 'crystal'}:
            path = self.root / 'sprites' / adventure['version'] / f'{dex}.png'
            return path if path.is_file() else None
        community = self.portraits.path(dex)
        if community is not None:
            return community
        directories = (self.registry.root / 'adventures' / adventure_id / 'sprites',
                       self.root / 'sprites')
        for directory in directories:
            root = directory.resolve()
            path = (root / f'{dex}.png').resolve()
            if path.parent == root and path.is_file():
                return path
        return None

    def prepare_gen2(self, version, report=lambda message: None):
        from ..gen2.data import GameData, ensure, write_bundle
        with self.guard:
            if self.reference_source:
                try:
                    data = GameData.load(self.reference_source, version)
                except (OSError, ValueError):
                    pass
                else:
                    write_bundle(self.game_data_dir, version, data.raw)
            ensure(self.game_data_dir, version, report)
            # The shared store and tables still read the Gen I reference tables, so a library
            # that only holds Gen II adventures needs them prepared too.
            self._prepare_gen1(report)
            if self.cancelled.is_set():
                raise RuntimeError('Application setup was cancelled')

    def _has_gen1_data(self):
        try:
            for name in game_data.FILES:
                game_data.load(name, directory=self.game_data_dir)
        except RuntimeError:
            return False
        return True

    def _adopt_reference(self):
        """Copy the verified Gen I reference bundle, even into a folder that already holds Gen II data."""
        try:
            for name in game_data.FILES:
                game_data.load(name, directory=self.reference_source)
        except RuntimeError:
            return  # a reference without Gen I tables: they are downloaded below instead
        self.game_data_dir.parent.mkdir(parents=True, exist_ok=True)
        if not self.game_data_dir.exists():
            with tempfile.TemporaryDirectory(prefix='.reference-', dir=self.game_data_dir.parent) as temporary:
                copied = Path(temporary) / 'bundle'
                shutil.copytree(self.reference_source, copied)
                copied.rename(self.game_data_dir)
            return
        bundle = game_data.bundle_path(self.reference_source)
        destination = self.game_data_dir / 'bundles' / bundle.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.reference-', dir=destination.parent) as temporary:
            copied = Path(temporary) / 'bundle'
            shutil.copytree(bundle, copied)
            if destination.exists():
                shutil.rmtree(destination)
            copied.rename(destination)
        CheckpointStore.atomic_write(self.game_data_dir / 'current.json', (self.reference_source / 'current.json').read_bytes())

    def _prepare_gen1(self, report):
        if self.reference_source and not self._has_gen1_data():
            self._adopt_reference()
        ensure_game_data(self.game_data_dir, report, self.cancelled, self.reference_archive)

    def prepare(self, report=lambda message: None):
        with self.guard:
            self._prepare_gen1(report)
            if self.cancelled.is_set():
                raise RuntimeError('Application setup was cancelled')
        return self.game_data_dir
