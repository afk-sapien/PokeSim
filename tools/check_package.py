"""Verify runtime resources and exclude private artifacts from built packages."""
from pathlib import Path
import tarfile
import zipfile

required = {
    'pokesim/web/static/index.html',
    'pokesim/web/static/app.js',
    'pokesim/web/static/style.css',
    'pokesim/healthcheck.py',
    'pokesim/prepare_data.py',
    'pokesim/data_tools/strategy.py',
}
artifacts = list(Path('dist').glob('*.whl')) + list(Path('dist').glob('*.tar.gz'))
if not artifacts:
    raise SystemExit('Build packages first with uv build')
for artifact in artifacts:
    if artifact.suffix == '.whl':
        with zipfile.ZipFile(artifact) as archive:
            names = set(archive.namelist())
    else:
        with tarfile.open(artifact) as archive:
            names = {name.partition('/')[2] for name in archive.getnames()}
        assert {'uv.lock', 'THIRD_PARTY_NOTICES.md'} <= names
    missing = required - names
    assert not missing, f'{artifact}: missing runtime files {missing}'
    for name in names:
        path = Path(name)
        assert path.suffix not in {'.gb', '.gbc', '.sav', '.state', '.sqlite'}, name
        assert path.name != '.env', name
        assert not name.startswith(('pokesim/data/', 'pokesim/web/static/sprites/')), name
    print(f'{artifact.name}: runtime resources verified')
