"""Read locally generated content without bundling game data in the package."""
import hashlib
import json
import os
from pathlib import Path

SCHEMA = 1
SOURCE_URL = 'https://github.com/pret/pokered'
SOURCE_REVISION = 'a1a22aaf84d1675bcdbaeb194592379d586d838e'
FILES = ('tables.json', 'strategy.json', 'collection.json')
# Yellow keeps its own maps, events, trainers and Pokédex data in a subfolder of the
# shared Gen I data folder. A Yellow adventure's process selects it through VARIANT_ENV.
YELLOW_SOURCE_URL = 'https://github.com/pret/pokeyellow'
YELLOW_REVISION = 'e89ead154b9968aa50eed9328ff2b38b6c194382'
VARIANTS = {'red': (SOURCE_URL, SOURCE_REVISION), 'yellow': (YELLOW_SOURCE_URL, YELLOW_REVISION)}
VARIANT_ENV = 'POKESIM_GEN1_VARIANT'


def directory():
    return Path(os.environ.get('GAME_DATA_DIR', str(Path(os.environ.get('DATA_DIR', 'data')) / 'game-data')))


def current_variant():
    variant = os.environ.get(VARIANT_ENV) or 'red'
    if variant not in VARIANTS:
        raise RuntimeError('Unknown Gen I game data variant')
    return variant


def variant_root(root, variant):
    """The folder holding ``variant`` data inside a shared Gen I data folder."""
    return Path(root) if variant == 'red' else Path(root) / variant


def bundle_path(root=None, variant=None):
    variant = current_variant() if variant is None else variant
    root = variant_root(directory() if root is None else root, variant)
    try:
        pointer = json.loads((root / 'current.json').read_text())
        bundle_id = pointer['bundle']
        if len(bundle_id) != 64 or any(c not in '0123456789abcdef' for c in bundle_id):
            raise ValueError('Invalid bundle identifier')
        return root / 'bundles' / bundle_id
    except (OSError, ValueError, KeyError) as error:
        raise RuntimeError('Game data is missing or invalid. Run the documented prepare-data command before starting pokesim.') from error


def load(name, *, directory=None, variant=None):
    if name not in FILES:
        raise ValueError('Unknown game data file')
    variant = current_variant() if variant is None else variant
    root = bundle_path(directory, variant)
    try:
        manifest = json.loads((root / 'manifest.json').read_text())
        raw = (root / name).read_bytes()
        if manifest['schema'] != SCHEMA or manifest['source_revision'] != VARIANTS[variant][1]:
            raise ValueError('Incompatible game data bundle')
        if hashlib.sha256(raw).hexdigest() != manifest['files'][name]:
            raise ValueError('Game data checksum mismatch')
        return json.loads(raw)
    except (OSError, ValueError, KeyError) as error:
        raise RuntimeError('Game data could not be verified. Regenerate it using the documented prepare-data command.') from error
