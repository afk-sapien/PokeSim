import gzip
import hashlib
from pathlib import Path

import pytest

from tools.compress_release_backups import candidates, compress


def test_compression_preserves_backup_bytes_and_permissions(tmp_path):
    source = tmp_path / 'before.tar'
    data = b'unchanged saved adventure\0' * 1000
    source.write_bytes(data)
    source.chmod(0o640)
    result = compress(source)
    target = Path(result['compressed'])
    assert gzip.decompress(target.read_bytes()) == data
    assert result['decompressed_sha256'] == hashlib.sha256(data).hexdigest()
    assert target.stat().st_mode & 0o777 == 0o640
    assert not source.exists()


def test_existing_archive_is_never_overwritten(tmp_path):
    source = tmp_path / 'before.tar'
    source.write_bytes(b'original')
    target = tmp_path / 'before.tar.gz'
    target.write_bytes(b'existing')
    with pytest.raises(FileExistsError):
        compress(source)
    assert source.read_bytes() == b'original'
    assert target.read_bytes() == b'existing'


def test_failed_verification_preserves_original(tmp_path, monkeypatch):
    source = tmp_path / 'before.tar'
    source.write_bytes(b'original')
    monkeypatch.setattr(gzip, 'open', lambda *a, **k: (_ for _ in ()).throw(ValueError('bad gzip')))
    with pytest.raises(ValueError):
        compress(source)
    assert source.read_bytes() == b'original'
    assert not list(tmp_path.glob('*.gz*'))


def test_scan_excludes_live_data_and_symlinks(tmp_path):
    valid = tmp_path / '20260915T110422Z-rc22'
    valid.mkdir()
    (valid / 'before.tar').write_bytes(b'backup')
    live = tmp_path / 'data'
    live.mkdir()
    (live / 'before.tar').write_bytes(b'live')
    (tmp_path / '20260915T110423Z-rc23').symlink_to(live, target_is_directory=True)
    assert list(candidates(tmp_path)) == [valid / 'before.tar']


def test_source_change_preserves_original(tmp_path, monkeypatch):
    from tools import compress_release_backups as module
    source = tmp_path / 'before.tar'
    source.write_bytes(b'original')
    original_digest = module.digest
    calls = 0
    def changing_digest(stream):
        nonlocal calls
        result = original_digest(stream)
        calls += 1
        if calls == 2:
            source.write_bytes(b'new save contents')
        return result
    monkeypatch.setattr(module, 'digest', changing_digest)
    with pytest.raises(ValueError, match='Source changed'):
        compress(source)
    assert source.read_bytes() == b'new save contents'
    assert not list(tmp_path.glob('*.gz*'))
