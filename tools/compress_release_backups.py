"""Losslessly compress legacy PokeSim cold backups after byte-for-byte verification."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat


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
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
            if fingerprint(path) != original:
                raise ValueError('Source changed before replacement')
            path.unlink()
            os.fsync(directory)
        finally:
            os.close(directory)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('roots', type=Path, nargs='+')
    parser.add_argument('--apply', action='store_true', help='Compress and verify before replacing tar files')
    args = parser.parse_args()
    for root in args.roots:
        for path in candidates(root):
            row = compress(path) if args.apply else {'path': str(path), 'bytes': path.stat().st_size}
            print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
