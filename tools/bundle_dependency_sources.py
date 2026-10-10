"""Preserve installed dependency notices and the matching Rust emulator source."""
import argparse
import email
import hashlib
import io
import json
import shutil
import tarfile
import tomllib
from importlib.metadata import distributions
from pathlib import Path
from urllib.request import urlopen

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', type=Path)
parser.add_argument('--emulator-source', type=Path, help='Corresponding PyBoy RS source archive')
args = parser.parse_args()
output = args.output
output.mkdir(parents=True, exist_ok=True)
root = Path(__file__).resolve().parents[1]
lock = tomllib.loads((root / 'uv.lock').read_text())
packages = [package for package in lock['package'] if package['name'] == 'pyboy-rs']
versions = {package['version'] for package in packages}
if len(versions) != 1:
    raise ValueError(f'uv.lock must pin exactly one pyboy-rs version, found {sorted(versions)}')
package = packages[0]
source = package.get('sdist')


def check_archive_matches_lock(raw):
    """The archive's own PKG-INFO must name the locked pyboy-rs version, whatever the file is called."""
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        member = next((item for item in archive.getmembers() if item.name.count('/') == 1 and item.name.endswith('/PKG-INFO')), None)
        if member is None:
            raise ValueError('Emulator source archive has no PKG-INFO')
        info = email.message_from_bytes(archive.extractfile(member).read())
    name, version = info['Name'].lower().replace('_', '-'), info['Version']
    if name != 'pyboy-rs' or version != package['version']:
        raise ValueError(f'Emulator source archive is {name} {version} but uv.lock pins pyboy-rs {package["version"]}')


archive = args.emulator_source
if archive is None and 'directory' in package['source']:
    directory = root / package['source']['directory']
    archive = directory / 'dist' / f"pyboy_rs-{package['version']}.tar.gz"
if archive is not None:
    raw = archive.read_bytes()
    source = {'filename': archive.name, 'hash': 'sha256:' + hashlib.sha256(raw).hexdigest()}
elif source is not None:
    with urlopen(source['url'], timeout=60) as response:
        raw = response.read()
    if 'sha256:' + hashlib.sha256(raw).hexdigest() != source['hash']:
        raise ValueError('Emulator source archive checksum mismatch')
else:
    raise ValueError('Supply the corresponding source archive with --emulator-source')
sources = output / 'sources'
sources.mkdir(exist_ok=True)
check_archive_matches_lock(raw)
(sources / f"pyboy-rs-{package['version']}.tar.gz").write_bytes(raw)
report = []
for dist in sorted(distributions(), key=lambda d: d.metadata['Name'].lower()):
    name = dist.metadata['Name']
    notices = []
    for file in dist.files or []:
        if '.dist-info/' in str(file) and any(term in str(file).lower() for term in ('license', 'copying', 'notice')):
            path = Path(dist.locate_file(file))
            if path.is_file():
                target = output / 'licenses' / name / Path(file)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                notices.append(str(target.relative_to(output)))
    report.append({'name': name, 'version': dist.version,
                   'license': dist.metadata.get('License-Expression') or dist.metadata.get('License'),
                   'project_urls': dist.metadata.get_all('Project-URL') or [], 'notices': notices})
(output / 'python-dependencies.json').write_text(json.dumps(report, indent=2))
(output / 'source-manifest.json').write_text(json.dumps({'pyboy-rs': source}, indent=2))
