"""Save summaries from synthetic SRAM images, so no save or game table is committed."""
import json

import pytest

from pokecore import save_summary as ss
from pokecore.cli import main
from pokecore.gen1 import (W_BADGES, W_CUR_MAP, W_CURRENT_BOX, W_DEX_OWNED, W_DEX_SEEN, W_EVENT_FLAGS,
                           W_HALL_OF_FAME_COUNT, W_MONEY, W_PLAYER_STARTER, W_PLAYTIME_H, W_RIVAL_NAME,
                           W_RIVAL_STARTER)
from pokecore.gen2.memory_map import CRYSTAL, GOLD_SILVER


def gen1_save(**fields):
    raw = bytearray(ss.SAVE_SIZE)
    for address, value in fields.get('wram', {}).items():
        raw[address - ss.GEN1_MAIN] = value
    raw[ss.GEN1_PLAYER_NAME:ss.GEN1_PLAYER_NAME + 4] = bytes([0x80, 0x81, 0x82, 0x50])
    raw[W_RIVAL_NAME - ss.GEN1_MAIN:W_RIVAL_NAME - ss.GEN1_MAIN + 3] = bytes([0x91, 0x80, 0x50])
    for at, value in fields.get('file', {}).items():
        raw[at] = value
    raw[ss.GEN1_CHECKSUM] = ~sum(raw[ss.GEN1_PLAYER_NAME:ss.GEN1_CHECKSUM]) & 0xFF
    return bytes(raw)


def gen2_save(version, **fields):
    symbols, delta, end = ss.GEN2_LAYOUTS['crystal' if version == 'crystal' else None]
    raw = bytearray(ss.SAVE_SIZE)
    for name, value in fields.items():
        name, offset = (name.split('__') + ['0'])[:2]
        raw[symbols[name][1] - delta + int(offset)] = value
    raw[ss.GEN2_CHECK_1] = ss.GEN2_CHECK_1_VALUE
    at = symbols['sChecksum'][1] - 0xA000 + 0x2000
    raw[at:at + 2] = (sum(raw[ss.GEN2_DATA:end]) & 0xFFFF).to_bytes(2, 'little')
    raw[at + 2] = ss.GEN2_CHECK_2_VALUE
    return bytes(raw)


def gen1_party(*mons):
    file = {ss.GEN1_PARTY: len(mons)}
    for index, (species, level) in enumerate(mons):
        at = ss.GEN1_PARTY + 8 + index * ss.GEN1_PARTY_STRUCT
        file[at], file[at + ss.GEN1_LEVEL] = species, level
    return file


@pytest.mark.parametrize('stage, wram, file', [
    ('new game', {}, {}),
    ('0 badges', {}, gen1_party((0xB0, 5))),
    ('1 badge', {W_BADGES: 1}, gen1_party((0xB0, 5))),
    ('8 badges', {W_BADGES: 0xFF}, gen1_party((0xB0, 50))),
    ('league entered', {W_BADGES: 0xFF, W_CUR_MAP: 0xF5}, gen1_party((0xB0, 50))),
    ('champion', {W_BADGES: 0xFF, W_CUR_MAP: 0x76, W_HALL_OF_FAME_COUNT: 1}, gen1_party((0xB0, 50))),
    ('post-game', {W_BADGES: 0xFF, W_CUR_MAP: 1, W_HALL_OF_FAME_COUNT: 1}, gen1_party((0xB0, 50))),
])
def test_gen1_stage(stage, wram, file):
    assert ss.summarize_save(gen1_save(wram=wram, file=file)).stage == stage


