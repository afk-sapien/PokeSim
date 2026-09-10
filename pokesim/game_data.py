"""Read locally generated content without bundling game data in the package."""
import hashlib
import json
import os
from pathlib import Path

SCHEMA = 1
SOURCE_URL = 'https://github.com/pret/pokered'
SOURCE_REVISION = 'a1a22aaf84d1675bcdbaeb194592379d586d838e'
FILES = ('tables.json', 'strategy.json', 'collection.json')


def directory():
    return Path(os.environ.get('GAME_DATA_DIR', str(Path(os.environ.get('DATA_DIR', 'data')) / 'game-data')))


def bundle_path():
    root = directory()
    try:
        pointer = json.loads((root / 'current.json').read_text())
        bundle_id = pointer['bundle']
        if len(bundle_id) != 64 or any(c not in '0123456789abcdef' for c in bundle_id):
            raise ValueError('Invalid bundle identifier')
        return root / 'bundles' / bundle_id
    except (OSError, ValueError, KeyError) as error:
        raise RuntimeError('Game data is missing or invalid. Run the documented prepare-data command before starting pokesim.') from error


def load(name):
    if name not in FILES:
        raise ValueError('Unknown game data file')
    root = bundle_path()
    try:
        manifest = json.loads((root / 'manifest.json').read_text())
        raw = (root / name).read_bytes()
        if manifest['schema'] != SCHEMA or manifest['source_revision'] != SOURCE_REVISION:
            raise ValueError('Incompatible game data bundle')
        if hashlib.sha256(raw).hexdigest() != manifest['files'][name]:
            raise ValueError('Game data checksum mismatch')
        return json.loads(raw)
    except (OSError, ValueError, KeyError) as error:
        raise RuntimeError('Game data could not be verified. Regenerate it using the documented prepare-data command.') from error
