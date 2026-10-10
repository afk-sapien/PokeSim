"""Verified shared ROMs and reference data, independent of adventure state."""
import hashlib
import logging
import shutil
import tempfile
from pathlib import Path
import threading

from ..checkpoints import CheckpointStore
from ..downloads import retrying
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
        self.portraits = PortraitPacks.portraits(registry, self.cancelled)
        from .item_artwork import IMAGES
        self.item_artwork = PortraitPacks(registry, self.cancelled, images=IMAGES,
                                         folder='/sprites/items/', pack='item-artwork', setting='item_artwork')

    def install_rom(self, raw):
        return self.add_cartridge(raw)['rom']

    def add_cartridge(self, raw, slot=None):
        """Verify an uploaded cartridge, store it once and file it under the game it really is.

        `slot` is only the shelf slot the owner aimed at. The hash decides where the cartridge
        goes, and the result says so when the two differ.
        """
        from ..cartridges import SLOT_TITLES, identify, unsupported_message, unpack
        if slot is not None and slot not in SLOT_TITLES:
            raise ValueError('Unknown cartridge slot')
        if len(raw) > MAX_ROM:
            raise ValueError('The cartridge file is too large. Game Boy ROMs are at most 2 MB.')
        if not raw:
            raise ValueError('The chosen file is empty. Choose your .gb, .gbc or .zip ROM file.')
        if raw[:4] == b'PK\x03\x04':
            raw = unpack(raw)
        cartridge = identify(raw)
        sha1 = hashlib.sha1(raw).hexdigest()
        if len(raw) > MAX_ROM or (cartridge is None and sha1 not in ROM_NAMES):
            raise ValueError(unsupported_message())
        version = cartridge.version if cartridge else ROM_NAMES[sha1].split()[1].lower()
        sha256 = hashlib.sha256(raw).hexdigest()
        path = self.root / 'roms' / sha256 / 'rom.gb'
        path.parent.mkdir(parents=True, exist_ok=True)
        known = sha256 in {row['id'] for row in self.registry.roms()}
        if not path.exists():
            status = 'repaired' if known else 'added'
            CheckpointStore.atomic_write(path, raw)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
            # The upload was verified above, so it can safely replace a damaged stored copy.
            status = 'repaired'
            CheckpointStore.atomic_write(path, raw)
        else:
            status = 'same' if known else 'added'
        rom = self.registry.add_rom(sha256, sha1, version)
        title = SLOT_TITLES.get(version, f'Pokémon {version.capitalize()}')
        moved = slot is not None and slot != version
        if moved:
            message = f'That file is {title}, not {SLOT_TITLES[slot]}, so it went into the {version.capitalize()} slot.'
        elif status == 'same':
            message = f'{title} is already installed. The file you chose is the same verified cartridge, so nothing changed.'
        elif status == 'repaired':
            message = f'{title} was checked and its stored copy replaced.'
        else:
            message = f'{title} added. It is ready for new adventures.'
        return {'rom': rom, 'version': version, 'title': title, 'requested': slot, 'moved': moved,
                'status': status, 'message': message, 'raw': raw}

    def cartridge_slots(self):
        """One entry per shelf slot: what is installed there and which adventures use it."""
        from ..cartridges import CARTRIDGES, SLOT_GENERATIONS, SLOT_TITLES, SLOTS, supported_versions
        supported = set(supported_versions())
        starters = {cartridge.version: list(cartridge.starters) for cartridge in CARTRIDGES}
        rows = self.registry.roms()
        adventures = self.registry.adventures()
        versions = list(SLOTS) + sorted({row['version'] for row in rows} - set(SLOTS))
        slots = []
        for version in versions:
            stored = [row for row in rows if row['version'] == version]
            ids = {row['id'] for row in stored}
            rom = None
            for row in stored:
                path = self.root / 'roms' / row['id'] / 'rom.gb'
                try:
                    stat = path.stat()
                except OSError:
                    stat = None
                candidate = {'id': row['id'], 'sha1': row['sha1'], 'short_hash': row['sha1'][:8],
                             'size': stat.st_size if stat else None, 'added_at': stat.st_mtime if stat else None,
                             'file_missing': stat is None}
                if rom is None or (rom['file_missing'] and stat is not None):
                    rom = candidate
            slots.append({
                'version': version,
                'title': SLOT_TITLES.get(version, f'Pokémon {version.capitalize()}'),
                'generation': SLOT_GENERATIONS.get(version),
                'supported': version in supported or bool(stored),
                'starters': starters.get(version, []),
                'installed': rom is not None,
                'rom': rom,
                'adventures': [{'id': game['id'], 'name': game['name'], 'archived': game['archived']}
                               for game in adventures if game['rom_id'] in ids],
            })
        return slots

    def remove_cartridge(self, version):
        """Forget a cartridge and delete its stored file, unless an adventure still plays it."""
        from ..cartridges import SLOT_TITLES
        title = SLOT_TITLES.get(version, f'Pokémon {version.capitalize()}')
        with self.registry.lock:
            ids = [row['id'] for row in self.registry.roms() if row['version'] == version]
            if not ids:
                raise KeyError(f'No {title} cartridge is installed')
            users = [game for game in self.registry.adventures() if game['rom_id'] in ids]
            if users:
                names = ', '.join(game['name'] + (' (archived)' if game['archived'] else '') for game in users)
                count = 'adventure uses' if len(users) == 1 else f'{len(users)} adventures use'
                raise ValueError(f'{title} cannot be removed because this {count} it: {names}. '
                                 'Delete those adventures first. Archived adventures count, since they can be restored.')
            self.registry.remove_roms(ids)
        for rom_id in ids:
            shutil.rmtree(self.root / 'roms' / rom_id, ignore_errors=True)
        return {'version': version, 'title': title, 'message': f'{title} removed. Add it again at any time.'}

    def install_portraits_quietly(self, raw):
        """Extract portraits right after an upload when the reference data is already prepared.

        Starting an adventure extracts them anyway, so a library without reference data yet
        simply waits for that.
        """
        try:
            return self.install_portraits(raw)
        except Exception as error:
            log.info('Portraits will be extracted when an adventure starts: %s', error)
            return 0

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
        yellow = cartridge is not None and cartridge.version == 'yellow'
        data = game_data.load('strategy.json', directory=self.game_data_dir, variant='yellow' if yellow else 'red')
        species = {int(key): value for key, value in data['species'].items()}

        # Yellow redraws most portraits, so they never mix with Red and Blue artwork.
        directory = self.root / 'sprites' / 'yellow' if yellow else self.root / 'sprites'
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
        """The portrait an adventure shows for `dex`.

        A hand-installed image in the adventure's own `sprites` folder wins. Next comes the
        community pack set for the adventure's version when the owner installed and enabled
        it, then the portraits extracted from the owner's own cartridge (per version, with the
        shared Generation I folder last).
        """
        if not 1 <= dex <= 251:
            return None
        adventure = self.registry.adventure(adventure_id)
        version = adventure['version']
        override = self._contained(self.registry.root / 'adventures' / adventure_id / 'sprites', dex)
        if override is not None:
            return override
        community = self.portraits.path(dex, version=version)
        if community is not None:
            return community
        path = self.root / 'sprites' / version / f'{dex}.png'
        if path.is_file():
            return path
        # Yellow redraws most portraits, so it never falls back to the shared Red and Blue folder.
        if version in {'yellow', 'gold', 'silver', 'crystal'}:
            return None
        return self._contained(self.root / 'sprites', dex)

    @staticmethod
    def _contained(directory, dex):
        root = directory.resolve()
        path = (root / f'{dex}.png').resolve()
        return path if path.parent == root and path.is_file() else None

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
                game_data.load(name, directory=self.game_data_dir, variant='red')
        except RuntimeError:
            return False
        return True

    def _adopt_reference(self):
        """Copy the verified Gen I reference bundle, even into a folder that already holds Gen II data."""
        try:
            for name in game_data.FILES:
                game_data.load(name, directory=self.reference_source, variant='red')
        except RuntimeError:
            return  # a reference without Gen I tables: they are downloaded below instead
        self.game_data_dir.parent.mkdir(parents=True, exist_ok=True)
        if not self.game_data_dir.exists():
            with tempfile.TemporaryDirectory(prefix='.reference-', dir=self.game_data_dir.parent) as temporary:
                copied = Path(temporary) / 'bundle'
                shutil.copytree(self.reference_source, copied)
                copied.rename(self.game_data_dir)
            return
        bundle = game_data.bundle_path(self.reference_source, 'red')
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
        retrying(lambda: ensure_game_data(self.game_data_dir, report, self.cancelled, self.reference_archive),
                 'Pokémon', report)

    def prepare(self, report=lambda message: None, version=None):
        with self.guard:
            self._prepare_gen1(report)
            if version == 'yellow':
                self._prepare_yellow(report)
            if self.cancelled.is_set():
                raise RuntimeError('Application setup was cancelled')
        return self.game_data_dir

    def _prepare_yellow(self, report):
        """Prepare Yellow maps, trainers and Pokédex data beside the shared Red and Blue data."""
        if self.reference_source:
            try:
                for name in game_data.FILES:
                    game_data.load(name, directory=self.reference_source, variant='yellow')
            except RuntimeError:
                pass
            else:
                source = game_data.variant_root(self.reference_source, 'yellow')
                target = game_data.variant_root(self.game_data_dir, 'yellow')
                bundle = game_data.bundle_path(self.reference_source, 'yellow')
                destination = target / 'bundles' / bundle.name
                if not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryDirectory(prefix='.reference-', dir=destination.parent) as temporary:
                        copied = Path(temporary) / 'bundle'
                        shutil.copytree(bundle, copied)
                        copied.rename(destination)
                CheckpointStore.atomic_write(target / 'current.json', (source / 'current.json').read_bytes())
        retrying(lambda: ensure_game_data(self.game_data_dir, report, self.cancelled, variant='yellow'),
                 'Pokémon Yellow', report)
