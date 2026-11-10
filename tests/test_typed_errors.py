"""A request's own errors keep their status codes quietly, and an untyped builtin is a logged 500."""
import ast
import logging
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from pokesim.app import auth, cable_sessions, coordinator
from pokesim.app.errors import Conflict, NotFound, Refused
from pokesim.app.manager import UNEXPECTED, Manager, create_app
from pokesim.app.offers import LimitReached
from pokesim.app.registry import identifier
from pokesim.app.watchdog import ErrorLog, _LogHandler


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


@pytest.mark.parametrize('error', [KeyError('slot'), ValueError('bad level'), RuntimeError('lock held')])
def test_an_untyped_builtin_logs_its_traceback(client, monkeypatch, caplog, error):
    response, logged = answer(client, monkeypatch, caplog, error)
    assert response.status_code == 500 and response.json() == {'detail': UNEXPECTED}
    assert UNEXPECTED == 'PokeSim hit an unexpected error. The log has the details.'
    assert len(logged) == 1 and logged[0].levelno == logging.ERROR
    assert logged[0].exc_info[1] is error
    assert 'GET /api/v1/adventures/' in logged[0].getMessage() and type(error).__name__ in logged[0].getMessage()


def test_the_watchdog_counts_an_untyped_builtin_as_an_unexpected_error(client, monkeypatch, caplog):
    errors = ErrorLog()
    handler = _LogHandler(errors)
    logging.getLogger().addHandler(handler)
    try:
        answer(client, monkeypatch, caplog, ValueError('bad level'))
    finally:
        logging.getLogger().removeHandler(handler)
    assert [signature.split(' in ')[0] for _, signature, _ in errors.since(0)] == ['ValueError']


BUILTINS = {'ValueError', 'KeyError', 'RuntimeError'}


@pytest.mark.parametrize('module', [auth, coordinator, cable_sessions], ids=lambda module: module.__name__)
def test_sign_in_and_trade_modules_raise_only_typed_errors(module):
    """A bad sign-in, invite or cable request answers 404 or 409, never an unexpected 500."""
    path = Path(module.__file__)
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Raise) and node.exc is not None:
            raised = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(raised, ast.Name) and raised.id in BUILTINS:
                found.append(f'{path.name}:{node.lineno} raises a bare {raised.id}')
    assert not found, 'Raise NotFound, Conflict or Refused from pokesim.app.errors instead:\n' + '\n'.join(found)


def test_a_named_error_keeps_its_own_answer_over_its_typed_base(client, monkeypatch, caplog):
    assert issubclass(LimitReached, Conflict)
    response, logged = answer(client, monkeypatch, caplog, LimitReached('Too many open offers'))
    assert response.status_code == 429 and logged == []
