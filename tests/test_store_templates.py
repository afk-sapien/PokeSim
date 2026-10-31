"""Keep the app store templates in step with compose.quickstart.yaml and the package version."""
from pathlib import Path
import re
import tomllib
import xml.etree.ElementTree as ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[1]
STORES = ROOT / 'deploy' / 'stores'
VERSION = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
QUICKSTART = (ROOT / 'compose.quickstart.yaml').read_text()
ENVIRONMENT = sorted(set(re.findall(r'^      ([A-Z_]+):', QUICKSTART, re.MULTILINE)))
COMPOSE_TEMPLATES = ('casaos/docker-compose.yml', 'umbrel/pokesim/docker-compose.yml')


def test_quickstart_facts_the_templates_copy():
    assert ENVIRONMENT == ['NTFY_MIN_PRIORITY', 'NTFY_MUTE', 'NTFY_TOKEN', 'NTFY_URL', 'PORT', 'PUBLIC_URL']
    assert '8930}:8000"' in QUICKSTART
    assert ':/data\n' in QUICKSTART


@pytest.mark.parametrize('name', COMPOSE_TEMPLATES)
def test_compose_templates_match_the_quickstart(name):
    text = (STORES / name).read_text()
    assert f'    image: ghcr.io/afk-sapien/pokesim:{VERSION}\n' in text
    for key in ENVIRONMENT:
        assert f'      {key}: ' in text
    assert '      NTFY_MIN_PRIORITY: "2"\n' in text
    assert '      PORT: "8000"\n' in text
    for line in ('    cap_drop: [ALL]\n', '    read_only: true\n', '      - no-new-privileges:true\n',
                 '      - /tmp:size=256m,mode=1777\n', '    stop_grace_period: 90s\n', '    init: true\n'):
        assert line in text
    assert '/data\n' in text


def test_unraid_template_matches_the_quickstart():
    root = ElementTree.parse(STORES / 'unraid' / 'pokesim.xml').getroot()
    assert root.findtext('Repository') == f'ghcr.io/afk-sapien/pokesim:{VERSION}'
    configs = {config.get('Target'): config for config in root.iter('Config')}
    assert sorted(key for key in configs if key.isupper()) == ENVIRONMENT
    assert configs['8000'].get('Type') == 'Port' and configs['8000'].get('Default') == '8930'
    assert configs['/data'].get('Type') == 'Path'
    assert configs['PUBLIC_URL'].get('Required') == 'true'
    assert configs['NTFY_MIN_PRIORITY'].get('Default') == '2'
    assert configs['NTFY_TOKEN'].get('Mask') == 'true'
    flags = root.findtext('ExtraParams').split()
    for flag in ('--init', '--read-only', 'ALL', 'no-new-privileges:true', '/tmp:size=256m,mode=1777'):
        assert flag in flags


def test_umbrel_manifest_names_the_release():
    manifest = (STORES / 'umbrel' / 'pokesim' / 'umbrel-app.yml').read_text()
    assert f'version: "{VERSION}"\n' in manifest
    assert 'port: 8930\n' in manifest
    assert (STORES / 'umbrel' / 'pokesim' / 'data' / '.gitkeep').exists()


def test_truenas_app_matches_the_quickstart():
    app = STORES / 'truenas' / 'pokesim'
    assert f'app_version: {VERSION}\n' in (app / 'app.yaml').read_text()
    values = (app / 'ix_values.yaml').read_text()
    assert f'    repository: ghcr.io/afk-sapien/pokesim\n    tag: {VERSION}\n' in values
    assert '  container_port: 8000\n' in values
    template = (app / 'templates' / 'docker-compose.yaml').read_text()
    for key in ENVIRONMENT:
        assert f'add_env("{key}", ' in template
    assert 'add_storage("/data", values.storage.data)' in template
    questions = (app / 'questions.yaml').read_text()
    assert '                  default: 8930\n' in questions
    for variable in ('public_url', 'ntfy_url', 'ntfy_token', 'ntfy_min_priority', 'ntfy_mute'):
        assert f'        - variable: {variable}\n' in questions
