"""Storage cleanup never waits on a box slot the PC release menu cannot reach."""
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from pokesim.policies.strategic import StrategicPolicy
from pokesim.policies.team import release_target
from pokesim.ram import list_breaks, read_snapshot
from pokesim.runtime import preparation
from pokesim.shortcuts import RETRY_FRAMES
from pokesim.trade import boxes
from pokesim.trade.preferences import identity
from test_duplicates import snapshot, stored
from test_managed_trade_evolutions import SPECIES_BY_DEX, runtime_inventory
from test_preparation import participant  # noqa: F401  (fixture)
from test_trade_save import ABRA, Memory, entry, populate


def traded_nickname():
    # A received nickname whose terminator arrived as the CONT text command. The PC list
    # stops drawing at this name, so its cursor never reaches the Pokémon stored after it.
    return bytes(boxes.encode_text('WETFUND')[:7]) + bytes((0x55, 0x8B, 0x8B, 0x50))


def test_a_text_command_in_a_nickname_hides_the_rest_of_the_box():
    names = boxes.encode_text('CORNFAX') + traded_nickname() + boxes.encode_text('MILKFAX')
    assert list_breaks(names) == 1
    # Bytes after the terminator are leftovers the game never prints.
    assert list_breaks(boxes.encode_text('MOP')[:4] + bytes((0x55,) * 7)) is None
    assert list_breaks(boxes.encode_text('CORNFAX') * 3) is None


def test_release_skips_spares_stored_after_a_list_breaking_name():
    memory = populate(Memory(), active=1, contents=())
    for position, level in enumerate((50, 40, 5, 6), start=1):
        slot = entry(ABRA, level)
        if position == 2:
            slot = replace(slot, nickname=traded_nickname())
        boxes.write_slot(memory, 1, position, slot)
    s = read_snapshot(memory, 1)
    assert s.unlisted == ((0, 2), (0, 3))
    # Without the guard the weakest copies, which the menu cannot reach, would be chosen forever.
    assert release_target(replace(s, unlisted=())) in ((0, 2), (0, 3))
    assert release_target(s) == (0, 1)


def test_a_failed_release_lets_another_spare_go_first():
    policy = StrategicPolicy(7)
    s = replace(snapshot([stored(0, level=30), stored(1, level=5), stored(2, level=6)]), frame=1000)
    assert policy._release_target(s) == (0, 1)
    policy.shortcut.failures[('release', 0, 1)] = s.frame + RETRY_FRAMES
    assert policy._release_target(s) == (0, 2)
    decision = policy.pc.step(s, SimpleNamespace(cursor=None), 'pc', 'party_release', None, {}, policy.collection)
    assert decision.request == ('release', 2)
    # The failed slot is offered again once its retry time has passed.
    assert policy._release_target(replace(s, frame=s.frame + RETRY_FRAMES)) == (0, 1)


def test_a_trade_never_offers_or_prepares_a_partner_the_pc_list_cannot_reach(participant, monkeypatch):
    # Red offered Muk and Kabutops stored after WETFUND in Box 11. The list stalled on that name
    # while scrolling, so every withdrawal for the trade failed with "Menu did not respond".
    emu, snap, _ = participant
    reachable = stored(0, species=SPECIES_BY_DEX[64], trainer_id=101)
    hidden = stored(1, species=SPECIES_BY_DEX[67], trainer_id=303)
    snap = replace(snapshot([reachable, hidden], party=snap.party), map=89, x=13, y=4)
    emu.snapshot = snap
    assert [offer['position'] for offer in runtime_inventory(emu, snap)['offers']] == [1, 2]
    emu.snapshot = snap = replace(snap, unlisted=((0, 1),))
    assert [offer['trade_key'] for offer in runtime_inventory(emu, snap)['offers']] == [identity(asdict(reachable))]
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: snap)
    with pytest.raises(ValueError, match='PC list cannot reach'):
        preparation.begin(emu, identity(asdict(hidden)), 'hidden', manual=True)
    assert emu.store.get(preparation.KEY) is None
    assert preparation.begin(emu, identity(asdict(reachable)), 'reachable')['phase'] == 'travelling'


def test_a_trade_never_offers_the_spare_the_game_is_releasing(participant):
    # Blue offered the Pidgey, Squirtle and Bulbasaur it was letting go at the PC. Each release
    # landed seconds after the trade was chosen, so preparation found the Pokémon gone and every
    # trade failed as "cannot be identified uniquely".
    emu, snap, _ = participant
    copies = [stored(0, level=30, trainer_id=101), stored(1, level=5, trainer_id=202),
              stored(2, level=6, trainer_id=303)]
    snap = replace(snapshot(copies, party=snap.party), map=89, x=13, y=4)
    emu.snapshot = snap
    emu.policy = policy = StrategicPolicy(7)
    assert sorted(offer['position'] for offer in runtime_inventory(emu, snap)['offers']) == [1, 2, 3]
    policy.release_spare = release_target(snap)
    assert policy.release_spare == (0, 1)
    assert sorted(offer['position'] for offer in runtime_inventory(emu, snap)['offers']) == [1, 3]
