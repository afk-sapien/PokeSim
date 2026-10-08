"""Optional owner-requested artwork downloads, separate from cartridge artwork.

A pack holds one or more sets, each a folder of the pinned PokeAPI/sprites tree. The
portrait pack holds one set per supported game so every adventure can show the artwork
of its own version. Downloads are staged in a resumable `.install-` folder (excluded
from backups) and the pack only becomes visible once every set is complete.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
import logging
import posixpath
import shutil
import threading

import httpx
from PIL import Image

from ..checkpoints import CheckpointStore

REVISION = 'bfb75391935310368065096fa08c51e8970bc43e'
SOURCE = 'https://github.com/PokeAPI/sprites/tree/' + REVISION
RAW = 'https://raw.githubusercontent.com/PokeAPI/sprites/' + REVISION
VERSIONS = '/sprites/pokemon/versions/'
FOLDER = VERSIONS + 'generation-i/red-blue/transparent/'
MAX_IMAGE_BYTES = 128 * 1024
MAX_PACK_BYTES = 48 * 1024 * 1024
WORKERS = 4
GEN1 = {dex: f'{dex}.png' for dex in range(1, 152)}
GEN2 = {dex: f'{dex}.png' for dex in range(1, 252)}
# Set name -> (folder at the pinned revision, {key: upstream file name}).
PORTRAIT_SETS = {
    'red-blue': (FOLDER, GEN1),
    'yellow': (VERSIONS + 'generation-i/yellow/transparent/', GEN1),
    'gold': (VERSIONS + 'generation-ii/gold/transparent/', GEN2),
    'silver': (VERSIONS + 'generation-ii/silver/transparent/', GEN2),
    'crystal': (VERSIONS + 'generation-ii/crystal/transparent/', GEN2),
}
# Adventure version -> portrait set.
VERSION_SETS = {'red': 'red-blue', 'blue': 'red-blue', 'yellow': 'yellow',
                'gold': 'gold', 'silver': 'silver', 'crystal': 'crystal'}
log = logging.getLogger(__name__)


def download(client, url, limit):
    data = bytearray()
    with client.stream('GET', url) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError('The sprite source returned an oversized file')
    return bytes(data)


def validate_png(data):
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError('The sprite source returned an oversized file')
    with Image.open(io.BytesIO(data)) as image:
        if image.format != 'PNG' or not all(1 <= side <= 256 for side in image.size):
            raise ValueError('The sprite source returned an invalid image')
        if getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Animated images are not supported in this pack')
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()


def _valid(path):
    try:
        validate_png(path.read_bytes())
    except Exception:
        return False
    return True


class PortraitPacks:
    def __init__(self, registry, cancelled, *, images=None, folder=FOLDER,
                 pack='portrait-packs', setting='community_portraits', sets=None, legacy=None):
        """`sets` maps set names to (folder, images). Without it the pack is one set kept
        at the pack root, which is also how a single-set install from an older release is
        laid out. `legacy` names the set such an install holds."""
        self.registry = registry
        self.cancelled = cancelled
        if sets is None:
            sets = {'': (folder, images if images is not None else GEN1)}
            legacy = ''
        self.sets = sets
        self.legacy = legacy
        self.setting = setting
        self.directory = registry.root / 'assets' / pack / REVISION
        self.staging = self.directory.parent / ('.install-' + REVISION)
        self.lock = threading.RLock()
        self.busy = False
        self.completed = 0
        self.error = None

    @classmethod
    def portraits(cls, registry, cancelled):
        return cls(registry, cancelled, sets=PORTRAIT_SETS, legacy='red-blue')

    # Layout ---------------------------------------------------------------------------------

    def _manifest(self):
        try:
            return json.loads((self.directory / 'manifest.json').read_bytes())
        except (OSError, ValueError):
            return None

    def _present(self):
        """{set name: folder holding it} for the sets the installed pack contains."""
        manifest = self._manifest()
        if not isinstance(manifest, dict):
            return {}
        if 'sets' not in manifest:  # a single-set install from before per-game sets
            return {self.legacy: self.directory} if self.legacy in self.sets else {}
        return {name: self.directory / name for name in manifest['sets'] if name in self.sets}

    def _total(self):
        return sum(len(images) for _, images in self.sets.values())

    def installed(self):
        return set(self._present()) == set(self.sets)

    def status(self):
        with self.lock:
            present = self._present()
            installed = set(present) == set(self.sets)
            active = bool(present) and self.registry.setting(self.setting, False) is True
            folders = {folder for folder, _ in self.sets.values()}
            source = (SOURCE + next(iter(folders)).rstrip('/') if len(folders) == 1
                      else SOURCE + posixpath.commonpath(sorted(folders)))
            return {'active': 'community' if active else 'default', 'installed': installed,
                    'sets': {name: name in present for name in self.sets},
                    'busy': self.busy, 'completed': self.completed, 'total': self._total(),
                    'error': self.error, 'revision': REVISION, 'source': source,
                    'license': 'https://github.com/PokeAPI/sprites/blob/' + REVISION + '/LICENCE.txt'}

    # Switching ------------------------------------------------------------------------------

    def begin(self):
        with self.lock:
            if self.busy:
                raise ValueError('The community sprite pack is already downloading')
            self.error = None
            if self.installed():
                self.registry.set_setting(self.setting, True)
                return False
            self.busy = True
            self.completed = 0
            return True

    def restore(self):
        with self.lock:
            if self.busy:
                raise ValueError('Wait for the sprite download to finish before switching')
            self.registry.set_setting(self.setting, False)
            self.error = None

    def path(self, key, *, version=None, preview=False):
        """The installed image for `key`, from the set matching the adventure `version`.

        Without a version the pack's first set answers (the only set for item artwork,
        Red/Blue for portraits). A version the pack has no set for gets nothing."""
        if version is None:
            name = next(iter(self.sets))
        else:
            name = VERSION_SETS.get(version, version)
        if name not in self.sets or key not in self.sets[name][1]:
            return None
        if not preview and self.registry.setting(self.setting, False) is not True:
            return None
        folder = self._present().get(name)
        if folder is None:
            return None
        path = folder / f'{key}.png'
        return path if path.is_file() else None

    # Download -------------------------------------------------------------------------------

    def _seed(self):
        """Carry images from an existing install into staging so they are not fetched again."""
        for name, folder in self._present().items():
            target = self.staging / name
            target.mkdir(parents=True, exist_ok=True)
            for key in self.sets[name][1]:
                source, destination = folder / f'{key}.png', target / f'{key}.png'
                if source.is_file() and not destination.exists():
                    shutil.copyfile(source, destination)

    def install(self):
        try:
            self.directory.parent.mkdir(parents=True, exist_ok=True)
            self.staging.mkdir(exist_ok=True)
            self._seed()
            budget = {'bytes': 0}
            jobs = []
            for name, (folder, images) in self.sets.items():
                target = self.staging / name
                target.mkdir(parents=True, exist_ok=True)
                groups = {}
                for key, filename in images.items():
                    if (target / f'{key}.png').is_file() and _valid(target / f'{key}.png'):
                        with self.lock:
                            self.completed += 1
                    else:
                        groups.setdefault(filename, []).append(key)
                jobs.extend((target, folder, filename, keys) for filename, keys in groups.items())
            with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
                if not (self.staging / 'LICENCE.txt').is_file():
                    notice = download(client, RAW + '/LICENCE.txt', 64 * 1024)
                    CheckpointStore.atomic_write(self.staging / 'LICENCE.txt', notice)

                def fetch(target, folder, filename, keys):
                    if self.cancelled.is_set():
                        raise ValueError('Sprite download was interrupted')
                    data = download(client, RAW + folder + filename, MAX_IMAGE_BYTES)
                    validate_png(data)
                    with self.lock:
                        budget['bytes'] += len(data)
                        if budget['bytes'] > MAX_PACK_BYTES:
                            raise ValueError('The sprite source returned more data than expected')
                    for key in keys:
                        CheckpointStore.atomic_write(target / f'{key}.png', data)
                    return len(keys)

                with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                    futures = [pool.submit(fetch, *job) for job in jobs]
                    try:
                        for future in as_completed(futures):
                            completed = future.result()
                            with self.lock:
                                self.completed += completed
                    except Exception:
                        for future in futures:
                            future.cancel()
                        raise
            if self.cancelled.is_set():
                raise ValueError('Sprite download was interrupted')
            self._activate()
        except Exception:
            log.exception('Community sprite installation failed')
            with self.lock:
                self.error = ('Could not install the sprite pack. Your current artwork is unchanged. '
                              'Check the connection and retry. Finished images are kept.')
        finally:
            with self.lock:
                self.busy = False

    def _activate(self):
        root = self.sets.keys() == {''}
        CheckpointStore.atomic_write(self.staging / 'manifest.json', json.dumps({
            'revision': REVISION, 'source': SOURCE, 'count': self._total(),
            **({} if root else {'sets': list(self.sets)})}).encode())
        with self.lock:
            retired = None
            if self.directory.exists():
                retired = self.directory.parent / ('.install-retired-' + REVISION)
                if retired.exists():
                    shutil.rmtree(retired)
                self.directory.rename(retired)
            self.staging.rename(self.directory)
            self.registry.set_setting(self.setting, True)
        if retired is not None:
            shutil.rmtree(retired, ignore_errors=True)
