"""A traded nickname holding <CONT> no longer hides the Pokémon stored after it in the PC list.

Core 0.9.4 presses A through the wait that <CONT> (0x55) starts while a Bill's PC list draws, so
storage cleanup and trades may pick every stored slot again.
"""
from dataclasses import asdict, replace
from types import SimpleNamespace

from pokesim.gen2 import menus
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


def test_release_reaches_spares_stored_after_a_cont_name():
    memory = populate(Memory(), active=1, contents=())
    nickname = bytes(boxes.encode_text('WETFUND')[:7]) + bytes((0x55, 0x8B, 0x8B, 0x50))
    for position, level in enumerate((50, 40, 5, 6), start=1):
        slot = entry(ABRA, level)
        if position == 2:
            slot = replace(slot, nickname=nickname)
        boxes.write_slot(memory, 1, position, slot)
    s = read_snapshot(memory, 1)
    assert not hasattr(s, 'unlisted')
    # The weakest copy sits after the name, and the release now takes it.
    assert release_target(s) == (0, 2)


def test_the_live_red_wetfund_slot_leaves_the_rest_of_box_11_pickable():
    # The bytes Red held in Box 11 slot 0: nickname WETFUND ended by <CONT>, from trainer ROWAN.
    nickname = bytes.fromhex('96849385948d83558b8b50')
    assert nickname[7:] == bytes((0x55, 0x8B, 0x8B, 0x50))
    trainer = bytes.fromhex('918e96808d50') + bytes((0x50,) * 5)
    assert boxes.decode_text(nickname).startswith('WETFUND') and boxes.decode_text(trainer) == 'ROWAN'
    memory = populate(Memory(), active=1, contents=((1, ABRA, 50),))
    for position, level in enumerate((40, 5, 6), start=1):
        slot = entry(ABRA, level)
        if position == 1:
            slot = replace(slot, nickname=nickname, ot_name=trainer)
        boxes.write_slot(memory, 11, position, slot)
    s = read_snapshot(memory, 1)
    assert [(mon.box, mon.position, mon.level) for mon in s.stored_details if mon.box == 10] == \
        [(10, 0, 40), (10, 1, 5), (10, 2, 6)]
    # Red's release used to stop at WETFUND. It now lets go of the weakest copy behind it.
    assert release_target(s) == (10, 1)


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


def test_a_trade_offers_and_prepares_a_partner_stored_after_a_cont_name(participant, monkeypatch):
    # Red offered Muk and Kabutops stored after WETFUND in Box 11. Before Core 0.9.4 the list stalled on
    # that name, so they were held back. Both are offered now, and either can be prepared.
    emu, snap, _ = participant
    first = stored(0, species=SPECIES_BY_DEX[64], trainer_id=101, nick='WETFUND')
    behind = stored(1, species=SPECIES_BY_DEX[67], trainer_id=303)
    snap = replace(snapshot([first, behind], party=snap.party), map=89, x=13, y=4)
    emu.snapshot = snap
    assert [offer['position'] for offer in runtime_inventory(emu, snap)['offers']] == [1, 2]
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: snap)
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


def test_red_and_blue_pc_lists_get_the_stack_pointer_and_yellow_reads_the_text():
    # Core reads <CONT>'s wait from the stack when ui carries sp. Yellow's stack sits where the Red
    # layout view shifts it, so Yellow passes no ui and Core waits for the dialogue text to settle.
    assert gen1_ui(0xDFF0, False) == {'sp': 0xDFF0}
    assert gen1_ui(0xDFF0, True) is None and gen1_ui(None, False) is None


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