def test_gen1_fields():
    summary = ss.summarize_save(gen1_save(
        wram={W_BADGES: 0b101, W_DEX_OWNED: 0b11, W_DEX_SEEN: 0b111, W_HALL_OF_FAME_COUNT: 2, W_CUR_MAP: 12,
              W_MONEY: 0x12, W_MONEY + 1: 0x34, W_MONEY + 2: 0x56, W_PLAYTIME_H: 7, W_PLAYTIME_H + 2: 8,
              W_PLAYTIME_H + 3: 9},
        file=gen1_party((0xB0, 5), (0x54, 12))))
    assert (summary.generation, summary.version) == (1, None)
    assert (summary.player_name, summary.rival_name) == ('ABC', 'RA')
    assert summary.badges == ('Boulder', 'Thunder') and summary.badge_count == 2
    assert (summary.dex_owned, summary.dex_seen, summary.hall_of_fame) == (2, 3, 2)
    assert (summary.money, summary.play_time, summary.map_id) == (123456, (7, 8, 9), 12)
    assert [(mon.species, mon.level, mon.name) for mon in summary.party] == [(0xB0, 5, None), (0x54, 12, None)]
    assert len(summary.box_counts) == 12
    assert json.loads(json.dumps(summary.to_dict()))['box_total'] == 0


def test_gen1_detects_yellow_from_its_starter_bytes():
    assert ss.summarize_save(gen1_save(wram={W_PLAYER_STARTER: 0x54, W_RIVAL_STARTER: 2})).version == 'yellow'
    assert ss.summarize_save(gen1_save(wram={W_PLAYER_STARTER: 0xB0, W_RIVAL_STARTER: 0xB1})).version is None


def test_gen1_ignores_unused_boxes_until_the_first_box_change():
    noisy = {ss.GEN1_BANKS[0]: 5, ss.GEN1_ACTIVE_BOX: 3}
    assert ss.summarize_save(gen1_save(file=noisy)).box_total == 3
    raw = bytearray(gen1_save(wram={W_CURRENT_BOX: ss.GEN1_HAS_CHANGED_BOXES | 1}, file=noisy))
    for start in ss.GEN1_BANKS:
        raw[start + ss.GEN1_BANK_CHECKSUM] = ~sum(raw[start:start + ss.GEN1_BANK_CHECKSUM]) & 0xFF
    assert ss.summarize_save(bytes(raw)).box_counts[:2] == (5, 3)


def test_gen1_refuses_a_bad_box_checksum():
    raw = gen1_save(wram={W_CURRENT_BOX: ss.GEN1_HAS_CHANGED_BOXES}, file={ss.GEN1_BANKS[0]: 5})
    with pytest.raises(ss.SaveError, match='boxes'):
        ss.summarize_save(raw)


@pytest.mark.parametrize('version', ['gold', 'crystal'])
@pytest.mark.parametrize('stage, fields', [
    ('new game', {}),
    ('0 badges', {'wPartyCount': 1}),
    ('2 badges', {'wPartyCount': 1, 'wJohtoBadges': 0b11}),
    ('league entered', {'wPartyCount': 1, 'wJohtoBadges': 0xFF, 'wMapGroup': 16, 'wMapNumber': 3}),
    ('champion', {'wPartyCount': 1, 'wJohtoBadges': 0xFF, 'wHallOfFameCount': 1}),
    ('kanto entered', {'wPartyCount': 1, 'wJohtoBadges': 0xFF, 'wHallOfFameCount': 1,
                       f'wEventFlags__{ss.EVENT_FAST_SHIP_HAS_ARRIVED // 8}': 1 << ss.EVENT_FAST_SHIP_HAS_ARRIVED % 8}),
    ('kanto entered', {'wPartyCount': 1, 'wHallOfFameCount': 1, 'wKantoBadges': 1}),
    ('red beaten', {'wPartyCount': 1, 'wHallOfFameCount': ss.HOF_MASTER_COUNT}),
])
def test_gen2_stage(version, stage, fields):
    assert ss.summarize_save(gen2_save(version, **fields)).stage == stage


def test_gen2_fields():
    raw = gen2_save('crystal', wPlayerName=0x80, wPlayerName__1=0x50, wRivalName=0x91, wRivalName__1=0x50,
                    wJohtoBadges=0b1, wKantoBadges=0b10, wPokedexCaught=0b11, wPokedexSeen=0b111, wHallOfFameCount=3,
                    wMoney=1, wMoney__1=2, wMoney__2=3, wGameTimeHours=1, wGameTimeHours__1=2, wGameTimeMinutes=3,
                    wGameTimeSeconds=4, wMapGroup=24, wMapNumber=7, wPartyCount=1, wPartySpecies=ss.GEN2_EGG,
                    wPartyMons=152, **{f'wPartyMons__{ss.GEN2_LEVEL}': 5})
    summary = ss.summarize_save(raw)
    assert (summary.generation, summary.version) == (2, 'crystal')
    assert (summary.player_name, summary.rival_name) == ('A', 'R')
    assert (summary.johto_badges, summary.kanto_badges) == (('Zephyr',), ('Cascade',))
    assert (summary.dex_owned, summary.dex_seen, summary.hall_of_fame) == (2, 3, 3)
    assert (summary.money, summary.play_time, summary.map_id) == (0x010203, (258, 3, 4), 24 * 256 + 7)
    assert (summary.party[0].species, summary.party[0].level, summary.party[0].egg) == (152, 5, True)
    assert len(summary.box_counts) == 14


