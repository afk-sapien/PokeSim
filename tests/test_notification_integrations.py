"""Independent subscriptions, migration and credentials for named integrations."""
import copy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from pokesim import notify
from pokesim.app import notifications
from pokesim.app.notifications import CATEGORIES, NotificationCenter, defaults
from pokesim.events import Event, HIGH, URGENT
from test_notifications import client, adventure, sender, WEBHOOK, BOT_TOKEN, SECRET  # noqa: F401

API = '/api/v1/notifications/integrations'


def add(client, **changes):
    response = client.post(API, json={'name': 'My chat', 'provider': 'telegram', 'telegram_token': BOT_TOKEN,
                                      'telegram_chat_id': '123', **changes})
    assert response.status_code == 200, response.text
    return response.json()['integrations'][-1]


def test_duplicate_provider_crud_credentials_and_restart(client):
    client, manager = client
    a = add(client, name='Private phone')
    b = add(client, name='Group chat', telegram_chat_id='-456')
    assert a['id'] != b['id']
    for row in (a, b):
        assert row['telegram_token_set'] and 'telegram_token' not in row
    response = client.patch(API + '/' + a['id'], json={'name': 'Renamed', 'enabled': False})
    assert response.status_code == 200
    assert BOT_TOKEN not in response.text
    fresh = NotificationCenter(manager.registry, manager.supervisor, manager.public_url)
    rows = fresh.public()['integrations']
    assert [(row['name'], row['enabled']) for row in rows] == [('Renamed', False), ('Group chat', True)]
    assert fresh.settings()['integrations'][0]['telegram_token'] == BOT_TOKEN
    assert client.delete(API + '/' + a['id']).status_code == 200
    assert [row['id'] for row in fresh.public()['integrations']] == [b['id']]
    assert client.delete(API + '/' + a['id']).status_code == 409
    assert client.patch('/api/v1/notifications', json={'provider': 'ntfy'}).status_code == 409
    assert len(fresh.public()['integrations']) == 1


def test_migration_preserves_disabled_destinations_filters_and_environment(client):
    client, manager = client
    red, blue = adventure(manager, 'Red'), adventure(manager, 'Blue')
    old = {**defaults(), 'enabled': True, 'provider': 'telegram',
           'providers': {'ntfy': True, 'discord': False, 'telegram': True},
           'topic': 'old-topic', 'token': SECRET, 'discord_webhook': WEBHOOK,
           'telegram_token': BOT_TOKEN, 'telegram_chat_id': '123', 'muted_adventures': [blue]}
    old['categories']['league'] = False
    manager.registry.set_setting('notifications', old)
    rows = manager.notifications.public()['integrations']
    assert len(rows) == 3
    assert rows[1]['enabled'] is False
    assert all(not row['categories']['league'] for row in rows)
    assert all(row['adventures'] == {red: True, blue: False} for row in rows)
    # A credential-only edit migrates all destinations and keeps every subscription.
    response = client.patch(API + '/legacy-telegram', json={'telegram_chat_id': '456'})
    assert response.status_code == 200
    stored = manager.notifications.settings()['integrations']
    assert len(stored) == 3
    assert stored[0]['telegram_token'] == '' and stored[2]['discord_webhook'] == ''
    assert stored[0]['token'] == SECRET and stored[1]['discord_webhook'] == WEBHOOK
    assert all(row['adventures'][blue] is False for row in response.json()['integrations'])


def test_event_and_adventure_filters_are_applied_at_actual_delivery(client, monkeypatch):
    client, manager = client
    red, blue = adventure(manager, 'Red'), adventure(manager, 'Blue')
    off = {key: False for key, *_ in CATEGORIES}
    add(client, name='Red badges', categories={**off, 'badges': True},
                 include_new_adventures=False, adventures={red: True, blue: False})
    league = add(client, name='League chat', telegram_chat_id='456', categories={**off, 'league': True},
                 include_new_adventures=True, adventures={blue: False})
    assert client.patch('/api/v1/notifications', json={'enabled': True}).status_code == 200
    calls = []
    monkeypatch.setattr(notify, 'publish', lambda *args, **kw: calls.append(kw['chat_id']))
    monkeypatch.setattr(notify, 'threading', SimpleNamespace(
        Lock=notify.threading.Lock,
        Thread=lambda target, args, daemon: type('T', (), {'start': lambda self: target(*args)})(),
    ))
    live = sender(manager.notifications, manager.registry.adventure(red))
    assert live.wants(Event('badge', 'Badge', priority=HIGH))
    live.send('Badge', '', priority=HIGH, event_type='badge')
    assert calls == ['123']
    calls.clear()
    assert live.wants(Event('trainer', 'Champion', priority=URGENT))
    live.send('Champion', '', priority=URGENT, event_type='trainer')
    assert calls == ['456']
    calls.clear()
    assert not live.wants(Event('trainer', 'Rival', priority=HIGH))
    live.send('Rival', '', priority=HIGH, event_type='trainer')
    assert calls == []
    assert not sender(manager.notifications, manager.registry.adventure(blue)).wants(Event('badge', 'Badge', priority=HIGH))
    new = adventure(manager, 'New Red')
    newcomer = sender(manager.notifications, manager.registry.adventure(new))
    assert not newcomer.wants(Event('badge', 'Badge', priority=HIGH))
    assert newcomer.wants(Event('champion', 'Win', priority=URGENT))
    client.patch(API + '/' + league['id'], json={'enabled': False})
    live.configure(manager.notifications.worker_settings(manager.registry.adventure(red)))
    assert not live.wants(Event('champion', 'Win', priority=URGENT))
    client.patch('/api/v1/notifications', json={'enabled': False})
    live.configure(manager.notifications.worker_settings(manager.registry.adventure(red)))
    live.send('Badge', '', priority=HIGH, event_type='badge')
    assert calls == []


