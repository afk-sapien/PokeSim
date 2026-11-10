"""The live smoke suite: it passes on a sound Library, names each failure, and always cleans up."""
from fastapi.testclient import TestClient
import pytest

from pokesim.app import cli, smoke
from pokesim.app.manager import Manager, create_app

from test_accounts import library  # noqa: F401  (fixture)


@pytest.fixture
def served(library, monkeypatch):  # noqa: F811
    """The accounts Library with an admin, its command line token and a cartridge for the admin to add."""
    manager = library.manager
    admin = library.user('admin', 'admin')
    manager.bind_library_owner(admin['id'])
    token = manager.issue_cli_token()

    def add_cartridge(raw, slot=None, owner=None):
        rom = manager.registry.add_rom('smoke', 'sha1', 'blue')
        return {'rom': rom, 'title': 'Pokémon Red', 'message': 'added', 'raw': raw}
    monkeypatch.setattr(manager.assets, 'add_cartridge', add_cartridge)
    monkeypatch.setattr(manager.assets, 'install_portraits_quietly', lambda raw: 0)
    library.token = token
    return library


def run(library, **options):  # noqa: F811
    return smoke.run('http://testserver', library.token, connect=lambda: TestClient(library.app),
                     rom=b'cartridge', **options)


def traces(manager):
    return ({user['id'] for user in manager.auth.users()}, [row['id'] for row in manager.auth.invites()],
            {row['id'] for row in manager.registry.adventures()}, manager.registry.roms())


def test_a_sound_library_passes_and_keeps_no_trace(served):
    before = traces(served.manager)
    report = run(served)
    assert report.failures == [], report.failures
    assert report.passed >= 30 and report.skipped == []
    assert traces(served.manager) == before
    assert list((served.manager.root / 'backups').glob('*.zip')) == []
    assert list((served.manager.root / '.deleted-adventures').glob('*')) == []


def test_each_failure_is_one_line_and_cleanup_still_runs(served, monkeypatch):
    before = traces(served.manager)
    # A broken check lets one member read every adventure.
    monkeypatch.setattr('pokesim.app.manager.can', lambda actor, action, adventure=None: True)
    report = run(served)
    assert report.failures and all('\n' not in line for line in report.failures)
    assert any("member A read member B's adventure" in line for line in report.failures)
    assert traces(served.manager) == before


def test_a_failure_partway_still_removes_the_throwaway_users(served, monkeypatch):
    before = traces(served.manager)

    def broken(*args, **kwargs):
        raise RuntimeError('the server went away')
    monkeypatch.setattr(smoke.Smoke, 'isolation', broken)
    report = run(served)
    assert any('the server went away' in line for line in report.failures)
    assert traces(served.manager) == before


def test_without_a_cartridge_the_adventure_checks_are_skipped_not_failed(served):
    report = smoke.run('http://testserver', served.token, connect=lambda: TestClient(served.app), rom=None)
    assert report.failures == [] and report.skipped


def test_a_backup_is_made_only_when_asked(served, monkeypatch):
    made = []
    monkeypatch.setattr('pokesim.app.backup.create_backup', lambda manager: made.append(1) or {'ok': True})
    assert run(served).failures == [] and made == []
    assert run(served, with_backup=True).failures == [] and made == [1]


def test_an_open_library_has_no_login_wall(tmp_path, monkeypatch):
    for name in ('AUTH', 'API_DOCS', 'OIDC_ISSUER', 'AUTH_PROXY_HEADER'):
        monkeypatch.delenv(name, raising=False)
    manager = Manager(tmp_path, 'http://testserver', auth='none')
    monkeypatch.setattr(manager, 'start', lambda: None)
    token = manager.issue_cli_token()
    app = create_app(manager)
    report = smoke.run('http://testserver', token, connect=lambda: TestClient(app))
    assert report.failures == [], report.failures
    assert report.mode == 'none' and report.passed >= 6


def test_the_command_prints_one_line_per_failure_and_exits_non_zero(tmp_path, monkeypatch, capsys):
    (tmp_path / 'manager.json').write_text('{"url": "http://127.0.0.1:9", "application_id": "x"}')
    (tmp_path / 'cli.token').write_text('secret')
    seen = {}

    def fake(base_url, token, rom=None, with_backup=False, **options):
        seen.update(base_url=base_url, token=token, with_backup=with_backup)
        return smoke.Report(failures=['login limiter: got 401 401', 'docs: anonymous got 200'])
    monkeypatch.setattr(smoke, 'run', fake)
    with pytest.raises(SystemExit) as stopped:
        cli.main(['smoke', '--data-dir', str(tmp_path), '--url', 'https://pokesim.example/', '--with-backup'])
    assert stopped.value.code == 1
    assert capsys.readouterr().err.splitlines() == ['FAIL login limiter: got 401 401', 'FAIL docs: anonymous got 200']
    assert seen == {'base_url': 'https://pokesim.example', 'token': 'secret', 'with_backup': True}


def test_the_command_defaults_to_the_address_in_manager_json(tmp_path, monkeypatch, capsys):
    (tmp_path / 'manager.json').write_text('{"url": "http://127.0.0.1:9", "application_id": "x"}')
    (tmp_path / 'cli.token').write_text('secret')
    seen = []

    def fake(base_url, token, **options):
        seen.append(base_url)
        return smoke.Report(passed=3, skipped=['no cartridge'], mode='accounts')
    monkeypatch.setattr(smoke, 'run', fake)
    cli.main(['smoke', '--data-dir', str(tmp_path)])
    assert capsys.readouterr().out.splitlines() == ['SKIP no cartridge', 'PokeSim smoke: 3 checks passed, accounts mode']
    assert seen == ['http://127.0.0.1:9']
