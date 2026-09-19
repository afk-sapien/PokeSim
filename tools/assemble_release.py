"""Validate a complete release from one source revision and write its manifests."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile
import zipfile


DESKTOP_ARCHIVES = (
    'PokeSim-windows-amd64.zip',
    'PokeSim-darwin-arm64.zip',
    'PokeSim-darwin-x86_64.zip',
    'PokeSim-linux-x86_64.tar.gz',
    'PokeSim-linux-aarch64.tar.gz',
)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_identity(identity, version, revision):
    if (identity.get('version') != version or identity.get('revision') != revision
            or identity.get('dirty') is not False):
        raise ValueError('Every package must come from the same clean tagged revision')


def assemble(root, version, revision, *, include_desktop=True):
    archives = DESKTOP_ARCHIVES if include_desktop else ()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:rc\d+)?', version):
        raise ValueError('Invalid release version')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Invalid source revision')
    wheel = f'pokesim-{version}-py3-none-any.whl'
    source = f'pokesim-{version}.tar.gz'
    required = {wheel, source, 'image-linux-amd64.tar.gz', 'image-metadata.json',
                'python-dependencies.json', 'compose.yaml', 'env.example'}
    for name in archives:
        required.update({name, name + '.sha256', name + '.json'})
    missing = sorted(name for name in required if not (root / name).is_file())
    if missing:
        raise ValueError(f'Missing release assets: {missing}')
    allowed = required | {'manifest.json', 'SHA256SUMS'}
    if include_desktop:
        allowed.add('desktop-manifest.json')
    unexpected = sorted(path.name for path in root.iterdir() if path.name not in allowed or not path.is_file())
    if unexpected:
        raise ValueError(f'Unexpected release assets: {unexpected}')

    with zipfile.ZipFile(root / wheel) as archive:
        check_identity(json.loads(archive.read('pokesim/_build.json')), version, revision)
    with tarfile.open(root / source) as archive:
        check_identity(json.load(archive.extractfile(f'pokesim-{version}/pokesim/_build.json')),
                       version, revision)

    metadata = json.loads((root / 'image-metadata.json').read_text())
    labels = metadata['Config']['Labels']
    if (metadata['Os'] != 'linux' or metadata['Architecture'] != 'amd64'
            or labels['org.opencontainers.image.version'] != version
            or labels['org.opencontainers.image.revision'] != revision):
        raise ValueError('Container identity or platform does not match the release')

    desktop = {}
    for name in archives:
        identity = json.loads((root / (name + '.json')).read_text())
        check_identity(identity, version, revision)
        checksum = digest(root / name)
        if identity.get('archive') != name or identity.get('sha256') != checksum:
            raise ValueError(f'Desktop archive does not match its build receipt: {name}')
        if (root / (name + '.sha256')).read_text().strip() != f'{checksum}  {name}':
            raise ValueError(f'Desktop checksum mismatch: {name}')
        desktop[name] = identity

    image = f'pokesim:{version}'
    settings = root / 'env.example'
    contents = settings.read_text()
    if len(re.findall(r'^POKESIM_IMAGE=.*$', contents, flags=re.M)) != 1:
        raise ValueError('Release settings must select exactly one image')
    settings.write_text(re.sub(r'^POKESIM_IMAGE=.*$', f'POKESIM_IMAGE={image}',
                              contents, flags=re.M), encoding='utf-8')
    compose = root / 'compose.yaml'
    contents = compose.read_text()
    image_default = r'\$\{POKESIM_IMAGE:-pokesim:(?:local|\d+\.\d+\.\d+(?:rc\d+)?)\}'
    if len(re.findall(image_default, contents)) not in (1, 2):
        raise ValueError('Release Compose must select the versioned application image')
    compose.write_text(re.sub(image_default, '${POKESIM_IMAGE:-' + image + '}', contents),
                       encoding='utf-8')
    if include_desktop:
        (root / 'desktop-manifest.json').write_text(json.dumps({
            'version': version, 'revision': revision, 'archives': desktop,
        }, indent=2) + '\n', encoding='utf-8')
    files = {path.name: digest(path) for path in sorted(root.iterdir())
             if path.name not in {'manifest.json', 'SHA256SUMS'}}
    (root / 'manifest.json').write_text(json.dumps({
        'version': version, 'revision': revision, 'image': image,
        'image_id': metadata['Id'], 'platform': 'linux/amd64', 'files': files,
    }, indent=2) + '\n', encoding='utf-8')
    files['manifest.json'] = digest(root / 'manifest.json')
    (root / 'SHA256SUMS').write_text(''.join(f'{checksum}  {name}\n'
                                          for name, checksum in sorted(files.items())), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--without-desktop', action='store_true', help='Assemble the Python and Docker release')
    args = parser.parse_args()
    assemble(args.directory, args.version, args.revision, include_desktop=not args.without_desktop)
    print('Release assets verified and manifests written')


if __name__ == '__main__':
    main()
