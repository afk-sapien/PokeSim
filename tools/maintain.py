"""Offline maintenance for stopped, backed-up PokeSim data.

  compress-backups  losslessly compress legacy cold backups after byte-for-byte verification

The duplicate helpers plan_removals and compact_boxes trim a backed-up, stopped adventure
checkpoint. They have no command line and do not alter the running game's capture or release
policy. The caller must retain the source checkpoint and verify the output before adoption.
"""
import argparse
from collections import defaultdict
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokesim.platform_io import sync_directory


# compress-backups: losslessly compress legacy PokeSim cold backups after byte-for-byte verification.

RELEASE_DIRECTORY = re.compile(r'^\d{8}T\d{6}Z-rc\d+(?:-final)?$')


def fingerprint(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def digest(stream):
    result = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        result.update(block)
    return result.hexdigest()


def compress(path):
    """Replace one closed tar only after its compressed copy verifies and reaches disk."""
    path = Path(path)
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('The source must be a regular file')
    target = path.with_suffix('.tar.gz')
    temporary = target.with_suffix('.gz.partial')
    if target.exists() or temporary.exists() or target.is_symlink() or temporary.is_symlink():
        raise FileExistsError('A compressed destination already exists')
    original = fingerprint(path)
    metadata = path.stat()
    created = False
    try:
        with path.open('rb') as source, temporary.open('xb') as output:
            created = True
            with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0, compresslevel=6) as encoded:
                shutil.copyfileobj(source, encoded, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        with path.open('rb') as source, gzip.open(temporary, 'rb') as decoded:
            source_hash = digest(source)
            if digest(decoded) != source_hash:
                raise ValueError('Compressed backup differs from the source')
        if fingerprint(path) != original:
            raise ValueError('Source changed during compression')
        os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
        os.utime(temporary, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        # Hard linking refuses to replace a destination created by another process.
        os.link(temporary, target)
        temporary.unlink()
        sync_directory(path.parent)
        if fingerprint(path) != original:
            raise ValueError('Source changed before replacement')
        path.unlink()
        sync_directory(path.parent)
        return {'original': str(path), 'compressed': str(target), 'original_bytes': original[2],
                'compressed_bytes': target.stat().st_size, 'decompressed_sha256': source_hash}
    finally:
        if created and temporary.exists():
            temporary.unlink()


def candidates(root):
    root = Path(root)
    for directory in sorted(root.iterdir()):
        path = directory / 'before.tar'
        if (not directory.is_symlink() and directory.is_dir()
                and RELEASE_DIRECTORY.fullmatch(directory.name)
                and path.is_file() and not path.is_symlink()):
            yield path


def compress_backups(args):
    for root in args.roots:
        for path in candidates(root):
            row = compress(path) if args.apply else {'path': str(path), 'bytes': path.stat().st_size}
            print(json.dumps(row), flush=True)


# Duplicate trimming for a backed-up, stopped adventure checkpoint. No command line.

def plan_removals(snapshot, preferences, protected=(), keep=3, threshold=5):
    """Trim large groups, retaining top quality, best DVs, and protected copies.

    Box coordinates match Snapshot and are zero based. Party members never leave.
    Groups of five or fewer remain untouched, even when keep is three.
    """
    from pokesim.duplicates import quality
    from pokesim.trade.preferences import identity
    if keep < 1 or threshold < keep:
        raise ValueError('Invalid retention limits')
    groups = defaultdict(list)
    for mon in [*(asdict(mon) for mon in snapshot.party), *snapshot.storage_entries()]:
        groups[mon['species']].append(mon)
    removed = []
    for species, copies in groups.items():
        if len(copies) <= threshold or species in protected:
            continue
        ranked = sorted(copies, key=quality, reverse=True)
        retained = {id(mon) for mon in ranked[:keep]}
        retained.add(id(max(copies, key=lambda mon: (sum(mon['dvs']), quality(mon)))))
        for mon in copies:
            if 'box' not in mon or id(mon) in retained:
                continue
            if preferences.get(identity(mon), {}).get('state') in ('locked', 'offered'):
                continue
            removed.append(mon)
    return removed


def compact_boxes(memory, removals):
    """Remove planned slots and preserve every retained record byte for byte.

    Validate the entire selection before writing. Only compact within each box.
    """
    from pokesim.trade.boxes import BoxView, LIST_TERMINATOR, OFF_COUNT, OFF_SPECIES_LIST, read_slot, write_slot
    selected = {(mon['box'] + 1, mon['position'] + 1) for mon in removals}
    if len(selected) != len(removals):
        raise ValueError('Duplicate removal coordinates')
    groups = defaultdict(set)
    for mon in removals:
        box, position = mon['box'] + 1, mon['position'] + 1
        slot = read_slot(memory, box, position)
        if slot.species != mon['species'] or slot.level != mon['level']:
            raise ValueError('Removal plan does not match checkpoint')
        groups[box].add(position)
    for box, positions in groups.items():
        view = BoxView(memory, box)
        survivors = [read_slot(memory, box, position)
                     for position in range(1, view.count + 1) if position not in positions]
        for position, slot in enumerate(survivors, 1):
            write_slot(memory, box, position, slot)
        view.write(OFF_COUNT, bytes([len(survivors)]))
        view.write(OFF_SPECIES_LIST + len(survivors), bytes([LIST_TERMINATOR]))
        view.flush()
        actual = [read_slot(memory, box, position)
                  for position in range(1, view.count + 1)]
        assert [(s.struct, s.nickname, s.ot_name) for s in actual] == [
            (s.struct, s.nickname, s.ot_name) for s in survivors]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True, metavar='SUBCOMMAND')
    description = 'Losslessly compress legacy PokeSim cold backups after byte-for-byte verification.'
    sub = commands.add_parser('compress-backups', help=description, description=description)
    sub.add_argument('roots', type=Path, nargs='+')
    sub.add_argument('--apply', action='store_true', help='Compress and verify before replacing tar files')
    sub.set_defaults(run=compress_backups)
    args = parser.parse_args(argv)
    args.run(args)


if __name__ == '__main__':
    main()
