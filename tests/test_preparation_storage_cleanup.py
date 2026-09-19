"""Completely full storage can free exactly one safe spare through PC inputs."""
from dataclasses import asdict, replace

from pokesim.runtime import preparation
from pokesim.trade.preferences import identity
from test_duplicates import snapshot, stored
from test_preparation import participant, storage_menu, storage_party, storage_step
from test_strategy import menu


def full_storage(snap, candidate):
    copies = (replace(candidate, level=1), stored(1, trainer_id=102, level=2),
              stored(2, trainer_id=103, level=3))
    return replace(snapshot(copies, party=storage_party()), map=snap.map, x=snap.x, y=snap.y,
                   textbox=True, box_counts=(20,) * 12, boxed_pokemon=((153, 20),) * 20)


def begin_cleanup(emu, snap, candidate):
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    full = full_storage(snap, candidate)
    emu.store.set_trade_preference(identity(asdict(full.stored_details[1])), {'state': 'locked'})
    controller = emu.preparation
    assert storage_step(controller, full, storage_menu(2)) == 'a'
    return controller, full


def test_cleanup_reserves_offer_and_existing_lock_before_selecting_spare(participant):
    emu, snap, candidate = participant
    controller, full = begin_cleanup(emu, snap, candidate)
    assert controller.storage_cleanup._release_target(full) == (0, 2)
    preferences = controller.storage_cleanup.trade_preferences()
    assert preferences[controller.state['trade_key']]['state'] == 'offered'
    assert preferences[identity(asdict(full.stored_details[1]))]['state'] == 'locked'
    assert emu.store.trade_preferences().get(controller.state['trade_key']) is None


def test_release_confirmation_rechecks_exact_safe_individual(participant):
    emu, snap, candidate = participant
    controller, full = begin_cleanup(emu, snap, candidate)
    listing = menu({4: '     PARTNER', 6: '     CANCEL'}, (5, 4), index=2, top=(5, 4))
    assert storage_step(controller, full, listing) == 'a'
    assert controller.storage_cleanup.pc.pending_release[:2] == (0, 2)
    confirmation = menu({1: '  YES', 3: '  NO', 15: 'GONE FOREVER'}, (1, 1), top=(1, 1))
    assert preparation.Screen(confirmation).kind(full) == 'yes_no'
    assert storage_step(controller, full, confirmation) == 'a'
    emu.store.set_trade_preference(identity(asdict(full.stored_details[2])), {'state': 'locked'})
    assert storage_step(controller, full, confirmation) is None
    assert 'no unprotected spare duplicate' in emu.store.get(preparation.KEY)['error']


def test_one_freed_slot_closes_cleanup_before_normal_deposit(participant):
    emu, snap, candidate = participant
    controller, full = begin_cleanup(emu, snap, candidate)
    freed = replace(full, box_counts=(19,) + (20,) * 11,
                    boxed_pokemon=full.boxed_pokemon[:19])
    assert storage_step(controller, freed, storage_menu(2)) == 'b'
    assert controller.storage_cleanup is not None
    overworld = replace(freed, textbox=False)
    assert storage_step(controller, overworld, bytearray(65536)) == 'up'
    assert controller.storage_cleanup is None
    assert storage_step(controller, freed, storage_menu(1)) == 'a'
    assert controller.operation == 'deposit'


def test_only_offered_spare_and_unique_pokemon_are_never_released(participant):
    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    unique = stored(1, trainer_id=102, species=0xB0)
    full = replace(snapshot((candidate, unique), party=storage_party()),
                   map=snap.map, x=snap.x, y=snap.y, textbox=True,
                   box_counts=(20,) * 12, boxed_pokemon=((153, 20),) * 20)
    assert storage_step(emu.preparation, full, storage_menu(2)) is None
    assert 'no unprotected spare duplicate' in emu.store.get(preparation.KEY)['error']
