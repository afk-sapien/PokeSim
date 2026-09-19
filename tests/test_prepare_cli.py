import hashlib
import json

import pytest

from pokesim import desktop_setup, game_data, prepare_data


@pytest.mark.parametrize('arguments', [[], ['source', '--download'],
                                       ['source', '--reference-archive', 'archive.zip'],
                                       ['--download', '--reference-archive', 'archive.zip']])
def test_preparation_requires_one_input(arguments):
    with pytest.raises(SystemExit) as error:
        prepare_data.main(arguments)
    assert error.value.code == 2


def test_archive_failure_preserves_existing_adventure(tmp_path):
    save = tmp_path / 'autosave.state'
    save.write_bytes(b'keep this adventure')
    archive = tmp_path / 'reference.zip'
    archive.write_bytes(b'corrupt download')
    output = tmp_path / 'game-data'
    with pytest.raises(SystemExit, match='verification'):
        prepare_data.main(['--reference-archive', str(archive), '--output', str(output)])
    assert save.read_bytes() == b'keep this adventure'
    assert not output.exists()


def test_repeated_download_setup_uses_verified_data_offline(tmp_path, monkeypatch):
    identity = 'a' * 64
    bundle = tmp_path / 'bundles' / identity
    bundle.mkdir(parents=True)
    files = {}
    for name in game_data.FILES:
        raw = b'{}'
        (bundle / name).write_bytes(raw)
        files[name] = hashlib.sha256(raw).hexdigest()
    (bundle / 'manifest.json').write_text(json.dumps({
        'schema': game_data.SCHEMA, 'source_revision': game_data.SOURCE_REVISION,
        'files': files,
    }))
    (tmp_path / 'current.json').write_text(json.dumps({'bundle': identity}))

    def unexpected_download(*args, **kwargs):
        pytest.fail('Prepared data must not require another download')

    monkeypatch.setattr(desktop_setup, 'urlopen', unexpected_download)
    prepare_data.main(['--download', '--output', str(tmp_path)])
    assert game_data.bundle_path(tmp_path) == bundle
