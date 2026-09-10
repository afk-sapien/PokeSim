"""Generate local game data from a pinned, user-supplied disassembly checkout."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from . import __version__
from . import game_data
from .data_tools import collection, strategy, tables
from .store import Store


def prepare(source, destination):
    source = source.resolve()
    def git(*args):
        return subprocess.check_output(['git', '-c', f'safe.directory={source}', '-C', str(source), *args], text=True).strip()
    revision = git('rev-parse', 'HEAD')
    if revision != game_data.SOURCE_REVISION:
        raise ValueError(f'Use source revision {game_data.SOURCE_REVISION}, found {revision}')
    if git('status', '--porcelain', '--untracked-files=no'):
        raise ValueError('The source checkout has modified tracked files. Use a clean checkout.')
    generated_strategy = strategy.generate(source, revision)
    values = {'strategy.json': generated_strategy, 'tables.json': tables.generate(source),
              'collection.json': collection.generate(source, json.loads(json.dumps(generated_strategy)))}
    encoded = {name: (json.dumps(value, separators=(',', ':'), ensure_ascii=False) + '\n').encode()
               for name, value in values.items()}
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in encoded.items()}
    manifest = {'schema': game_data.SCHEMA, 'source': game_data.SOURCE_URL, 'source_revision': revision,
                'generator_version': __version__, 'files': hashes}
    identity = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    destination = Path(destination)
    bundle = destination / 'bundles' / identity
    bundle.mkdir(parents=True, exist_ok=True)
    for name, raw in encoded.items():
        Store.atomic_write(bundle / name, raw)
    Store.atomic_write(bundle / 'manifest.json', json.dumps(manifest, indent=2).encode())
    Store.atomic_write(destination / 'current.json', json.dumps({'bundle': identity}).encode())
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=game_data.directory())
    args = parser.parse_args()
    try:
        print(prepare(args.source, args.output))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Cannot prepare game data: {error}') from error


if __name__ == '__main__':
    main()