def test_gen2_counts_the_active_box_from_its_working_copy():
    symbols = GOLD_SILVER
    raw = bytearray(gen2_save('gold', wCurBox=1))
    bank, address = symbols['sBox']
    raw[bank * 0x2000 + address - 0xA000] = 4
    bank, address = symbols['sBox1']
    raw[bank * 0x2000 + address - 0xA000] = 2
    bank, address = symbols['sBox2']
    raw[bank * 0x2000 + address - 0xA000] = 9
    bank, address = symbols['sBox3']
    raw[bank * 0x2000 + address - 0xA000] = 0xFF
    assert ss.summarize_save(bytes(raw)).box_counts[:3] == (2, 4, 0)


@pytest.mark.parametrize('raw', [bytes(ss.SAVE_SIZE), bytes([0xFF]) * ss.SAVE_SIZE])
def test_refuses_blank_memory(raw):
    with pytest.raises(ss.SaveError, match='checksum'):
        ss.summarize_save(raw)


@pytest.mark.parametrize('build', [gen1_save, lambda: gen2_save('gold'), lambda: gen2_save('crystal')])
def test_refuses_a_flipped_byte(build):
    raw = bytearray(build())
    raw[0x2100 if build is not gen1_save else 0x2700] ^= 1
    with pytest.raises(ss.SaveError, match='checksum'):
        ss.summarize_save(bytes(raw))


def test_refuses_the_wrong_size():
    with pytest.raises(ss.SaveError, match='32768'):
        ss.summarize_save(bytes(100))


def test_crystal_layout_differs_from_gold():
    assert CRYSTAL['sChecksum'] != GOLD_SILVER['sChecksum']


def test_reads_a_path_and_prints(tmp_path, capsys):
    path = tmp_path / 'game.sav'
    path.write_bytes(gen2_save('crystal', wPartyCount=1, wJohtoBadges=1))
    assert main(['summary', str(path)]) == 0
    out = capsys.readouterr().out
    assert 'Stage: 1 badge' in out and 'Game: crystal (Generation 2)' in out and 'Johto badges: 1' in out
    assert main(['summary', '--json', str(path)]) == 0
    assert json.loads(capsys.readouterr().out)['stage'] == '1 badge'


def test_cli_reports_a_refusal(tmp_path, capsys):
    path = tmp_path / 'bad.sav'
    path.write_bytes(bytes(ss.SAVE_SIZE))
    assert main(['summary', str(path)]) == 1
    assert 'checksum' in capsys.readouterr().err
    assert main(['summary', str(tmp_path / 'missing.sav')]) == 1


def test_refuses_a_rom_from_the_other_generation(monkeypatch):
    monkeypatch.setattr(ss, '_rom_facts', lambda rom: ('red', 1, {}))
    with pytest.raises(ss.SaveError, match='Generation 1'):
        ss.summarize_save(gen2_save('crystal'), rom=b'rom')


def test_rom_names_the_version_and_species(monkeypatch):
    monkeypatch.setattr(ss, '_rom_facts', lambda rom: ('blue', 1, {0xB0: {'name': 'CHARMANDER'}}))
    summary = ss.summarize_save(gen1_save(file=gen1_party((0xB0, 5))), rom=b'rom')
    assert (summary.version, summary.party[0].name) == ('blue', 'CHARMANDER')


def test_event_flags_stay_inside_the_read_span():
    assert W_EVENT_FLAGS - ss.GEN1_MAIN + 0x140 < ss.GEN1_PARTY
