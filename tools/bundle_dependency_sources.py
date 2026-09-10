"""Preserve dependency notices and the pinned PyBoy source with the image."""
import hashlib
import json
import shutil
import sys
import tomllib
from importlib.metadata import distributions
from pathlib import Path
from urllib.request import urlopen

output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
lock = tomllib.loads(Path('uv.lock').read_text())
package = next(package for package in lock['package'] if package['name'] == 'pyboy')
source = package['sdist']
with urlopen(source['url'], timeout=60) as response:
    raw = response.read()
assert 'sha256:' + hashlib.sha256(raw).hexdigest() == source['hash']
sources = output / 'sources'
sources.mkdir(exist_ok=True)
(sources / f"pyboy-{package['version']}.tar.gz").write_bytes(raw)
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
(output / 'source-manifest.json').write_text(json.dumps({'pyboy': source}, indent=2))
