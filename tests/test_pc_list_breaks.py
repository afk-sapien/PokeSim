"""Bill's PC list reaches every stored slot when Core reads the stack, and pc_list guards the rest.

Core 0.9.5 presses through all nine text commands a traded nickname can hold, in every game, once
it has the stack pointer. Without it, Gen I stops at five of them and Gen II has no table, so
pc_list keeps storage cleanup and trades away from the slots that list cannot reach.
"""
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from pokesim import pc_list
from pokesim.gen2 import menus
from pokesim.gen2.policy import Policy as Gen2Policy
from pokesim.policies.strategic import StrategicPolicy
from pokesim.policies.team import release_target
from pokesim.ram import read_snapshot
from pokesim.runtime import preparation
from pokesim.shortcuts import RETRY_FRAMES, gen1_ui
from pokesim.trade import boxes
from pokesim.trade.preferences import identity
from test_duplicates import snapshot, stored
from test_managed_trade_evolutions import SPECIES_BY_DEX, runtime_inventory
from test_preparation import participant  # noqa: F401  (fixture)
from test_trade_save import ABRA, Memory, entry, populate

SP = 0xDFF0
SAFE_WITHOUT_SP = (0x00, 0x4C, 0x57, 0x5F)


def named(code):
    return bytes(boxes.encode_text('WETFUND')[:7]) + bytes((code, 0x8B, 0x8B, 0x50))


def box_with(code):
    """Box 1 holding four Abra, the second named with ``code``."""
    memory = populate(Memory(), active=1, contents=())
    for position, level in enumerate((50, 40, 5, 6), start=1):
        slot = entry(ABRA, level)
        if position == 2:
            slot = replace(slot, nickname=named(code))
        boxes.write_slot(memory, 1, position, slot)
    return read_snapshot(memory, 1)


def release_with(s, sp):
    policy = StrategicPolicy(7)
    policy.sp = sp
    return policy._release_target(s)


def test_the_table_matches_core_0_9_5():
    assert pc_list.TEXT_COMMANDS == {0x00, 0x49, 0x4B, 0x4C, 0x51, 0x55, 0x57, 0x58, 0x5F}
    assert pc_list.GEN1_BREAKS == {0x49, 0x4B, 0x51, 0x55, 0x58}
    assert pc_list.GEN1_BREAKS | set(SAFE_WITHOUT_SP) == pc_list.TEXT_COMMANDS
    assert pc_list.GEN2_BREAKS == pc_list.TEXT_COMMANDS


@pytest.mark.parametrize('code', (0x55, 0x49))
def test_a_red_slot_behind_a_breaking_name_is_guarded_without_sp_and_pickable_with_it(code):
    s = box_with(code)
    # In Red and Blue the list stops at the name, so that slot and every one after it are out of reach.
    assert s.unlisted == ((0, 1), (0, 2), (0, 3))
    assert pc_list.guarded(s, None) == {(0, 1), (0, 2), (0, 3)} and pc_list.guarded(s, SP) == set()
    # With the stack pointer the weakest copy goes, though it sits behind the name.
    assert release_with(s, SP) == (0, 2) == release_target(s)
    # Without it no spare the list can reach is left, so nothing is released.
    assert release_with(s, None) is None


@pytest.mark.parametrize('code', SAFE_WITHOUT_SP)
def test_a_gen1_name_core_reads_without_sp_hides_nothing(code):
    s = box_with(code)
    assert s.unlisted == ()
    assert release_with(s, None) == (0, 2)


def test_yellow_without_sp_guards_the_whole_box():
    names = bytes(boxes.encode_text('CORNFAX')) + named(0x55) + bytes(boxes.encode_text('MILKFAX'))
    assert list(pc_list.gen1_unlisted(names, 3, yellow=True)) == [0, 1, 2]
    assert list(pc_list.gen1_unlisted(names, 3, yellow=False)) == [1, 2]
    # Bytes after the terminator are leftovers the game never prints.
    assert list(pc_list.gen1_unlisted(boxes.encode_text('MOP')[:4] + bytes((0x55,) * 7), 1, yellow=True)) == []


