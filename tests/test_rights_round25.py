"""A chosen or automatic trade, and an upload, refused when owners or rights changed meanwhile."""
import pytest

from pokesim.app import coordinator as coordinator_module, ownership, trade_settings
from pokesim.app.coordinator import Waiting
from pokesim.trade.worth import Gain

from test_accounts import library, meanwhile, people  # noqa: F401  (fixtures)
from test_user_deletion import quiet  # noqa: F401  (fixture)


def recorded_plans(coordinator, monkeypatch, manual):
    """Stub what `propose` asks the adventures, and return the list each recorded plan joins."""
    recorded = []
    monkeypatch.setattr(coordinator, '_admit', lambda tid, selection: None)
    if manual:
        monkeypatch.setattr(coordinator, 'manual_inventory', lambda aid: {})
        monkeypatch.setattr(coordinator, '_manual_offer', lambda inventory, key: {})
    else:
        monkeypatch.setattr(coordinator, 'inventory', lambda aid: {'offers': [{}]})
        monkeypatch.setattr(coordinator_module, 'find', lambda offers, key: {})
        monkeypatch.setattr(coordinator_module, 'gain', lambda inventory, offer: Gain(0))
        monkeypatch.setattr(coordinator, '_last_copies_useful', lambda *values: True)
    monkeypatch.setattr(coordinator, '_mon_display', lambda offer: {})
    monkeypatch.setattr(coordinator, '_offer_for', lambda offer, inventory: {})
    monkeypatch.setattr(coordinator, '_compatible_pair', lambda *sides: True)
    monkeypatch.setattr(coordinator.registry, 'create_transaction', lambda tid, plan: recorded.append(plan))
    return recorded


def test_a_chosen_trade_already_starting_stops_when_an_adventure_changes_hands(quiet, people, monkeypatch):  # noqa: F811
    manager = quiet.manager
    coordinator = manager.coordinator
    admin = manager.actor_for(people.admin)
    monkeypatch.setattr(coordinator, 'manual_game_reason', lambda game: '')
    entry = coordinator.enqueue_manual({'left_id': people.red, 'left_key': 'a', 'right_id': people.blue, 'right_key': 'b'})
    assert entry['owners'] == {people.red: people.alice['id'], people.blue: people.bob['id']}
    assert coordinator._manual_claim(entry['id'])
    ownership.transfer(manager, people.red, people.bob['id'], admin)
    starting = next(item for item in coordinator._manual_entries() if item['id'] == entry['id'])
    assert starting['cancel_requested'] is True
    recorded = recorded_plans(coordinator, monkeypatch, manual=True)
    trade = {'left_id': people.red, 'left_key': 'a', 'right_id': people.blue, 'right_key': 'b',
             'request_id': entry['id'], 'manual': True}
    with pytest.raises(ValueError, match='changed hands'):
        coordinator.propose(trade, owners=starting['owners'])
    assert recorded == []


def test_an_automatic_trade_waits_when_owners_or_trading_with_others_changed(quiet, people, monkeypatch):  # noqa: F811
    manager = quiet.manager
    coordinator = manager.coordinator
    admin = manager.actor_for(people.admin)
    for aid in (people.red, people.blue):
        trade_settings.update(manager.registry, aid, across_owners=True)
    owners = {people.red: people.alice['id'], people.blue: people.bob['id']}
    recorded = recorded_plans(coordinator, monkeypatch, manual=False)
    trade = {'left_id': people.red, 'left_key': 'a', 'right_id': people.blue, 'right_key': 'b'}
    # Bob turned trading with other people off after the pair was chosen.
    trade_settings.update(manager.registry, people.blue, across_owners=False)
    with pytest.raises(Waiting):
        coordinator.propose(trade, owners=owners, across=True)
    # Red moved to Bob after the pair was chosen.
    trade_settings.update(manager.registry, people.blue, across_owners=True)
    ownership.transfer(manager, people.red, people.bob['id'], admin)
    with pytest.raises(Waiting):
        coordinator.propose(trade, owners=owners, across=True)
    assert recorded == []


def test_uploads_check_rights_again_once_the_body_is_in(quiet, people, meanwhile, monkeypatch):  # noqa: F811
    from pokesim.app import migration
    manager = quiet.manager
    admin = manager.actor_for(people.admin)
    imported, added = [], []
    monkeypatch.setattr(migration, 'import_archive', lambda *args, **kwargs: imported.append(args) or {})
    monkeypatch.setattr(manager.assets, 'add_cartridge', lambda *args: added.append(args) or {'raw': b''})
    carol = quiet.user('carol', 'admin')
    client = quiet.login('carol')
    meanwhile(lambda: ownership.change_user(manager, carol['id'], admin, role='member'))
    uploaded = client.post('/api/v1/backups/upload', content=b'PK')
    assert uploaded.status_code in {401, 403}, uploaded.text
    assert not list((manager.root / 'backups').glob('*.zip'))
    ownership.change_user(manager, carol['id'], admin, role='admin')
    meanwhile(lambda: ownership.change_user(manager, carol['id'], admin, role='member'))
    moved = client.post('/api/v1/imports', content=b'PK')
    assert moved.status_code in {401, 403}, moved.text
    assert imported == []
    alice = quiet.login('alice')
    meanwhile(lambda: ownership.change_user(manager, people.alice['id'], admin, disabled=True))
    cartridge = alice.post('/api/v1/assets/rom', content=b'ROM')
    assert cartridge.status_code in {401, 403}, cartridge.text
    assert added == []
