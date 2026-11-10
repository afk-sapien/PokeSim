"""Gen II hook finders and trusted setup writes without a ROM. Cartridge cases are in test_gen2_hooks_roms.py."""
import random
from types import SimpleNamespace

import pytest

from pokecore import gen2
from pokecore.gen2 import hooks, resets
from pokecore.gen2.ram import decode_mon, experience_at

FOUGHT, SHOWN, GS = 'EVENT_FOUGHT_LUGIA', 'EVENT_WHIRL_ISLAND_LUGIA_CHAMBER_LUGIA', 'EVENT_GOT_GS_BALL'
CHIKORITA = {'name': 'Chikorita', 'growth': 'MEDIUM_SLOW', 'stats': [45, 49, 65, 45, 49, 65],
             'learnset': [[1, 33], [1, 45], [8, 75]]}


class Banked:
    """A flat banked image. Every bank shares one 64 KiB array, as in PokeSim's returns tests."""

    def __init__(self):
        self.raw = bytearray(65536)
        self.writes = []

    def __getitem__(self, key):
        key = key[1] if isinstance(key, tuple) else key
        return self.raw[key]

    def __setitem__(self, key, value):
        self.writes.append(key)
        self.raw[key[1] if isinstance(key, tuple) else key] = value


def tables(game='crystal'):
    data = gen2.GameTables({'game': game, 'species': {152: CHIKORITA}, 'moves': {33: {'pp': 35}, 45: {'pp': 40}},
                            'events': {FOUGHT: 792, SHOWN: 1853, GS: 832}})
    return data