def test_tests_target_only_the_named_integration_and_keep_unsaved_edits_private(client, monkeypatch):
    client, manager = client
    a = add(client, name='One')
    add(client, name='Two', telegram_chat_id='456')
    sent = []
    monkeypatch.setattr(notifications, 'publish', lambda *args, **kw: sent.append(kw['chat_id']))
    result = client.post(API + '/' + a['id'] + '/test', json={'telegram_chat_id': '789'})
    assert result.json()['ok']
    assert sent == ['789']
    assert manager.notifications.public()['integrations'][0]['telegram_chat_id'] == '123'
    result = client.post(API + '/missing/test', json={})
    assert result.status_code == 409
    assert sent == ['789']


@pytest.mark.parametrize('change', [{'name': ''}, {'provider': 'ntfy'}, {'min_priority': True},
                                  {'enabled': 'yes'}, {'categories': {'badges': 1}},
                                  {'adventures': {'missing': True}}, {'include_new_adventures': 1},
                                  {'telegram_token': ''}, {'token': 'wrong-provider'}])
def test_invalid_edits_are_atomic(client, change):
    client, manager = client
    row = add(client)
    before = copy.deepcopy(manager.notifications.settings())
    response = client.patch(API + '/' + row['id'], json=change)
    assert response.status_code == 409
    assert manager.notifications.settings() == before


def test_trade_notifies_each_eligible_integration_once(client, monkeypatch):
    client, manager = client
    red, blue = adventure(manager, 'Red'), adventure(manager, 'Blue')
    add(client, categories={'trades': True}, adventures={red: True, blue: True})
    add(client, telegram_chat_id='456', categories={'trades': False})
    add(client, telegram_chat_id='789', categories={'trades': True}, adventures={red: False, blue: False})
    client.patch('/api/v1/notifications', json={'enabled': True})
    sent = []
    monkeypatch.setattr(notifications, 'publish', lambda *args, **kw: sent.append(kw['chat_id']))
    manager.notifications.trade_completed({'plan': {'participants': [red, blue]}}, {}).join(5)
    assert sent == ['123']


def test_concurrent_integration_additions_are_not_lost(client):
    _, manager = client
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: manager.notifications.save_integration({
            'name': f'Chat {i}', 'provider': 'telegram', 'telegram_token': BOT_TOKEN,
            'telegram_chat_id': str(i + 1)}), range(8)))
    assert len(manager.notifications.public()['integrations']) == 8


def test_create_retry_keeps_one_integration(client):
    client, manager = client
    data = {'request_id': 'a' * 32, 'name': 'Phone', 'provider': 'telegram',
            'telegram_token': BOT_TOKEN, 'telegram_chat_id': '123'}
    first = client.post(API, json=data)
    second = client.post(API, json=data)
    assert first.status_code == second.status_code == 200
    assert len(second.json()['integrations']) == 1
    assert second.json()['integrations'][0]['id'] == 'a' * 32


def test_environment_subscription_is_retained_when_another_integration_is_added(client):
    _, manager = client
    center = NotificationCenter(manager.registry, manager.supervisor, manager.public_url, environ={
        'NTFY_URL': 'https://ntfy.sh/legacy', 'NTFY_TOKEN': SECRET, 'NTFY_MUTE': 'trainer',
    })
    center.save_integration({'name': 'Phone', 'provider': 'telegram', 'telegram_token': BOT_TOKEN,
                             'telegram_chat_id': '123'})
    values = center.settings()
    assert values['enabled'] is True
    assert values['integrations'][0]['token'] == SECRET
    assert values['integrations'][0]['mute'] == ['trainer']
    assert len(values['integrations']) == 2
