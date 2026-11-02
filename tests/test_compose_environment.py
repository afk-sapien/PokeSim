"""Keep the Compose files passing the account settings that the authentication docs promise."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ('compose.yaml', 'compose.quickstart.yaml')
DOCS = (ROOT / 'docs' / 'authentication.md').read_text(encoding='utf-8')
# Provider and proxy settings have non-empty defaults in the code, so an empty value from
# Compose would override them. The docs say to add these by hand.
BY_HAND = {'AUTH_ADMIN_GROUP', 'AUTH_MEMBER_GROUP', 'AUTH_PROXY_DEFAULT_ROLE', 'AUTH_PROXY_GROUPS_HEADER',
           'AUTH_PROXY_HEADER', 'AUTH_PROXY_SECRET', 'DISABLE_PASSWORD_LOGIN', 'OIDC_CLIENT_ID',
           'OIDC_CLIENT_SECRET', 'OIDC_DEFAULT_ROLE', 'OIDC_GROUPS_CLAIM', 'OIDC_ISSUER', 'OIDC_SCOPES'}


def passed(name):
    return set(re.findall(r'^      ([A-Z_]+):', (ROOT / name).read_text(encoding='utf-8'), re.MULTILINE))


def read_by_code():
    source = '\n'.join(path.read_text(encoding='utf-8') for path in (ROOT / 'pokesim').rglob('*.py'))
    return set(re.findall(r"""(?:environ\.get\(|environ\[|env_flag\(|_env\()['"]([A-Z0-9_]+)['"]""", source))


def test_compose_files_pass_the_same_settings():
    assert passed('compose.yaml') == passed('compose.quickstart.yaml')


def test_documented_account_settings_reach_the_app():
    documented = set(re.findall(r'`([A-Z][A-Z0-9_]+)`', DOCS)) & read_by_code()
    assert {'AUTH', 'AUTH_TRUSTED_PROXIES', 'POKESIM_ADMIN_USER', 'POKESIM_ADMIN_PASSWORD'} <= documented
    for name in COMPOSE_FILES:
        assert documented - passed(name) == BY_HAND, name
    assert 'under `environment:` yourself' in DOCS


def test_compose_files_pass_only_settings_the_app_reads():
    code = read_by_code() | {'PUBLIC_URL', 'PORT'}
    for name in COMPOSE_FILES:
        assert passed(name) <= code, name