def event(memory, data, name):
    _, base = data.symbols['wEventFlags']
    index = data.events[name]
    return bool(memory.raw[base + index // 8] & 1 << index % 8)


# Write-level cases from PokeSim's walking returns: flags and bytes the returns flip.

def test_write_flag_sets_and_clears_one_bit_and_reports_a_change():
    memory, data = Banked(), tables()
    _, base = data.symbols['wEventFlags']
    memory.raw[base + 792 // 8] = 0xFF ^ 1 << 792 % 8
    assert resets.write_flag(memory, data, FOUGHT, True) and event(memory, data, FOUGHT)
    assert memory.raw[base + 792 // 8] == 0xFF
    assert not resets.write_flag(memory, data, FOUGHT, True)
    assert resets.write_flag(memory, data, FOUGHT, False) and not event(memory, data, FOUGHT)
    assert memory.raw[base + 792 // 8] == 0xFF ^ 1 << 792 % 8
    assert len(memory.writes) == 2


def test_write_byte_writes_only_a_change_at_its_offset():
    memory, data = Banked(), tables()
    _, base = data.symbols['wRoamMon1']
    assert resets.write_byte(memory, data, 'wRoamMon1', 0xFF, 2) and memory.raw[base + 2] == 0xFF
    assert not resets.write_byte(memory, data, 'wRoamMon1', 0xFF, 2)
    _, scene = data.symbols['wTinTower1FSceneID']
    memory.raw[scene] = 1
    assert resets.write_byte(memory, data, 'wTinTower1FSceneID', 0) and memory.raw[scene] == 0
    assert len(memory.writes) == 2


def test_write_puts_raw_bytes_in_order_and_high_ram_unbanked():
    memory = Banked()
    data = SimpleNamespace(symbols={'wRoamMon1': (1, 0xD000), 'hThing': (0, 0xFF90)})
    resets.write(memory, data, 'wRoamMon1', bytes((243, 40, 0xFF, 0xFF, 0)))
    assert memory.raw[0xD000:0xD005] == bytes((243, 40, 0xFF, 0xFF, 0))
    assert memory.writes[0] == (1, 0xD000)
    resets.write(memory, data, 'hThing', b'\x07', 1)
    assert memory.raw[0xFF91] == 7 and memory.writes[-1] == 0xFF91


def test_reset_event_applies_a_group_and_returns_what_changed():
    memory, data = Banked(), tables()
    resets.write_flag(memory, data, FOUGHT, True)
    assert resets.reset_event(memory, data, [(FOUGHT, False), (SHOWN, False), (GS, True)]) == (FOUGHT, GS)
    assert not event(memory, data, FOUGHT) and not event(memory, data, SHOWN) and event(memory, data, GS)
    assert resets.reset_event(memory, data, [(FOUGHT, False)]) == ()


@pytest.mark.parametrize('flags,match', [
    ([(FOUGHT, True), ('EVENT_UNKNOWN', True)], 'known event'),
    ([(FOUGHT, True), (FOUGHT, False)], 'Conflicting'),
    ([(FOUGHT, 1)], 'known event'),
    ([], 'at least one'),
])
def test_reset_event_refuses_before_any_write(flags, match):
    memory, data = Banked(), tables()
    with pytest.raises(ValueError, match=match):
        resets.reset_event(memory, data, flags)
    assert memory.writes == []


def test_reset_event_restores_written_bytes_when_a_write_does_not_persist():
    class Sticky(Banked):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if len(self.writes) == 2:
                self.raw[key[1]] ^= 0xFF
    memory, data = Sticky(), tables()
    with pytest.raises(RuntimeError, match='did not persist'):
        resets.reset_event(memory, data, [(FOUGHT, True), (SHOWN, True)])
    # Both attempted bytes are restored, the failed one included.
    assert not event(memory, data, FOUGHT) and not event(memory, data, SHOWN) and len(memory.writes) == 4


def test_box_gift_builds_a_level_5_box_struct_in_the_next_slot():
    memory, data = Banked(), tables()
    _, box = data.symbols['sBox']
    memory.raw[box] = 2
    resets.box_gift(memory, data, 152, 'seed', 0, 2)
    rng = random.Random('seed')
    trainer, dvs = rng.randrange(65536), (rng.randrange(256), rng.randrange(256))
    raw = memory.raw[box + 22 + 64:box + 22 + 96]
    assert raw[0] == 152 and raw[2:6] == bytes((33, 45, 0, 0)) and raw[21:23] == bytes(dvs)
    assert int.from_bytes(raw[6:8], 'big') == trainer and int.from_bytes(raw[8:11], 'big') == experience_at(5, 'MEDIUM_SLOW')
    assert raw[23:27] == bytes((35, 40, 0, 0)) and raw[27] == 70 and raw[31] == 5
    mon = decode_mon(raw, memory.raw[box + 882 + 22:box + 882 + 33], data, box=0, position=2)
    assert (mon.species, mon.level, mon.nick, mon.moves[:2]) == (152, 5, 'CHIKORITA', (33, 45))
    assert data.text(memory.raw[box + 662 + 22:box + 662 + 33]) == 'POKESIM'
    assert memory.raw[box] == 3 and memory.raw[box + 3:box + 5] == bytes((152, 0xFF))
    for symbol in ('wPokedexCaught', 'wPokedexSeen'):
        assert memory.raw[data.symbols[symbol][1] + 151 // 8] == 1 << 151 % 8


def test_box_gift_draws_a_nickname_from_the_pool_after_the_dvs():
    memory, data = Banked(), tables()
    resets.box_gift(memory, data, 152, 7, 0, 0, nicknames=('LEAFY', 'BUD'), ot='ELM')
    rng = random.Random(7)
    rng.randrange(65536), rng.randrange(256), rng.randrange(256)
    _, box = data.symbols['sBox']
    assert data.text(memory.raw[box + 882:box + 893]) == rng.choice(('LEAFY', 'BUD'))
    assert data.text(memory.raw[box + 662:box + 673]) == 'ELM'


def test_box_gift_writes_another_box_in_its_own_bank_and_refuses_a_changed_slot():
    memory, data = Banked(), tables()
    _, other = data.symbols['sBox3']
    resets.box_gift(memory, data, 152, 1, 2, 0)
    assert memory.raw[other] == 1 and memory.raw[other + 22] == 152
    assert (data.symbols['sBox3'][0], other) in memory.writes
    count = len(memory.writes)
    for position in (0, 20):
        with pytest.raises(ValueError, match='destination changed'):
            resets.box_gift(memory, data, 152, 1, 2, position)
    assert len(memory.writes) == count


def test_set_gs_ball_is_crystal_only():
    memory = Banked()
    resets.set_gs_ball(memory, tables())
    assert memory.raw[tables().symbols['sGSBallFlag'][1]] == 0x0B
    with pytest.raises(ValueError, match='Only Crystal'):
        resets.set_gs_ball(memory, tables('gold'))


# Hook finders on a synthetic image laid out as each finder expects.

def word(value):
    return bytes((value & 0xFF, value >> 8))


def put(memory, address, raw):
    memory.raw[address:address + len(raw)] = raw


def hooked(game='crystal'):
    memory, data = Banked(), gen2.GameTables({'game': game})
    label = lambda name: hooks.label(data, name)[1]  # noqa: E731
    start = label('BattleStartMessage')
    put(memory, start, b'\xfa' + word(label('wBattleMode')) + b'\x3d\x28\x10')
    put(memory, start + 0x16, b'\xcd' + word(label('BattleCheckEnemyShininess')) + b'\x30')
    contest = label('BugContest_SetCaughtContestMon')
    put(memory, contest, b'\xfa' + word(label('wContestMon')) + b'\xa7\x28\x04')
    put(memory, contest + 10, b'\xcd')
    put(memory, label('HatchEggs'), b'\x11' + word(label('wPartySpecies')) + b'\x21'
        + word(label('wPartyMon1Happiness')) + b'\xaf\xea' + word(label('wCurPartyMon')))
    put(memory, label('CountStep'), bytes.fromhex(hooks.STEP_SIGNATURES[game]))
    put(memory, label('SelectQuantityToBuy'), b'\x3e\x04\x21\x00\x40\xcf\x7a')
    put(memory, label('BuySell_DisplaySubtotal'), b'\xe5\x21' + word(label('hMoneyTemp'))
        + bytes((0xF0, label('hProduct') + 1 & 0xFF)))
    put(memory, label('BuyMenuLoop') + 40, b'\xfa' + word(label('wMartItemID')) + b'\x5f\x16\x00')
    for bank, address, signature in hooks.HOOKS[game]:
        put(memory, address, bytes.fromhex(signature))
    return memory, data


@pytest.mark.parametrize('game', gen2.VERSIONS)
def test_every_finder_returns_its_verified_address(game):
    memory, data = hooked(game)
    labels = hooks.LABELS[game]
    assert hooks.encounter_hook(memory, data) == (15, labels['BattleStartMessage'][1] + 0x16)
    assert hooks.contest_hook(memory, data) == (3, labels['BugContest_SetCaughtContestMon'][1] + 10)
    assert hooks.hatch_hook(memory, data) == labels['HatchEggs']
    assert hooks.step_hook(memory, data) == labels['CountStep']
    assert hooks.capture_hooks(memory, data) == tuple((bank, address) for bank, address, _ in hooks.HOOKS[game])
    bank, address = labels['SelectQuantityToBuy']
    assert hooks.mart_hooks(memory, data) == {
        'opened': labels['BuyMenu'], 'priced': (bank, address + 6), 'subtotal': labels['BuySell_DisplaySubtotal'],
        'bought': (5, labels['BuyMenuLoop'][1] + 40)}


@pytest.mark.parametrize('finder,name', [
    (hooks.encounter_hook, 'BattleStartMessage'), (hooks.contest_hook, 'BugContest_SetCaughtContestMon'),
    (hooks.hatch_hook, 'HatchEggs'), (hooks.step_hook, 'CountStep'), (hooks.mart_hooks, 'SelectQuantityToBuy'),
    (hooks.mart_hooks, 'BuySell_DisplaySubtotal'),
])
def test_a_changed_instruction_is_a_signature_error(finder, name):
    memory, data = hooked()
    memory.raw[hooks.LABELS['crystal'][name][1]] ^= 0xFF
    with pytest.raises(ValueError, match='signature does not match'):
        finder(memory, data)


def test_second_halves_and_the_purchase_count_are_verified_too():
    memory, data = hooked()
    memory.raw[hooks.LABELS['crystal']['BattleStartMessage'][1] + 0x16 + 3] = 0x38
    with pytest.raises(ValueError, match='shiny check'):
        hooks.encounter_hook(memory, data)
    memory, data = hooked()
    loop = hooks.LABELS['crystal']['BuyMenuLoop'][1]
    memory.raw[loop + 100:loop + 106] = memory.raw[loop + 40:loop + 46]
    with pytest.raises(ValueError, match='purchase'):
        hooks.mart_hooks(memory, data)
    memory, data = hooked()
    memory.raw[hooks.HOOKS['crystal'][1][1]] ^= 0xFF
    with pytest.raises(ValueError, match='capture completion'):
        hooks.capture_hooks(memory, data)


def test_symbols_win_over_the_label_table_and_marts_need_their_labels():
    memory, data = hooked()
    count = hooks.LABELS['crystal']['CountStep']
    moved = SimpleNamespace(game='crystal', symbols={**data.symbols, 'CountStep': (count[0], count[1] + 1)})
    with pytest.raises(ValueError):
        hooks.step_hook(memory, moved)
    assert hooks.mart_hooks(memory, SimpleNamespace(game='other', symbols={})) == {}
    partial = SimpleNamespace(game='other', symbols={name: hooks.LABELS['crystal'][name] for name in (
        'BuyMenu', 'SelectQuantityToBuy')})
    assert set(hooks.mart_hooks(memory, partial)) == {'opened', 'priced'}


def test_bcd_packs_six_digits():
    assert hooks.bcd(0) == [0, 0, 0] and hooks.bcd(2100) == [0x00, 0x21, 0x00] and hooks.bcd(999999) == [0x99] * 3


def test_names_are_on_the_package():
    for module, names in ((hooks, ('bcd', 'capture_hooks', 'contest_hook', 'encounter_hook', 'hatch_hook',
                                   'mart_hooks', 'step_hook')),
                          (resets, ('box_gift', 'reset_event', 'set_gs_ball', 'write_byte', 'write_flag'))):
        for name in names:
            assert getattr(gen2, name) is getattr(module, name)
    assert gen2.hooks is hooks and gen2.resets is resets
