import hashlib
import json
from pathlib import Path

import pytest

from pokesim import game_data
from pokesim.store import Store
from pokesim.web.app import create_app
from fastapi.testclient import TestClient
from unittest.mock import Mock


def synthetic_bundle(tmp_path, monkeypatch):
    root = tmp_path / 'game-data'
    identity = 'a' * 64
    bundle = root / 'bundles' / identity
    bundle.mkdir(parents=True)
    raw = b'{"example":true}'
    (bundle / 'tables.json').write_bytes(raw)
    (bundle / 'manifest.json').write_text(json.dumps({
        'schema': game_data.SCHEMA, 'source_revision': game_data.SOURCE_REVISION,
        'files': {'tables.json': hashlib.sha256(raw).hexdigest()}}))
    (root / 'current.json').write_text(json.dumps({'bundle': identity}))
    monkeypatch.setenv('GAME_DATA_DIR', str(root))
    return root, bundle


def test_local_bundle_is_verified_before_use(tmp_path, monkeypatch):
    _, bundle = synthetic_bundle(tmp_path, monkeypatch)
    assert game_data.load('tables.json') == {'example': True}
    (bundle / 'tables.json').write_text('{"example":false}')
    with pytest.raises(RuntimeError, match='verified'):
        game_data.load('tables.json')


def test_missing_bundle_provides_setup_instructions(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_DATA_DIR', str(tmp_path))
    with pytest.raises(RuntimeError, match='prepare-data'):
        game_data.load('strategy.json')


def test_bundle_pointer_cannot_escape_data_directory(tmp_path, monkeypatch):
    root, _ = synthetic_bundle(tmp_path, monkeypatch)
    (root / 'current.json').write_text(json.dumps({'bundle': '../../outside'}))
    with pytest.raises(RuntimeError):
        game_data.load('tables.json')


def test_portraits_work_without_bundled_game_images(tmp_path):
    store = Store(tmp_path)
    try:
        with TestClient(create_app(Mock(), store)) as client:
            response = client.get('/sprites/25.png')
            assert response.status_code == 200
            assert response.headers['content-type'].startswith('image/svg+xml')
            assert '025' in response.text
            assert client.get('/sprites/0.png').status_code == 404
            assert client.get('/static/sprites/25.png').status_code == 404
            portraits = tmp_path / 'sprites'
            portraits.mkdir()
            (portraits / '25.png').write_bytes(b'user supplied image')
            response = client.get('/sprites/25.png')
            assert response.content == b'user supplied image'
            assert response.headers['content-type'] == 'image/png'
    finally:
        store.close()
