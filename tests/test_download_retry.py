"""Pinned data downloads retry brief outages, explain failures in words, and heal themselves."""
from types import SimpleNamespace
import threading
from urllib.error import HTTPError, URLError

import pytest

from pokesim import downloads
from pokesim.app import supervisor as supervisor_module
from pokesim.app.registry import Registry, identifier
from pokesim.app.supervisor import Supervisor
from pokesim.downloads import DataDownloadError, retrying
from test_managed_supervisor import FakeChild

DNS = URLError(OSError(-5, 'No address associated with hostname'))


def test_a_brief_outage_is_retried_with_backoff_and_then_succeeds():
    calls, waits, reports = [], [], []
    def read():
        calls.append(1)
        if len(calls) < 3:
            raise DNS
        return b'ok'
    assert retrying(read, 'Pokémon Silver', reports.append, waits.append) == b'ok'
    assert waits == [2, 5]
    assert len(reports) == 2


def test_a_lasting_outage_ends_in_a_plain_message_after_bounded_attempts():
    calls, waits = [], []
    def read():
        calls.append(1)
        raise DNS
    with pytest.raises(DataDownloadError) as caught:
        retrying(read, 'Pokémon Silver', sleep=waits.append)
    assert str(caught.value) == "Couldn't download the Pokémon Silver game data (no network). Retry."
    assert len(calls) == downloads.ATTEMPTS
    assert waits == [2, 5, 15]


def test_a_missing_archive_is_not_retried_and_names_the_server_answer():
    calls = []
    def read():
        calls.append(1)
        raise HTTPError('https://example.invalid', 404, 'Not Found', {}, None)
    with pytest.raises(DataDownloadError, match='server answered 404'):
        retrying(read, 'Pokémon Gold', sleep=lambda _: pytest.fail('retried'))
    assert len(calls) == 1


def test_gen2_data_download_uses_the_shared_retry(monkeypatch, tmp_path):
    from pokesim.gen2 import data
    def offline(*args, **kwargs):
        raise DNS
    monkeypatch.setattr(data, 'urlopen', offline)
    monkeypatch.setattr(downloads.time, 'sleep', lambda _: None)
    with pytest.raises(DataDownloadError, match='Pokémon Silver game data \\(no network\\)'):
        data.ensure(tmp_path, 'silver')


@pytest.fixture
def supervisor(tmp_path):
    registry = Registry(tmp_path)
    registry.add_rom('digest', 'sha1', 'silver')
    rom = tmp_path / 'rom.gbc'
    rom.write_bytes(b'fake')
    state = {'offline': True}
    def prepare(version, report):
        if state['offline']:
            raise DataDownloadError("Couldn't download the Pokémon Silver game data (no network). Retry.")
    assets = SimpleNamespace(rom_path=lambda rid: rom, game_data_dir=tmp_path, prepare_gen2=prepare,
                             install_portraits=lambda raw: 0, cancelled=threading.Event())
    supervisor = Supervisor(registry, assets, 'http://127.0.0.1:8000', FakeChild)
    supervisor.state = state
    yield supervisor
    supervisor.close()
    registry.close()


def start_offline(supervisor):
    row = supervisor.registry.create('Cozy Escape', 'digest', {'starter': 'random'}, identifier())
    supervisor.registry.request_lifecycle(row['id'], 'start', identifier())
    with pytest.raises(DataDownloadError):
        supervisor.start(row['id'])
    return row['id']


def test_a_failed_download_is_retried_automatically_until_the_network_returns(supervisor):
    aid = start_offline(supervisor)
    row = supervisor.registry.adventure(aid)
    assert row['state'] == 'failed' and 'no network' in row['error']
    assert row['summary']['next_retry'] > 0
    supervisor.setup_retries[aid] = (0, 1)
    supervisor.run_setup_retries()
    assert supervisor.registry.adventure(aid)['state'] == 'failed'
    assert supervisor.setup_retries[aid][1] == 2
    supervisor.state['offline'] = False
    supervisor.setup_retries[aid] = (0, 2)
    supervisor.run_setup_retries()
    assert supervisor.registry.adventure(aid)['state'] == 'running'
    assert aid not in supervisor.setup_retries


def test_automatic_retries_are_bounded_and_skipped_for_a_stopped_adventure(supervisor):
    aid = start_offline(supervisor)
    for attempt in range(supervisor_module.SETUP_RETRIES + 1):
        supervisor.setup_retries[aid] = (0, supervisor_module.SETUP_RETRIES)
        supervisor.run_setup_retries()
    assert aid not in supervisor.setup_retries
    assert supervisor.registry.adventure(aid)['state'] == 'failed'
    supervisor.setup_retries[aid] = (0, 1)
    supervisor.registry.update(aid, desired_state='stopped')
    supervisor.run_setup_retries()
    assert aid not in supervisor.setup_retries
