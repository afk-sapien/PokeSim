"""A cancel asked for while a chosen trade starts, Auto trading turned off meanwhile, and starts with PokeSim under the caps."""
import pytest

from pokesim.app import trade_settings
from pokesim.app.coordinator import Waiting

from test_accounts import library, people  # noqa: F401  (fixtures)
from test_rights_round25 import recorded_plans
from test_user_deletion import quiet  # noqa: F401  (fixture)


def chosen(coordinator, people, monkeypatch):
    monkeypatch.setattr(coordinator, 'manual_game_reason', lambda game: '')
    return coordinator.enqueue_manual({'left_id': people.red, 'left_key': 'a', 'right_id': people.blue, 'right_key': 'b'})


def state_of(coordinator, mid):
    return next(entry for entry in coordinator._manual_entries() if entry['id'] == mid)


def test_a_cancel_asked_for_while_a_chosen_trade_starts_is_kept(quiet, people, monkeypatch):  # noqa: F811
    coordinator = quiet.manager.coordinator
    entry = chosen(coordinator, people, monkeypatch)

    def busy(data, **options):
        # The owner cancels while the trade is starting, then an adventure turns out to be busy.
        coordinator._manual_update(entry['id'], cancel_requested=True)
        raise Waiting('An adventure is already held for an exchange')
    monkeypatch.setattr(coordinator, 'propose', busy)
    coordinator.drain_manual()
    assert state_of(coordinator, entry['id'])['state'] == 'cancelled'
    # A restart that cut a cancelled trade off while it started does not put it back in line.
    other = chosen(coordinator, people, monkeypatch)
    coordinator._manual_update(other['id'], state='starting', cancel_requested=True)
    proposed = []
    monkeypatch.setattr(coordinator, 'propose', lambda data, **options: proposed.append(data))
    coordinator.drain_manual()
    assert state_of(coordinator, other['id'])['state'] == 'cancelled'
    assert proposed == []


def test_an_automatic_trade_waits_when_auto_trading_was_turned_off(quiet, people, monkeypatch):  # noqa: F811
    manager = quiet.manager
    coordinator = manager.coordinator
    for aid in (people.red, people.blue):
        trade_settings.update(manager.registry, aid, across_owners=True)
    owners = {people.red: people.alice['id'], people.blue: people.bob['id']}
    recorded = recorded_plans(coordinator, monkeypatch, manual=False)
    trade_settings.update(manager.registry, people.blue, enabled=False)
    trade = {'left_id': people.red, 'left_key': 'a', 'right_id': people.blue, 'right_key': 'b'}
    with pytest.raises(Waiting):
        coordinator.propose(trade, owners=owners, across=True)
    assert recorded == []


def test_starting_with_pokesim_stays_under_the_member_cap(quiet, people, monkeypatch):  # noqa: F811
    import pokesim.checkpoints
    from pokesim.app import deletion
    manager = quiet.manager
    registry = manager.registry
    started = []
    for name in ('announce_setup', 'resume_orphans'):
        monkeypatch.setattr(manager, name, lambda: None)
    for part, names in ((manager.watchdog, ('install', 'run')), (manager.coordinator, ('recover', 'start_scheduler')),
                        (manager.supervisor, ('run_monitor',)), (manager.offers, ('run',)), (manager.leases, ('run',))):
        for name in names:
            monkeypatch.setattr(part, name, lambda: None)
    monkeypatch.setattr(deletion, 'recover_deletions', lambda manager: None)
    monkeypatch.setattr(pokesim.checkpoints, 'compress_event_states', lambda *args, **kwargs: None)
    monkeypatch.setattr(manager.supervisor, 'start', started.append)
    registry.set_setting('running_caps', {'server': None, 'member': 1})
    for row in registry.adventures():
        registry.update(row['id'], desired_state='stopped')
    kept = quiet.adventure('Kept', people.alice)
    registry.update(kept, desired_state='running')
    green = quiet.adventure('Green', people.alice)
    for aid in (people.red, green):
        registry.update(aid, settings={**registry.adventure(aid)['settings'], 'auto_start': True})
    # The fixture keeps the app from starting adventures, so this calls the real start.
    type(manager).start(manager)
    # The adventure already running keeps its place, and the two that only start with PokeSim wait.
    assert started == [kept]
    for aid in (people.red, green):
        row = registry.adventure(aid)
        assert (row['state'], row['desired_state']) == ('stopped', 'stopped')
        assert '1 of 1' in row['error']
