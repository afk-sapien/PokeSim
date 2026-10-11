"""Ask me first: automatic trades wait as requests until the owner accepts or dismisses them."""
import pytest

from pokesim import config
from pokesim.app import trade_requests, trade_settings
from pokesim.app.registry import identifier

from test_managed_coordinator import Peer, setup  # noqa: F401  (fixture)
from test_view_links import managed  # noqa: F401  (fixture)


@pytest.fixture
def asking(setup):  # noqa: F811
    trade_settings.set_ask_first(setup.registry, True)
    return setup


def pending(setup, aid=None):
    return setup.coordinator.requests.for_adventure(aid)['requests']


def stored(setup):
    return setup.registry.setting(trade_requests.KEY)['requests']


def test_ask_first_is_on_by_default(tmp_path):
    from pokesim.app.registry import Registry
    registry = Registry(tmp_path)
    try:
        assert trade_settings.ask_first(registry) is True
        trade_settings.set_ask_first(registry, False)
        assert trade_settings.ask_first(registry) is False
        with pytest.raises(ValueError):
            trade_settings.set_ask_first(registry, 'no')
    finally:
        registry.close()


def test_an_automatic_trade_waits_as_a_request(asking):
    c, left, right = asking.coordinator, asking.data['left_id'], asking.data['right_id']
    assert c.schedule_once() is None
    assert asking.cable_calls == [] and asking.registry.transactions() == []
    rows = pending(asking, right)
    assert len(rows) == 1
    row = rows[0]
    # The page's own adventure is always the left side.
    assert row['left']['adventure_id'] == right and row['right']['adventure_id'] == left
    assert row['left']['key'] == '1' and row['right']['key'] == '0'
    assert any('New Pokédex entry' in reason for reason in row['reasons'])
    assert row['left']['sprite_url'].startswith(f'/games/{right}/sprites/')
    assert 'waiting for you' in c.last_message
    # Another round finds the same pair and does not suggest it twice.
    assert c.schedule_once() is None
    assert len(pending(asking)) == 1


def test_accepting_queues_the_trade_like_a_hand_picked_one(asking):
    c = asking.coordinator
    c.schedule_once()
    rid = pending(asking)[0]['id']
    accepted = c.requests.accept(rid)
    assert accepted['status'] == 'accepted' and accepted['manual_id']
    assert c.manual_status(accepted['manual_id'])['state'] == 'queued'
    assert pending(asking) == []
    assert c.drain_manual()['phase'] == 'completed'
    assert asking.cable_calls == [accepted['manual_id']]
    with pytest.raises(ValueError, match='already accepted'):
        c.requests.accept(rid)


def test_a_dismissed_pair_is_not_suggested_again(asking):
    c = asking.coordinator
    c.schedule_once()
    rid = pending(asking)[0]['id']
    assert c.requests.dismiss(rid)['status'] == 'dismissed'
    c.schedule_once()
    assert pending(asking) == []
    # A different Pokémon makes a new pair, which may be suggested.
    asking.peers[asking.data['left_id']].key = '7'
    c.schedule_once()
    assert [row['right']['key'] for row in pending(asking, asking.data['right_id'])] == ['7']


def test_a_request_expires_when_a_pokemon_leaves_automatic_trading(asking):
    c, left = asking.coordinator, asking.data['left_id']
    c.schedule_once()
    rid = pending(asking)[0]['id']
    # Set to Never trade, moved to the party or traded away: it is no longer offered.
    asking.peers[left].key = 'moved'
    c.schedule_once()
    row = next(row for row in stored(asking) if row['id'] == rid)
    assert row['status'] == 'expired' and 'no longer available' in row['status_reason']


def test_a_request_expires_when_a_pokemon_evolves(asking):
    c, left = asking.coordinator, asking.data['left_id']
    c.schedule_once()
    rid = pending(asking)[0]['id']
    asking.peers[left].dex = 3
    c.schedule_once()
    row = next(row for row in stored(asking) if row['id'] == rid)
    assert row['status'] == 'expired' and 'evolved' in row['status_reason']


def test_a_game_that_was_not_read_keeps_its_requests(asking):
    c, left = asking.coordinator, asking.data['left_id']
    c.schedule_once()
    asking.registry.update(left, state='stopped', desired_state='stopped')
    c.schedule_once()
    assert len(pending(asking)) == 1


def test_accepting_a_stale_request_expires_it_instead(asking):
    c, left = asking.coordinator, asking.data['left_id']
    c.schedule_once()
    rid = pending(asking)[0]['id']
    asking.peers[left].key = 'gone'
    result = c.requests.accept(rid)
    assert result['status'] == 'expired' and c.manual_statuses()['trades'] == []


def test_at_most_three_requests_wait_and_none_share_a_pokemon(asking, monkeypatch):
    c = asking.coordinator
    for name, key in [('Third Red', '2'), ('Fourth Red', '3'), ('Fifth Red', '4'), ('Sixth Red', '5'),
                      ('Seventh Red', '6'), ('Eighth Red', '8')]:
        game = asking.registry.create(name, 'rom', {}, identifier())
        asking.registry.update(game['id'], state='running', desired_state='running')
        asking.peers[game['id']] = Peer(game['id'], key)
    c.schedule_once()
    rows = pending(asking)
    assert len(rows) == trade_requests.MAX_PENDING
    sides = [(row[side]['adventure_id'], row[side]['key']) for row in rows for side in ('left', 'right')]
    assert len(sides) == len(set(sides))


def test_ask_first_off_trades_at_once_as_before(asking):
    trade_settings.set_ask_first(asking.registry, False)
    assert asking.coordinator.schedule_once()['phase'] == 'completed'


def test_trade_request_routes(managed, monkeypatch):  # noqa: F811
    client, manager = managed.client, managed.manager
    data = client.get(f'/api/v1/interactions/trade-requests?adventure_id={managed.aid}').json()
    assert data == {'ask_first': True, 'requests': [], 'viewer_only': False}
    path = '/api/v1/interactions/trade-requests/settings'
    assert client.put(path, json={'ask_first': 'no'}).status_code == 400
    assert client.put(path, json={'ask_first': False}).json() == {'ask_first': False}
    assert trade_settings.ask_first(manager.registry) is False
    assert client.post(f'/api/v1/interactions/trade-requests/{identifier()}/dismiss').status_code == 404
    assert client.post(f'/api/v1/interactions/trade-requests/{identifier()}/other').status_code == 404
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    assert client.put(path, json={'ask_first': True}).status_code == 403
