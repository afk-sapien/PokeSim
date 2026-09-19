import hashlib
import io
import json
import tarfile
import zipfile

import pytest

from tools.assemble_release import DESKTOP_ARCHIVES, assemble, digest


VERSION = '0.2.0rc99'
REVISION = 'a' * 40


@pytest.fixture
def assets(tmp_path):
    identity = {'version': VERSION, 'revision': REVISION, 'dirty': False}
    raw = json.dumps(identity).encode()
    with zipfile.ZipFile(tmp_path / f'pokesim-{VERSION}-py3-none-any.whl', 'w') as archive:
        archive.writestr('pokesim/_build.json', raw)
    with tarfile.open(tmp_path / f'pokesim-{VERSION}.tar.gz', 'w:gz') as archive:
        entry = tarfile.TarInfo(f'pokesim-{VERSION}/pokesim/_build.json')
        entry.size = len(raw)
        archive.addfile(entry, io.BytesIO(raw))
    for name in DESKTOP_ARCHIVES:
        (tmp_path / name).write_bytes(b'archive contents')
        checksum = hashlib.sha256(b'archive contents').hexdigest()
        (tmp_path / (name + '.sha256')).write_text(f'{checksum}  {name}\n')
        (tmp_path / (name + '.json')).write_text(json.dumps({
            **identity, 'archive': name, 'sha256': checksum,
        }))
    (tmp_path / 'image-linux-amd64.tar.gz').write_bytes(b'image contents')
    (tmp_path / 'image-metadata.json').write_text(json.dumps({
        'Id': 'sha256:example', 'Os': 'linux', 'Architecture': 'amd64',
        'Config': {'Labels': {'org.opencontainers.image.version': VERSION,
                              'org.opencontainers.image.revision': REVISION}},
    }))
    (tmp_path / 'python-dependencies.json').write_text('[]')
    (tmp_path / 'compose.yaml').write_text('services:\n'
                                         '  pokesim:\n'
                                         '    image: ${POKESIM_IMAGE:-pokesim:local}\n'
                                         '  prepare-data:\n'
                                         '    image: ${POKESIM_IMAGE:-pokesim:local}\n')
    (tmp_path / 'env.example').write_text('POKESIM_IMAGE=pokesim:local\n')
    return tmp_path


def test_complete_release_checksums_cover_every_download_and_manifest(assets):
    assemble(assets, VERSION, REVISION)
    assert (assets / 'env.example').read_text() == f'POKESIM_IMAGE=pokesim:{VERSION}\n'
    assert (assets / 'compose.yaml').read_text().count(f'POKESIM_IMAGE:-pokesim:{VERSION}') == 2
    sums = dict(line.split('  ', 1)[::-1] for line in (assets / 'SHA256SUMS').read_text().splitlines())
    assert set(sums) == {path.name for path in assets.iterdir()} - {'SHA256SUMS'}
    for name, checksum in sums.items():
        assert digest(assets / name) == checksum
    # Local assembly can be repeated before a draft is uploaded.
    before = (assets / 'SHA256SUMS').read_bytes()
    assemble(assets, VERSION, REVISION)
    assert (assets / 'SHA256SUMS').read_bytes() == before


def test_missing_native_target_blocks_release(assets):
    (assets / DESKTOP_ARCHIVES[0]).unlink()
    with pytest.raises(ValueError, match='Missing release assets'):
        assemble(assets, VERSION, REVISION)
    assert not (assets / 'manifest.json').exists()


@pytest.mark.parametrize('change', [{'revision': 'b' * 40}, {'dirty': True}, {'version': '0.1.0'}])
def test_mixed_or_dirty_desktop_build_blocks_release(assets, change):
    path = assets / (DESKTOP_ARCHIVES[0] + '.json')
    path.write_text(json.dumps({**json.loads(path.read_text()), **change}))
    with pytest.raises(ValueError, match='same clean tagged revision'):
        assemble(assets, VERSION, REVISION)


def test_changed_archive_blocks_release(assets):
    (assets / DESKTOP_ARCHIVES[0]).write_bytes(b'changed download')
    with pytest.raises(ValueError, match='build receipt'):
        assemble(assets, VERSION, REVISION)


def test_wrong_container_revision_blocks_release(assets):
    path = assets / 'image-metadata.json'
    metadata = json.loads(path.read_text())
    metadata['Config']['Labels']['org.opencontainers.image.revision'] = 'b' * 40
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='Container identity'):
        assemble(assets, VERSION, REVISION)


def test_wrong_wheel_revision_blocks_release(assets):
    with zipfile.ZipFile(assets / f'pokesim-{VERSION}-py3-none-any.whl', 'w') as archive:
        archive.writestr('pokesim/_build.json', json.dumps({
            'version': VERSION, 'revision': 'b' * 40, 'dirty': False,
        }))
    with pytest.raises(ValueError, match='same clean tagged revision'):
        assemble(assets, VERSION, REVISION)


def test_unexpected_private_file_blocks_release(assets):
    (assets / 'adventure.state').write_bytes(b'private state')
    with pytest.raises(ValueError, match='Unexpected release assets'):
        assemble(assets, VERSION, REVISION)
