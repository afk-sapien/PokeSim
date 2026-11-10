import pytest

from pokecore import gen1, gen1_ui, yellow
from pokecore.cartridges import by_version
from pokecore.shortcuts import screens


def yellow_memory():
    raw = bytearray(65536)
    raw[yellow.W_PLAYER_NAME:yellow.W_PLAYER_NAME + 6] = bytes([0x80, 0x81, 0x82, 0x83, 0x84, 0x50])
    raw[yellow.W_PLAYER_ID:yellow.W_PLAYER_ID + 2] = (0x1234).to_bytes(2, 'big')
    raw[yellow.W_PARTY_COUNT] = 2
    raw[yellow.W_PARTY_SPECIES:yellow.W_PARTY_SPECIES + 3] = bytes([0x24, yellow.STARTER_PIKACHU, 0xFF])
    for slot, species in enumerate((0x24, yellow.STARTER_PIKACHU)):
        base = yellow.W_PARTY_MONS + slot * 44
        raw[base] = species
        raw[base + 1:base + 3] = (20).to_bytes(2, 'big')
        raw[base + 12:base + 14] = (0x1234).to_bytes(2, 'big')
        raw[base + 33] = 5 + slot
        ot = yellow.W_PARTY_OT + slot * 11
        raw[ot:ot + 6] = raw[yellow.W_PLAYER_NAME:yellow.W_PLAYER_NAME + 6]
    return raw


def test_address_translation():
    assert yellow.address(0xCF1A) == 0xCF1A
    assert yellow.address(0xCF1B) == 0xCF1A
    assert yellow.address(0xDEE1) == 0xDEE0
    assert yellow.address(0xDEE2) == 0xDEE2
    assert yellow.address(0xFFF4) == 0xFFF9
    assert yellow.address(0xFFF8) == 0xFFF5
    assert yellow.address(0xFFF5) == 0xFFF5


def test_continue_ready_finds_the_yellow_text_wait_through_the_raw_stack():
    raw = bytearray(65536)
    raw[0x134:0x13C] = b'YELWAIT!'
    # Yellow's text wait, operands zeroed. Its link cable branch pushes around a far call.
    raw[0x3852:0x388E] = bytes.fromhex('f08bf5f08cf5afe08b3e06e08ce5fa0000a7280cd5c52100000600cd0000c1d1'
                                       '210000cd0000e1cd00003e2dcd0000f000e6032800f1e08cf1e08bc9')
    view = yellow.RedLayoutMemory(raw)
    sp = 0xDE00
    assert screens.continue_ready(view, sp) is False
    for wait in (0x3870, 0x3878, 0x387C, 0x3881):
        raw[sp + 4:sp + 6] = wait.to_bytes(2, 'little')
        assert screens.continue_ready(view, sp) is True, hex(wait)
    assert screens.continue_ready(bytearray(65536), sp) is None


def test_red_layout_view_reads_and_writes():
    raw = bytearray(range(256)) * 256
    view = yellow.RedLayoutMemory(raw)
    for red in (0xC000, 0xCF1A, 0xCF1B, 0xD158, 0xDEE1, 0xDEE2, 0xFFF4, 0xFFF7, 0xFFF9, 0xFFFF):
        assert view[red] == raw[yellow.address(red)]
    span = (0xCF10, 0xCF30)
    assert view.read_bytes(*span) == bytes(raw[yellow.address(a)] for a in range(*span))
    assert view.read_bytes(0xFFF0, 0x10000) == bytes(raw[yellow.address(a)] for a in range(0xFFF0, 0x10000))
    assert view[0xD000:0xD004] == list(raw[0xCFFF:0xD003])
    view[0xD158] = 0x99
    assert raw[0xD157] == 0x99
    assert yellow.red_layout(raw, None) is raw
    assert yellow.red_layout(raw, 'red') is raw
    assert yellow.red_layout(view, 'yellow') is view
    assert isinstance(yellow.red_layout(raw, by_version('yellow')), yellow.RedLayoutMemory)
    with pytest.raises(ValueError):
        yellow.red_layout(raw, 'gold')


def test_gen1_readers_take_version():
    raw = yellow_memory()
    party = gen1.read_party(raw, version='yellow')
    assert [mon['species'] for mon in party] == [0x24, yellow.STARTER_PIKACHU]
    assert [mon['level'] for mon in party] == [5, 6]
    assert gen1.read_party(yellow.RedLayoutMemory(raw)) == party
    assert gen1.read_trainers(raw, version='yellow')['trainer_id'] == 0x1234
    raw[yellow.address(gen1.W_NUM_BAG_ITEMS)] = 1
    raw[yellow.address(gen1.W_BAG_ITEMS):yellow.address(gen1.W_BAG_ITEMS) + 3] = bytes([4, 7, 0xFF])
    assert gen1.read_bag(raw, version='yellow') == ((4, 7),)
    raw[yellow.address(gen1.W_BADGES)] = 0b11
    assert gen1.read_progress(raw, version='yellow')['badges'] == gen1.read_progress(
        yellow.RedLayoutMemory(raw))['badges']
    assert isinstance(gen1_ui.read_storage(raw, version='yellow'), dict)


