"""A request's own errors keep their status codes quietly, and an untyped builtin leaves a traceback."""
import logging

from fastapi.testclient import TestClient
import pytest

from pokesim.app.errors import Conflict, NotFound, Refused
from pokesim.app.manager import Manager, create_app
from pokesim.app.offers import LimitReached
from pokesim.app.registry import identifier


@pytest.fixture
def client(tmp_path, monkeypatch):
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    with TestClient(create_app(manager)) as client:
        yield client, manager


def answer(client, monkeypatch, caplog, error):
    """What the library answers when reading one adventure raises this error, and what it logs."""
    client, manager = client
    monkeypatch.setattr(manager.registry, 'adventure', lambda aid: (_ for _ in ()).throw(error))
    with caplog.at_level(logging.WARNING, logger='pokesim.app.manager'):
        response = client.get(f'/api/v1/adventures/{identifier()}')
    return response, [record for record in caplog.records if record.name == 'pokesim.app.manager']


def test_a_missing_adventure_is_a_quiet_404(client, caplog):
    client, manager = client
    with caplog.at_level(logging.WARNING, logger='pokesim.app.manager'):
        response = client.get(f'/api/v1/adventures/{identifier()}')
    assert response.status_code == 404 and response.json() == {'detail': 'Adventure not found'}
    assert not [record for record in caplog.records if record.name == 'pokesim.app.manager']


@pytest.mark.parametrize(('error', 'status'), [
    (NotFound('That offer is gone'), 404),
    (Conflict('Pick a shorter name'), 409),
    (Refused('PokeSim is shutting down'), 409),
])
def test_a_typed_error_keeps_its_code_and_logs_nothing(client, monkeypatch, caplog, error, status):
    response, logged = answer(client, monkeypatch, caplog, error)
    assert response.status_code == status and response.json() == {'detail': str(error.args[0])}
    assert logged == []


@pytest.mark.parametrize(('error', 'status', 'detail'), [
    (KeyError('slot'), 404, 'slot'),
    (ValueError('bad level'), 409, 'bad level'),
    (RuntimeError('lock held'), 409, 'lock held'),
])
def test_an_untyped_builtin_logs_its_traceback(client, monkeypatch, caplog, error, status, detail):
    response, logged = answer(client, monkeypatch, caplog, error)
    assert response.status_code == status and response.json() == {'detail': detail}
    assert len(logged) == 1 and logged[0].levelno == logging.WARNING
    assert logged[0].exc_info[1] is error
    assert 'GET /api/v1/adventures/' in logged[0].getMessage() and type(error).__name__ in logged[0].getMessage()


def test_a_named_error_keeps_its_own_answer_over_its_typed_base(client, monkeypatch, caplog):
    assert issubclass(LimitReached, Conflict)
    response, logged = answer(client, monkeypatch, caplog, LimitReached('Too many open offers'))
    assert response.status_code == 429 and logged == []
