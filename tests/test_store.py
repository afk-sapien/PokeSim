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
    assert (store.states / store.event(eid)['state']).read_bytes() == b'state'


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
