"""Managed cable trades share unique boxed partners only for new registrations."""
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from pokesim.runtime.participant import Participant
from pokesim.strategy_data import SPECIES
from pokesim.trade.preferences import identity
from test_duplicates import snapshot, stored
from test_managed_coordinator import setup
from test_preparation import participant
from test_trade_diversity import completed, inventory, offer, selection

SPECIES_BY_DEX = {row['dex']: sid for sid, row in SPECIES.items()}


def runtime_inventory(emu, snap, collection=None):
    emu.status = lambda: {'game': snap.to_dict(), 'strategy': {'collection': collection}}
    owner = Participant(SimpleNamespace(store=emu.store, emulator=emu),
                        SimpleNamespace(adventure_id='red', generation=1))
    return owner.inventory()


@pytest.mark.parametrize('dex,evolved', [(64, 65), (67, 68), (75, 76), (93, 94)])
def test_unique_boxed_link_evolutions_are_available(participant, dex, evolved):
    emu, snap, candidate = participant
    candidate = replace(candidate, species=SPECIES_BY_DEX[dex])
    snap = replace(snapshot([candidate], party=snap.party), map=89)
    selected, = runtime_inventory(emu, snap)['offers']
    assert selected['trade_key'] == identity(asdict(candidate))
    assert selected['last_copy'] is True
    assert (selected['dex'], selected['arrived_dex']) == (dex, evolved)


@pytest.mark.parametrize('preference', ['locked', 'withdrawn'])
def test_unique_link_evolution_respects_preferences(participant, preference):
    emu, snap, candidate = participant
    candidate = replace(candidate, species=SPECIES_BY_DEX[64])
    emu.store.set_trade_preference(identity(asdict(candidate)), {'state': preference})
    snap = replace(snapshot([candidate], party=snap.party), map=89)
    assert runtime_inventory(emu, snap)['offers'] == []


def test_unique_link_evolution_respects_projects_and_party(participant):
    emu, snap, candidate = participant
    candidate = replace(candidate, species=SPECIES_BY_DEX[64])
    snap = replace(snapshot([candidate], party=snap.party), map=89)
    collection = {'hunt': {'species': SPECIES_BY_DEX[65], 'parent': candidate.species}}
    assert runtime_inventory(emu, snap, collection)['offers'] == []
    party_only = replace(snapshot([], party=(replace(snap.party[0], species=candidate.species),)), map=89)
    assert runtime_inventory(emu, party_only)['offers'] == []


def test_unique_mode_does_not_offer_best_of_multiple_copies(participant):
    emu, snap, candidate = participant
    weak = replace(candidate, species=SPECIES_BY_DEX[64], level=20)
    strong = replace(weak, position=1, trainer_id=303, level=50)
    snap = replace(snapshot([weak, strong], party=snap.party), map=89)
    selected, = runtime_inventory(emu, snap)['offers']
    assert selected['trade_key'] == identity(asdict(weak))
    assert selected['last_copy'] is False


@pytest.mark.parametrize('dex,evolved', [(64, 65), (67, 68), (75, 76), (93, 94)])
def test_both_unique_pre_evolutions_can_use_the_cable(setup, dex, evolved):
    for peer in setup.peers.values():
        peer.dex = dex
        peer.owned = [dex]
        peer.offer = {'last_copy': True, 'arrived_dex': evolved}
    row = setup.coordinator.propose(setup.data)
    result = setup.coordinator.execute(row['id'])
    assert result['phase'] == 'completed'
    assert setup.cable_calls == [row['id']]


@pytest.mark.parametrize('reason', ['restore', 'quality'])
def test_proposal_rejects_spending_unique_partner_without_new_dex(setup, reason):
    for peer in setup.peers.values():
        peer.dex = 64
        peer.owned = [64, 65]
        peer.offer = {'last_copy': True, 'arrived_dex': 65, 'level': 40}
    if reason == 'quality':
        original = setup.coordinator.inventory
        def with_existing(aid):
            return {**original(aid), 'party': [{'dex': 65, 'level': 5}]}
        setup.coordinator.inventory = with_existing
    with pytest.raises(ValueError, match='last copy'):
        setup.coordinator.propose(setup.data)
    assert not setup.registry.transactions()


def test_unique_version_exclusive_can_unlock_a_peer_dex(setup, monkeypatch):
    left, right = setup.data['left_id'], setup.data['right_id']
    inventories = {left: inventory({**offer('red-only', 23), 'last_copy': True}),
                   right: inventory({**offer('blue-only', 27), 'last_copy': True})}
    inventories[left]['owned'] = [23]
    inventories[right]['owned'] = [27]
    assert selection(setup, monkeypatch, inventories) is not None


def test_return_of_evolved_unique_partner_registers_original_owner_once(setup, monkeypatch):
    completed(setup, left_key='kadabra-now-alakazam')
    left, right = setup.data['left_id'], setup.data['right_id']
    inventories = {left: inventory(offer('spare', 19)),
                   right: inventory({**offer('kadabra-now-alakazam', 65), 'last_copy': True})}
    inventories[left]['owned'] = [19, 64]
    inventories[right]['owned'] = [19, 64, 65]
    assert selection(setup, monkeypatch, inventories) is not None
    inventories[left]['owned'].append(65)
    assert selection(setup, monkeypatch, inventories) is None


def test_one_sides_new_entry_does_not_spend_other_unique_for_quality(setup, monkeypatch):
    left, right = setup.data['left_id'], setup.data['right_id']
    inventories = {left: inventory({**offer('unique-left', 25), 'last_copy': True}),
                   right: inventory({**offer('unique-right', 27), 'last_copy': True})}
    inventories[left]['owned'] = [25]
    inventories[right]['owned'] = [25, 27]
    assert selection(setup, monkeypatch, inventories) is None


@pytest.mark.parametrize('dex,evolved', [(64, 65), (67, 68), (75, 76), (93, 94)])
def test_third_game_can_exchange_last_pre_evolution_for_missing_evolved_form(setup, monkeypatch, dex, evolved):
    left, right = setup.data['left_id'], setup.data['right_id']
    inventories = {left: inventory({**offer('last-pre-evolution', dex), 'arrived_dex': evolved, 'last_copy': True}),
                   right: inventory({**offer('already-evolved', evolved), 'last_copy': True})}
    inventories[left]['owned'] = [dex]
    inventories[right]['owned'] = [dex, evolved]
    assert selection(setup, monkeypatch, inventories) is not None
    inventories[left]['owned'].append(evolved)
    assert selection(setup, monkeypatch, inventories) is None


def test_proposal_allows_reciprocal_evolution_registration(setup):
    left = setup.peers[setup.data['left_id']]
    right = setup.peers[setup.data['right_id']]
    left.dex, left.owned = 64, [64]
    left.offer = {'last_copy': True, 'arrived_dex': 65}
    right.dex, right.owned = 65, [64, 65]
    right.offer = {'last_copy': True, 'arrived_dex': 65}
    row = setup.coordinator.propose(setup.data)
    assert setup.coordinator.execute(row['id'])['phase'] == 'completed'


def test_evolution_exception_cannot_spend_unique_partner_for_unrelated_new_entry(setup):
    left = setup.peers[setup.data['left_id']]
    right = setup.peers[setup.data['right_id']]
    left.dex, left.owned = 64, [64]
    left.offer = {'last_copy': True, 'arrived_dex': 65}
    right.dex, right.owned = 94, [64, 65, 94]
    right.offer = {'last_copy': True, 'arrived_dex': 94}
    with pytest.raises(ValueError, match='last copy'):
        setup.coordinator.propose(setup.data)
    assert not setup.registry.transactions()
