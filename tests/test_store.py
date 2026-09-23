import pytest

from pokesim.events import Event
from pokesim.store import Store
from test_events import snap


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path)
    yield instance
    instance.close()


@pytest.mark.parametrize('attachment', ['shots', 'states'])
def test_failed_event_write_rolls_back_and_allows_retry(store, monkeypatch, attachment):
    from pathlib import Path

    write_bytes = Path.write_bytes
    directory = getattr(store, attachment)

    def fail_write(path, data):
        if path.parent == directory:
            path.touch()
            raise OSError('disk full')
        return write_bytes(path, data)

    event = Event('catch', 'Caught a partner')
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'write_bytes', fail_write)
        with pytest.raises(OSError, match='disk full'):
            store.add_event(event, snap(), b'image', b'state')

    store.set('unrelated', {'saved': True})
    assert store.events() == []
    assert not store.db.in_transaction
    assert list(store.shots.iterdir()) == []
    assert list(store.states.iterdir()) == []
    eid = store.add_event(event, snap(), b'image', b'state')
    assert len(store.events()) == 1
    assert (store.shots / store.event(eid)['shot']).read_bytes() == b'image'
    # The state is stored compressed, so read it the way the emulator does.
    from pokesim.checkpoints import open_state
    with open_state(store.states / store.event(eid)['state']) as handle:
        assert handle.read() == b'state'


def test_failed_event_update_rolls_back_attachments(store):
    import sqlite3

    store.db.set_authorizer(
        lambda action, table, *_: sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_UPDATE and table == 'events' else sqlite3.SQLITE_OK
    )
    with pytest.raises(sqlite3.DatabaseError, match='not authorized'):
        store.add_event(Event('catch', 'Caught a partner'), snap(), b'image', b'state')
    store.set('unrelated', True)
    assert store.events() == []
    assert list(store.shots.iterdir()) == []
    assert list(store.states.iterdir()) == []


def test_event_save_states_are_stored_compressed(store):
    """A notable entry keeps a full 167 KB save state so the journal can rewind to it.

    They are only ever added to, never rewritten, so uncompressed they dominate an
    adventure's disk: a live server was carrying 456 MB of them across two adventures.
    A PyBoy state is mostly zeroed RAM and compresses about ten to one.
    """
    from pokesim.checkpoints import GZIP_MAGIC, open_state

    raw = bytes(256) * 655
    event = Event('badge', 'Beat Brock!', priority=4)
    eid = store.add_event(event, snap(), b'png-bytes', raw)

    written = store.states / f'event-{eid}.state'
    assert written.read_bytes()[:2] == GZIP_MAGIC
    assert written.stat().st_size < len(raw) // 4
    with open_state(written) as handle:
        assert handle.read() == raw


def test_save_states_written_before_compression_still_load(tmp_path):
    """An existing library must keep resuming and every old journal entry keep its rewind."""
    from pokesim.checkpoints import open_state

    raw = bytes(range(256)) * 32
    legacy = tmp_path / 'auto-v1-legacy.state'
    legacy.write_bytes(raw)
    with open_state(legacy) as handle:
        assert handle.read() == raw
