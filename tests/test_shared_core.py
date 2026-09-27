"""Compatibility at the boundary between shared decoding and application state."""
from pokisim_core import gen1
from pokisim_core.rom import KNOWN_ROM_SHA1

from pokesim import config, ram


def test_legacy_decoder_imports_share_the_core_implementation():
    assert ram.decode_text is gen1.decode_text
    assert ram.bcd is gen1.bcd
    assert ram.flag_bits is gen1.flag_bits
    assert ram.individual_data is gen1.individual_data
    assert config.KNOWN_ROM_SHA1 is KNOWN_ROM_SHA1


def test_shared_party_fields_keep_application_types_names_and_pp():
    memory = bytearray(65536)
    memory[ram.W_PARTY_COUNT] = 2
    base = ram.W_PARTY_MONS
    memory[base] = 0x99
    memory[base + 1:base + 3] = (17).to_bytes(2, 'big')
    memory[base + 8:base + 12] = bytes((33, 45, 0, 0))
    memory[base + 29:base + 33] = bytes((0xC4, 0x89, 0, 0))
    memory[base + 33] = 5
    memory[base + 34:base + 36] = (20).to_bytes(2, 'big')
    memory[ram.W_PARTY_NICKS:ram.W_PARTY_NICKS + 4] = bytes((0x81, 0x94, 0x81, 0x50))

    snapshot = ram.read_snapshot(memory, 123)

    assert snapshot.frame == 123
    assert isinstance(snapshot, ram.Snapshot)
    assert isinstance(snapshot.party, tuple)
    lead, joining = snapshot.party
    assert isinstance(lead, ram.PartyMon)
    assert (lead.species, lead.name, lead.nick) == (0x99, 'Bulbasaur', 'BUB')
    assert (lead.hp, lead.max_hp, lead.level) == (17, 20, 5)
    assert lead.pp == (4, 9, 0, 0)
    assert lead.max_pp == (56, 54, 0, 0)
    assert joining.pending and joining.name == 'Joining the team'
    assert not snapshot.all_fainted


def test_shared_bag_decode_keeps_snapshot_filtering_and_capacity():
    memory = bytearray(65536)
    memory[ram.W_NUM_BAG_ITEMS] = 255
    memory[ram.W_BAG_ITEMS:ram.W_BAG_ITEMS + 8] = bytes((4, 9, 0, 7, 0xFF, 1, 1, 2))
    memory[ram.W_BAG_ITEMS + 40:ram.W_BAG_ITEMS + 42] = bytes((3, 99))

    snapshot = ram.read_snapshot(memory, 0)

    assert snapshot.items == ((4, 9), (1, 2))


def test_application_dex_sanity_check_remains_above_core_decoding():
    memory = bytearray(65536)
    memory[ram.W_DEX_OWNED] = 3
    memory[ram.W_DEX_SEEN] = 2

    snapshot = ram.read_snapshot(memory, 0)

    assert snapshot.owned == frozenset({2})
    assert snapshot.seen == frozenset({2})
