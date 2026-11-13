"""Checks from outside the app that refuse a request's values still answer 409, through validation.py.

A plain ValueError that reaches the manager is answered 500 as an unexpected error. So every app
module takes these checks from pokesim.app.validation, and a check taken straight from its own
module fails here in CI, named by file and line.
"""
import ast
import io
import logging
from pathlib import Path
import zipfile

from fastapi.testclient import TestClient
import pytest

from pokesim import cartridges, nicknames, palettes, randomized
from pokesim.app import validation
from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier
from pokesim.runtime import settings

APP = Path(validation.__file__).parent
WRAPPED = frozenset(validation.__all__)


def outside_app(module):
    inside = module == 'pokesim.app' or module.startswith('pokesim.app.')
    return (module == 'pokesim' or module.startswith('pokesim.')) and not inside


def dotted(node):
    """The dotted name an attribute chain such as `pokesim.palettes` spells, or None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return base and f'{base}.{node.attr}'
    return None


def unwrapped(source, package):
    """(line, what) for each check this source takes straight from a pokesim module outside the app."""
    tree = ast.parse(source)
    found, names = [], {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            parts = package.split('.')
            base = parts[:len(parts) - node.level + 1] if node.level else []
            origin = '.'.join(base + ([node.module] if node.module else []))
            for alias in node.names:
                names[alias.asname or alias.name] = f'{origin}.{alias.name}'
                if outside_app(origin) and (alias.name.startswith('validate') or alias.name in WRAPPED):
                    found.append((node.lineno, f'imports {alias.name} from {origin}'))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split('.')[0]
                names[bound] = alias.name if alias.asname else bound
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not (node.attr.startswith('validate') or node.attr in WRAPPED):
            continue
        head, _, rest = (dotted(node.value) or '').partition('.')
        if head in names:
            module = names[head] + (f'.{rest}' if rest else '')
            if outside_app(module):
                found.append((node.lineno, f'uses {module}.{node.attr}'))
    return found


def test_every_app_module_takes_outside_checks_from_validation():
    found = []
    for path in sorted(APP.rglob('*.py')):
        if path == APP / 'validation.py':
            continue
        relative = path.relative_to(APP.parents[1])
        for line, what in unwrapped(path.read_text(encoding='utf-8'), '.'.join(relative.parent.parts)):
            found.append(f'{relative}:{line} {what}')
    assert not found, ('Import these from pokesim.app.validation, which answers their ValueError as a Conflict, '
                       'and wrap any new one there:\n' + '\n'.join(found))


@pytest.mark.parametrize(('source', 'caught'), [
    ('from ..nicknames import validate_parts', True),
    ('from pokesim.palettes import validate_palette as check', True),
    ('from ..cartridges import unpack', True),
    ('from .. import randomized\nrandomized.validate(code)', True),
    ('import pokesim.runtime.settings\npokesim.runtime.settings.validate_speed(1)', True),
    ('import pokesim.runtime.settings as chosen\nchosen.validate_speed(1)', True),
    ('from .validation import validate_parts', False),
    ('from .registry import validate_id', False),
    ('manager.validate_adventure_settings({})', False),
    ('import struct\nstruct.unpack("<H", raw)', False),
])
def test_the_scan_tells_a_wrapped_check_from_an_unwrapped_one(source, caught):
    assert bool(unwrapped(source, 'pokesim.app')) is caught


def refusal(check, *args):
    """The message the outside check refuses these arguments with."""
    with pytest.raises(ValueError) as raised:
        check(*args)
    assert type(raised.value) is ValueError
    return str(raised.value)


def zip_without_a_game():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('readme.txt', 'No cartridge in here')
    return buffer.getvalue()


@pytest.fixture
def library(tmp_path, monkeypatch):
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    with TestClient(create_app(manager)) as client:
        headers = {'X-PokeSim-CSRF': client.get('/api/v1/session').json()['csrf_token']}
        manager.registry.add_rom('red-rom', 'sha1', 'red')
        manager.registry.add_rom('gold-rom', 'sha2', 'gold')
        ids = {'red': manager.registry.create('Red', 'red-rom', {}, identifier())['id'],
               'gold': manager.registry.create('Gold', 'gold-rom', {}, identifier())['id']}
        yield client, headers, ids


NEW_RED = {'name': 'Red', 'rom_id': 'red-rom'}


@pytest.mark.parametrize(('method', 'route', 'body', 'check', 'args'), [
    pytest.param('post', '/api/v1/adventures', {'json': {**NEW_RED, 'trainer_name': 'RED123'}},
                 nicknames.validate_trainer_name, ('RED123',), id='trainer name'),
    pytest.param('post', '/api/v1/adventures', {'json': {**NEW_RED, 'starter': 'mewtwo'}},
                 cartridges.validate_starter, ('mewtwo',), id='starter'),
    pytest.param('post', '/api/v1/adventures', {'json': {**NEW_RED, 'nicknames': 'off'}},
                 settings.validate_play_settings, ({'nicknames': 'off'},), id='nicknames at creation'),
    pytest.param('post', '/api/v1/adventures', {'json': {**NEW_RED, 'randomizer': 5}},
                 randomized.validate, (5,), id='randomizer at creation'),
    pytest.param('post', '/api/v1/adventures', {'json': {'name': 'Gold', 'rom_id': 'gold-rom', 'fair_wild_dvs': True}},
                 cartridges.validate_generation_settings, ({'fair_wild_dvs': True}, 'gold'), id='generation at creation'),
    pytest.param('patch', '/api/v1/adventures/{red}', {'json': {'settings': {'palette': 'neon'}}},
                 palettes.validate_palette, ('neon',), id='palette'),
    pytest.param('patch', '/api/v1/adventures/{red}', {'json': {'settings': {'speed': 99}}},
                 settings.validate_speed, (99,), id='speed'),
    pytest.param('patch', '/api/v1/adventures/{red}', {'json': {'settings': {'randomizer': 5}}},
                 randomized.validate, (5,), id='randomizer change'),
    pytest.param('patch', '/api/v1/adventures/{gold}', {'json': {'settings': {'fair_wild_dvs': True}}},
                 cartridges.validate_generation_settings, ({'fair_wild_dvs': True}, 'gold'), id='generation change'),
    pytest.param('patch', '/api/v1/adventures/{red}/play', {'json': {'play_style': 'story'}},
                 settings.validate_play_settings, ({'play_style': 'story'},), id='play settings'),
    pytest.param('patch', '/api/v1/settings', {'json': {'max_running': 3}},
                 nicknames.validate_parts, ({'max_running': 3},), id='nickname settings'),
    pytest.param('post', '/api/v1/cartridges', {'content': zip_without_a_game()},
                 cartridges.unpack, (zip_without_a_game(),), id='cartridge zip'),
])
def test_a_refused_value_is_a_quiet_409_with_the_check_message(library, caplog, method, route, body, check, args):
    client, headers, ids = library
    expected = refusal(check, *args)
    with caplog.at_level(logging.WARNING, logger='pokesim.app.manager'):
        response = getattr(client, method)(route.format(**ids), headers=headers, **body)
    assert response.status_code == 409 and response.json() == {'detail': expected}
    assert not [record for record in caplog.records if record.name == 'pokesim.app.manager']