def test_starters():
    raw = yellow_memory()
    raw[0xD714], raw[0xD716] = 2, yellow.STARTER_PIKACHU
    assert gen1.read_starters(raw, version='yellow') == {
        'player': yellow.STARTER_PIKACHU, 'rival': 2, 'rival_evolution': 'flareon', 'player_id': 0x1234}
    red = bytearray(65536)
    red[gen1.W_RIVAL_STARTER], red[gen1.W_PLAYER_STARTER] = 0xB0, 0x99
    assert gen1.read_starters(red)['rival_evolution'] is None
    assert gen1.read_starters(red)['rival'] == 0xB0


def test_pikachu_state():
    raw = yellow_memory()
    raw[yellow.W_PIKACHU_HAPPINESS] = 210
    raw[yellow.W_PIKACHU_MOOD] = 128
    raw[yellow.W_PIKACHU_SPAWN_STATE_FLAGS] = 0b1010_0000
    state = yellow.read_pikachu(raw)
    assert state['happiness'] == 210 and state['mood'] == 128
    assert state['following'] and state['starter_spawn'] and not state['surfing']
    assert state['starter_slot'] == 1
    assert yellow.read_pikachu(yellow.RedLayoutMemory(raw), layout='red') == state
    assert yellow.happiness_band(210) == 2
    with pytest.raises(ValueError):
        yellow.happiness_band(256)


def test_starter_pikachu_identity():
    raw = yellow_memory()
    assert yellow.starter_pikachu_slot(raw) == 1
    traded = bytearray(raw)
    traded[yellow.W_PARTY_MONS + 44 + 12] = 0
    assert yellow.starter_pikachu_slot(traded) is None
    fainted = bytearray(raw)
    fainted[yellow.W_PARTY_MONS + 44 + 1:yellow.W_PARTY_MONS + 44 + 3] = b'\0\0'
    assert yellow.starter_pikachu_slot(fainted) is None
    assert yellow.starter_pikachu_slot(fainted, alive=False) == 1
    assert not yellow.is_yellow(b'not a rom')


def test_yellow_link_build_is_additive():
    from pokecore import gen1_link_metadata as link
    yellow_build = link.build(yellow.YELLOW_SHA1)
    red = link.BUILDS['ea9bcae617fdf159b045185467ae58b2e4a48b9a']
    assert yellow_build['version'] == 'Yellow'
    assert yellow_build['symbols']['wPartyMons'] == red['symbols']['wPartyMons']
    assert yellow_build['symbols']['SavePartyAndDexData'] == (28, 0x7B56)
    assert link.build('0' * 40) is None
    rom = bytearray(1 << 20)
    assert set(link.verify_signatures(rom, yellow.YELLOW_SHA1)) == set(yellow_build['signatures'])
    for name, signature in yellow_build['signatures'].items():
        bank, address = yellow_build['symbols'][name]
        offset = address if bank == 0 else bank * 0x4000 + address - 0x4000
        rom[offset:offset + 8] = bytes.fromhex(signature)
    assert link.verify_signatures(rom, yellow.YELLOW_SHA1) == []


def test_yellow_emulator_reads_red_addresses(monkeypatch):
    import io
    import sys
    from types import SimpleNamespace

    class Backend:
        def __init__(self, rom, **options):
            self.memory = bytearray(65536)
            self.frame_count = 0

        def tick(self, frames=1, render=True, sound=False):
            self.frame_count += frames
            self.memory[0xD157] = self.frame_count
            return True

        def set_emulation_speed(self, speed):
            pass

        def stop(self, save=True):
            pass

    monkeypatch.setitem(sys.modules, 'pyboy_rs', SimpleNamespace(PyBoy=Backend))
    emulator = yellow.YellowEmulator(io.BytesIO(bytes(32768)), sound_emulated=False)
    emulator.raw_memory[0xD162] = 3
    assert emulator.memory[gen1.W_PARTY_COUNT] == 3
    assert emulator.tick_read(5, gen1.W_PLAYER_NAME, gen1.W_PLAYER_NAME + 1) == bytes([5])
    assert gen1.read_party(emulator.memory) == gen1.read_party(emulator.raw_memory, version='yellow')
