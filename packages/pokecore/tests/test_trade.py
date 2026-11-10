
import pytest

from pokecore import gen1_link_metadata, gen2_link_metadata, timecapsule as tc, trade
from pokecore.gen1_cable import CableError

# Synthetic tables in the documented shapes. They are not cartridge data.
GEN1_SPECIES = {0x99: {'dex': 1, 'stats': [45, 49, 49, 45, 65]},
                0x36: {'dex': 81, 'stats': [25, 35, 70, 45, 95]}}
GEN2_SPECIES = {1: {'types': [22, 3], 'stats': [45, 49, 49, 45, 65, 65]},
                81: {'types': [23, 9], 'stats': [25, 35, 70, 45, 95, 55]}}


def gen1_row(species=0x99, catch_rate=0x2D, level=12):
    raw = bytearray(44)
    raw[0], raw[1:3], raw[3], raw[4] = species, (30).to_bytes(2, 'big'), level, 0
    raw[5:7] = bytes([22, 3])
    raw[7] = catch_rate
    raw[8:12] = bytes([33, 45, 0, 0])
    raw[12:14] = (4321).to_bytes(2, 'big')
    raw[27:29] = bytes([0xAB, 0xCD])
    raw[33] = level
    return {'struct': bytes(raw), 'nickname': b'\x80\x50' + bytes(9), 'trainer': b'\x81\x50' + bytes(9)}


def gen2_row(dex=1, item=0, moves=(33, 45, 0, 0), level=12):
    raw = bytearray(48)
    raw[0], raw[1], raw[2:6] = dex, item, bytes(moves)
    raw[6:8] = (4321).to_bytes(2, 'big')
    raw[21:23] = bytes([0xAB, 0xCD])
    raw[27], raw[31] = 120, level
    return {'struct': bytes(raw), 'nickname': b'\x80\x50' + bytes(9), 'trainer': b'\x81\x50' + bytes(9)}


def test_time_capsule_rules():
    assert tc.held_item_from_catch_rate(0x19) == tc.LEFTOVERS
    assert tc.held_item_from_catch_rate(0xFF) == tc.BERRY
    assert tc.held_item_from_catch_rate(0x2E) == 0x2E
    assert tc.is_mail(tc.FLOWER_MAIL) and tc.is_mail(0xBD) and not tc.is_mail(0xBE)
    assert tc.compatible(151, [165])
    assert not tc.compatible(152, [1])
    assert not tc.compatible(25, [166])
    assert not tc.compatible(25, [1], tc.FLOWER_MAIL)
    assert not tc.compatible(25, [1], egg=True)
    assert tc.compatible_struct(gen2_row()['struct'])
    assert not tc.compatible_struct(gen1_row()['struct'])


def test_time_capsule_round_trip_keeps_identity():
    sent = gen1_row()
    gen2 = tc.to_gen2(sent, GEN1_SPECIES, GEN2_SPECIES)['struct']
    assert len(gen2) == 48 and gen2[0] == 1 and gen2[1] == tc.BITTER_BERRY
    assert gen2[27] == tc.TRADE_FRIENDSHIP and gen2[31] == 12
    assert tc.individual(gen2)[0] == (5, 0xA, 0xB, 0xC, 0xD)
    back = tc.to_gen1({**sent, 'struct': gen2}, GEN1_SPECIES, GEN2_SPECIES)['struct']
    assert len(back) == 44 and back[0] == 0x99 and back[5:7] == bytes([22, 3])
    assert back[8:30] == sent['struct'][8:30] and back[33] == 12
    assert tc.convert(sent, 1, GEN1_SPECIES, GEN2_SPECIES) is sent
    magnemite = tc.to_gen1(gen2_row(81), GEN1_SPECIES, GEN2_SPECIES)['struct']
    assert magnemite[5:7] == bytes([23, 23])
    with pytest.raises(CableError):
        tc.to_gen1(gen2_row(moves=(200, 0, 0, 0)), GEN1_SPECIES, GEN2_SPECIES)
    with pytest.raises(CableError):
        tc.to_gen2(gen1_row(species=0x01), GEN1_SPECIES, GEN2_SPECIES)


