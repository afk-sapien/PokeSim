"""Prepare local game data from a verified reference archive or pinned Git checkout."""
import argparse
import hashlib
import json
import subprocess
import threading
from pathlib import Path

from . import __version__
from . import game_data
from .data_tools import collection, strategy, tables
from .store import Store


def prepare(source, destination, variant='red'):
    source = source.resolve()
    def git(*args):
        return subprocess.check_output(['git', '-c', f'safe.directory={source}', '-C', str(source), *args], text=True).strip()
    revision = git('rev-parse', 'HEAD')
    expected = game_data.VARIANTS[variant][1]
    if revision != expected:
        raise ValueError(f'Use source revision {expected}, found {revision}')
    if git('status', '--porcelain', '--untracked-files=no'):
        raise ValueError('The source checkout has modified tracked files. Use a clean checkout.')
    return generate_bundle(source, destination, revision, variant)


def generate_bundle(source, destination, revision, variant='red'):
    """Generate from a source tree already verified by the calling installer.

    ``destination`` is the shared Gen I data folder. Yellow data goes in its subfolder.
    """
    url, expected = game_data.VARIANTS[variant]
    if revision != expected:
        raise ValueError('Unsupported reference revision')
    generated_strategy = strategy.generate(source, revision)
    values = {'strategy.json': generated_strategy, 'tables.json': tables.generate(source),
              'collection.json': collection.generate(source, json.loads(json.dumps(generated_strategy)), variant)}
    encoded = {name: (json.dumps(value, separators=(',', ':'), ensure_ascii=False) + '\n').encode()
               for name, value in values.items()}
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in encoded.items()}
    manifest = {'schema': game_data.SCHEMA, 'source': url, 'source_revision': revision,
                'generator_version': __version__, 'files': hashes}
    if variant != 'red':
        manifest['variant'] = variant
    identity = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    destination = game_data.variant_root(destination, variant)
    bundle = destination / 'bundles' / identity
    bundle.mkdir(parents=True, exist_ok=True)
    for name, raw in encoded.items():
        Store.atomic_write(bundle / name, raw)
    Store.atomic_write(bundle / 'manifest.json', json.dumps(manifest, indent=2).encode())
    Store.atomic_write(destination / 'current.json', json.dumps({'bundle': identity}).encode())
    return bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, nargs='?', help='Existing pinned reference Git checkout')
    archive = parser.add_mutually_exclusive_group()
    archive.add_argument('--download', action='store_true', help='Download and verify the pinned reference archive')
    archive.add_argument('--reference-archive', type=Path, help='Use a verified reference ZIP for offline setup')
    parser.add_argument('--output', type=Path, default=game_data.directory())
    parser.add_argument('--yellow', action='store_true',
                        help='Prepare Pokémon Yellow data from pret/pokeyellow as well as, or with a source checkout instead of, Red and Blue data')
    args = parser.parse_args(argv)
    if bool(args.source) == bool(args.download or args.reference_archive):
        parser.error('Choose a source checkout, --download, or --reference-archive')
    try:
        if args.source:
            print(prepare(args.source, args.output, 'yellow' if args.yellow else 'red'))
        else:
            from .desktop_setup import ensure_game_data
            ensure_game_data(args.output, lambda message: print(message, flush=True),
                             threading.Event(), args.reference_archive)
            print(f'Game data ready: {game_data.bundle_path(args.output, "red")}')
            if args.yellow:
                ensure_game_data(args.output, lambda message: print(message, flush=True),
                                 threading.Event(), variant='yellow')
                print(f'Yellow game data ready: {game_data.bundle_path(args.output, "yellow")}')
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Cannot prepare game data: {error}') from error


if __name__ == '__main__':
    main()
