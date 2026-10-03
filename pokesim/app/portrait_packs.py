"""Optional owner-requested portrait downloads, separate from cartridge artwork."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
import logging
import tempfile
import threading
from pathlib import Path

import httpx
from PIL import Image

from ..checkpoints import CheckpointStore

REVISION = 'bfb75391935310368065096fa08c51e8970bc43e'
SOURCE = 'https://github.com/PokeAPI/sprites/tree/' + REVISION
RAW = 'https://raw.githubusercontent.com/PokeAPI/sprites/' + REVISION
FOLDER = '/sprites/pokemon/versions/generation-i/red-blue/transparent/'
MAX_IMAGE_BYTES = 128 * 1024
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
    with Image.open(io.BytesIO(data)) as image:
        if image.format != 'PNG' or not all(1 <= side <= 256 for side in image.size):
            raise ValueError('The sprite source returned an invalid image')
        if getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Animated images are not supported in this pack')
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()


class PortraitPacks:
    def __init__(self, registry, cancelled):
        self.registry = registry
        self.cancelled = cancelled
        self.directory = registry.root / 'assets' / 'portrait-packs' / REVISION
        self.lock = threading.RLock()
        self.busy = False
        self.completed = 0
        self.error = None

    def installed(self):
        return (self.directory / 'manifest.json').is_file()

    def status(self):
        with self.lock:
            installed = self.installed()
            active = installed and self.registry.setting('community_portraits', False) is True
            return {'active': 'community' if active else 'default', 'installed': installed,
                    'busy': self.busy, 'completed': self.completed, 'total': 151,
                    'error': self.error, 'revision': REVISION, 'source': SOURCE + FOLDER.rstrip('/'),
                    'license': 'https://github.com/PokeAPI/sprites/blob/' + REVISION + '/LICENCE.txt'}

    def begin(self):
        with self.lock:
            if self.busy:
                raise ValueError('The community sprite pack is already downloading')
            self.error = None
            if self.installed():
                self.registry.set_setting('community_portraits', True)
                return False
            self.busy = True
            self.completed = 0
            return True

    def restore(self):
        with self.lock:
            if self.busy:
                raise ValueError('Wait for the sprite download to finish before switching')
            self.registry.set_setting('community_portraits', False)
            self.error = None

    def path(self, dex, *, preview=False):
        if not 1 <= dex <= 151 or not self.installed():
            return None
        if not preview and self.registry.setting('community_portraits', False) is not True:
            return None
        path = self.directory / f'{dex}.png'
        return path if path.is_file() else None

    def install(self):
        try:
            self.directory.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.install-', dir=self.directory.parent) as temp:
                stage = Path(temp) / 'pack'
                stage.mkdir()
                with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
                    notice = download(client, RAW + '/LICENCE.txt', 64 * 1024)
                    (stage / 'LICENCE.txt').write_bytes(notice)

                    def fetch(dex):
                        if self.cancelled.is_set():
                            raise ValueError('Sprite download was interrupted')
                        data = download(client, RAW + FOLDER + f'{dex}.png', MAX_IMAGE_BYTES)
                        validate_png(data)
                        (stage / f'{dex}.png').write_bytes(data)

                    with ThreadPoolExecutor(max_workers=4) as pool:
                        futures = [pool.submit(fetch, dex) for dex in range(1, 152)]
                        try:
                            for future in as_completed(futures):
                                future.result()
                                with self.lock:
                                    self.completed += 1
                        except Exception:
                            for future in futures:
                                future.cancel()
                            raise
                if self.cancelled.is_set():
                    raise ValueError('Sprite download was interrupted')
                CheckpointStore.atomic_write(stage / 'manifest.json', json.dumps({
                    'revision': REVISION, 'source': SOURCE, 'count': 151}).encode())
                stage.rename(self.directory)
                self.registry.set_setting('community_portraits', True)
        except Exception:
            log.exception('Community sprite installation failed')
            with self.lock:
                self.error = 'Could not install the sprite pack. Your current artwork is unchanged. Check the connection and retry.'
        finally:
            with self.lock:
                self.busy = False