def test_the_live_red_wetfund_slot_leaves_box_11_pickable_with_sp():
    # The bytes Red held in Box 11 slot 0: nickname WETFUND ended by <CONT>, from trainer ROWAN.
    nickname = bytes.fromhex('96849385948d83558b8b50')
    trainer = bytes.fromhex('918e96808d50') + bytes((0x50,) * 5)
    assert boxes.decode_text(nickname).startswith('WETFUND') and boxes.decode_text(trainer) == 'ROWAN'
    memory = populate(Memory(), active=1, contents=((1, ABRA, 50),))
    for position, level in enumerate((40, 5, 6), start=1):
        slot = entry(ABRA, level)
        if position == 1:
            slot = replace(slot, nickname=nickname, ot_name=trainer)
        boxes.write_slot(memory, 11, position, slot)
    s = read_snapshot(memory, 1)
    assert s.unlisted == ((10, 0), (10, 1), (10, 2))
    # Red's release used to stop at WETFUND. With the stack pointer it lets go of the weakest copy behind it.
    assert release_with(s, SP) == (10, 1)
    assert release_with(s, None) is None


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


def test_a_trade_offers_a_partner_behind_a_breaking_name_only_with_sp(participant, monkeypatch):
    # Red offered Muk and Kabutops stored after WETFUND in Box 11. With the stack pointer either can
    # be prepared. Without it the list stops at the name, so the one behind it is held back.
    emu, snap, _ = participant
    first = stored(0, species=SPECIES_BY_DEX[64], trainer_id=101, nick='WETFUND')
    behind = stored(1, species=SPECIES_BY_DEX[67], trainer_id=303)
    snap = replace(snapshot([first, behind], party=snap.party), map=89, x=13, y=4, unlisted=((0, 1),))
    emu.snapshot = snap
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: snap)
    assert [offer['position'] for offer in runtime_inventory(emu, snap)['offers']] == [1]
    with pytest.raises(ValueError, match='PC list cannot reach'):
        preparation.begin(emu, identity(asdict(behind)), 'behind', manual=True)
    emu.pb.register_file = SimpleNamespace(SP=SP)
    assert [offer['position'] for offer in runtime_inventory(emu, snap)['offers']] == [1, 2]
    assert preparation.begin(emu, identity(asdict(behind)), 'behind', manual=True)['phase'] == 'travelling'


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


def test_every_gen1_game_passes_the_stack_pointer():
    # Core 0.9.5 reads Yellow's stack too, so Red, Blue and Yellow all pass it.
    assert gen1_ui(SP) == {'sp': SP}
    assert gen1_ui(None) is None


def test_gold_silver_and_crystal_pc_lists_get_the_stack_pointer(monkeypatch):
    seen = []

    class Machine:
        def step(self, memory, ui):
            seen.append(ui)
            return 'a'

    class Task(menus.CoreTask):
        def build(self, snapshot):
            return Machine()

    monkeypatch.setattr(menus, 'current_screen', lambda memory, version: 'bills_pc')
    snap = SimpleNamespace(data=SimpleNamespace(game='gold'))
    mem = SimpleNamespace(memory=bytearray(0x10000), sp=0xDF00)
    assert Task().step(snap, mem) == 'a'
    mem.sp = None
    assert Task().step(snap, mem) == 'a'
    assert seen == [{'sp': 0xDF00}, None]
    assert menus.stack_pointer(SimpleNamespace(register_file=SimpleNamespace(SP=0xDFE0))) == 0xDFE0
    assert menus.stack_pointer(SimpleNamespace()) is None


@pytest.mark.parametrize('code', (0x55, 0x00))
def test_gen2_without_sp_guards_every_pick_in_a_box_with_a_text_command_name(code):
    mon = lambda box, position, name: SimpleNamespace(box=box, position=position, nick_bytes=name)  # noqa: E731
    plain = bytes(boxes.encode_text('CORNFAX'))
    snap = SimpleNamespace(frame=0, active_box=2, stored=(mon(2, 0, plain), mon(2, 3, named(code)), mon(4, 0, plain)))
    policy = SimpleNamespace(sp=None, blocked={}, task_key=Gen2Policy.task_key, unlisted_box=Gen2Policy.unlisted_box)
    allowed = lambda task: Gen2Policy.allowed(policy, task, snap)  # noqa: E731
    withdraw = menus.Storage('WITHDRAW', 0, 1)
    assert not allowed(menus.Release(2, 0)) and not allowed(withdraw)
    assert allowed(menus.Release(4, 0)) and allowed(menus.Storage('DEPOSIT', 0, 1))
    policy.sp = 0xDF00
    assert allowed(menus.Release(2, 0)) and allowed(withdraw)