def test_gen1_received_checks():
    sent = gen1_row(species=38)
    evolved = {**sent, 'struct': bytes([149]) + sent['struct'][1:]}
    report = trade.verify_gen1_received(sent, evolved)
    assert report['received_species'] == 149 and not report['default_name_evolved']
    assert report['received_key'] == trade.gen1_individual_key(sent)
    with pytest.raises(CableError, match='Unexpected received species'):
        trade.verify_gen1_received(sent, sent)
    changed = bytearray(evolved['struct'])
    changed[27] ^= 1
    with pytest.raises(CableError, match='identity or training'):
        trade.verify_gen1_received(sent, {**evolved, 'struct': bytes(changed)})
    named = {**sent, 'nickname': b'\x8a\x80\x83\x80\x81\x91\x80\x50' + bytes(3)}
    renamed = {**evolved, 'nickname': b'\x80\x8b\x80\x8a\x80\x99\x80\x8c\x50' + bytes(2)}
    assert trade.verify_gen1_received(named, renamed, names={38: 'Kadabra', 149: 'Alakazam'})['default_name_evolved']


def test_gen1_party_and_walking():
    symbols = gen1_link_metadata.BUILDS[gen1_link_metadata.YELLOW_SHA1]['symbols']
    memory = bytearray(65536)
    memory[symbols['wPartyCount'][1]] = 1
    row = gen1_row()
    memory[symbols['wPartyMons'][1]:symbols['wPartyMons'][1] + 44] = row['struct']
    assert trade.gen1_party(memory, symbols)[0]['struct'] == row['struct']
    poisoned = bytearray(row['struct'])
    poisoned[4] = 8
    before = [{**row, 'struct': bytes(poisoned)}]
    poisoned[1:3] = (29).to_bytes(2, 'big')
    assert trade.walking_party_preserved(before, [{**row, 'struct': bytes(poisoned)}])
    poisoned[1:3] = (27).to_bytes(2, 'big')
    assert not trade.walking_party_preserved(before, [{**row, 'struct': bytes(poisoned)}])
    memory[symbols['wPartyCount'][1]] = 0
    with pytest.raises(CableError):
        trade.gen1_party(memory, symbols)


def test_gen2_trade_checks():
    assert trade.gen2_evolved_species(bytes([64, 0])) == 65
    assert trade.gen2_evolved_species(bytes([64, tc.EVERSTONE])) == 64
    assert trade.gen2_evolved_species(bytes([95, tc.METAL_COAT])) == 208
    assert trade.gen2_evolved_species(bytes([95, 0])) == 95
    sent = gen2_row(dex=95, item=tc.METAL_COAT)
    received = bytearray(sent['struct'])
    received[0], received[1], received[27] = 208, 0, tc.TRADE_FRIENDSHIP
    report = trade.verify_gen2_received(sent, {**sent, 'struct': bytes(received)})
    assert report['received_species'] == 208 and report['held_item'] == 0
    received[27] = 120
    with pytest.raises(CableError, match='friendship'):
        trade.verify_gen2_received(sent, {**sent, 'struct': bytes(received)})
    party = [gen2_row(), gen2_row(dex=4), gen2_row(dex=7)]
    kept = trade.gen2_untraded_party(party, 1, friendship_step=True, eggs=(False, False, True))
    assert [row['struct'][27] for row in kept] == [121, 120]


def test_link_builds_are_complete():
    for builds in (gen1_link_metadata.BUILDS, gen2_link_metadata.BUILDS):
        for build in builds.values():
            assert set(build['signatures']) <= set(build['symbols'])
    assert {build['version'] for build in gen2_link_metadata.BUILDS.values()} == {'gold', 'silver', 'crystal'}
    assert gen1_link_metadata.rom_offset(10, 0x4055) == 10 * 0x4000 + 0x55
    assert not tc.communication_ok(bytes(1 << 21), 'gold')
