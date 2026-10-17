import os

from pokesim.app.manager import read_preview


def test_preview_read_matches_the_file_that_replaced_it(tmp_path):
    preview = tmp_path / 'left.jpg'
    preview.write_bytes(b'x' * 4000)
    size = preview.stat().st_size
    pending = tmp_path / 'left.pending'
    pending.write_bytes(b'y' * 1200)
    os.replace(pending, preview)
    body = read_preview(preview)
    assert body == b'y' * 1200
    assert len(body) != size


def test_preview_removed_with_its_trade_reads_as_missing(tmp_path):
    assert read_preview(tmp_path / 'gone' / 'left.jpg') is None
