"""The Gen II per-step memory snapshot and the decoded region cache."""
import io
import random
from collections import defaultdict

import pytest

from pokesim.gen2 import ram, snapshot
from pokesim.gen2.core import boot
from pokesim.gen2.data import GameData
from pokesim.gen2.ram import Memory, read_snapshot

# ld hl, $C000 / loop: inc (hl) / jr loop. Work RAM byte $C000 changes every frame.
PROGRAM = bytes((0x21, 0x00, 0xC0, 0x34, 0x18, 0xFD))


def cartridge():
    data = bytearray(32 * 16384)
    data[0x100:0x103] = bytes((0xC3, 0x50, 0x01))
    data[0x150:0x150 + len(PROGRAM)] = PROGRAM
    data[0x143] = 0x80
    data[0x147] = 0x13
    data[0x148] = 4
    data[0x149] = 3
    data[0x14D] = (-sum(data[0x134:0x14D]) - 25) & 255
    return bytes(data)


@pytest.fixture
def machine():
    pb = boot(io.BytesIO(cartridge()), ram=io.BytesIO(random.Random(3).randbytes(32768)), sound=False)
    pb.tick(120)  # past the boot ROM, into the program loop
    rng = random.Random(9)
    for bank in range(8):
        for address in rng.sample(range(0xC000, 0xE000), 48):
            pb.memory[bank, address] = rng.randrange(256)
    yield pb
    pb.stop(save=False)


def live(pb, bank, address, size):
    """Byte-at-a-time banked reads, which never use a slice or the snapshot."""
    return bytes(pb.memory[bank, value] for value in range(address, address + size))


RANGES = [(0, 0xC000, 16), (0, 0xCFF8, 8), (0, 0xCFF8, 16), (1, 0xD000, 4096), (3, 0xD800, 32), (5, 0xC010, 4),
          (7, 0xDFFF, 1), (7, 0xDFF0, 32), (0, 0xA000, 8192), (2, 0xA123, 1102), (3, 0xBFFF, 1), (3, 0xBFF0, 32),
          (1, 0x8000, 16), (0, 0x9FF8, 16), (8, 0xD000, 4), (4, 0xA000, 4), (-1, 0xC000, 2)]


def test_snapshot_reads_equal_live_banked_reads(machine):
    mem = Memory(machine.memory, None)
    for bank, address, size in RANGES:
        try:
            expected = bytes(machine.memory[bank, address:address + size])
        except ValueError:
            with pytest.raises(ValueError):
                mem.raw(bank, address, size)
            continue
        assert mem.raw(bank, address, size) == expected == live(machine, bank, address, size), (bank, hex(address))


def test_snapshot_is_reused_until_the_machine_changes(machine):
    memory = machine.memory
    first = memory.snapshot_window(1, 0xD000, 16)
    block = memory._banks[1][(snapshot.WRAM, 1)]
    assert memory.snapshot_window(1, 0xD000, 16) == first
    assert memory._banks[1][(snapshot.WRAM, 1)] is block
    generation = machine._generation
    memory.snapshot_window(2, 0xA000, 16)
    assert machine._generation == generation


def test_ticks_invalidate_the_snapshot(machine):
    memory = machine.memory
    before = memory.snapshot_window(0, 0xC000, 1)
    machine.tick()
    after = memory.snapshot_window(0, 0xC000, 1)
    assert after == live(machine, 0, 0xC000, 1) != before


def test_writes_and_loads_invalidate_the_snapshot(machine):
    memory = machine.memory
    state = machine.save()
    original = memory.snapshot_window(3, 0xD100, 4)
    memory[3, 0xD100] = original[0] ^ 0xFF
    assert memory.snapshot_window(3, 0xD100, 4) == live(machine, 3, 0xD100, 4) != original
    sram = memory.snapshot_window(2, 0xA010, 1)
    memory[2, 0xA010] = sram[0] ^ 0x55
    assert memory.snapshot_window(2, 0xA010, 1) == bytes((sram[0] ^ 0x55,))
    machine.load(state)
    assert memory.snapshot_window(3, 0xD100, 4) == original
    assert memory.snapshot_window(2, 0xA010, 1) == sram
    checkpoint = machine.checkpoint()
    memory[3, 0xD100] = 7
    assert memory.snapshot_window(3, 0xD100, 1) == b'\x07'
    machine.restore_checkpoint(checkpoint)
    assert memory.snapshot_window(3, 0xD100, 4) == original


def test_hooks_during_a_tick_read_live_memory(machine):
    memory = machine.memory
    seen = []
    memory.snapshot_window(0, 0xC000, 1)

    def hook(context):
        seen.append((memory.snapshot_window(0, 0xC000, 1), Memory(memory, None).raw(0, 0xC000, 1),
                     live(machine, 0, 0xC000, 1)))

    machine.hook_register(0, 0x0153, hook, None)
    machine.tick()
    machine.hook_deregister(0, 0x0153)
    assert seen and all(window is None and value == current for window, value, current in seen)
    assert len({value for _, value, _ in seen}) > 1


def test_closed_machines_do_not_serve_a_snapshot():
    pb = boot(io.BytesIO(cartridge()), sound=False)
    pb.tick()
    pb.memory.snapshot_window(0, 0xC000, 1)
    pb.stop(save=False)
    assert pb.memory.snapshot_window(0, 0xC000, 1) is None


# A synthetic Gen II layout: every symbol read_snapshot reads, placed in fake banked memory.
SYMBOLS = {'wPartyCount': 1, 'wPartySpecies': 7, 'wPartyMons': 288, 'wPartyMonNicknames': 66, 'wCurBox': 1,
           'wNumItems': 41, 'wNumBalls': 25, 'wNumKeyItems': 27, 'wTMsHMs': 57, 'wObjectStructs': 520,
           'wMapGroup': 1, 'wMapNumber': 1, 'wEventFlags': 256, 'wMapObjects': 256, 'wPokedexSeen': 32,
           'wPokedexCaught': 32, 'wDayCareMan': 1, 'wDayCareLady': 1, 'wBreedMon1': 32, 'wBreedMon1Nickname': 11,
           'wBreedMon2': 32, 'wBreedMon2Nickname': 11, 'wRoamMon1': 7, 'wRoamMon2': 7, 'wRoamMon3': 7,
           'wBattleMode': 1, 'wTilemap': 360, 'wXCoord': 1, 'wYCoord': 1, 'wPlayerName': 11, 'wRivalName': 11,
           'wJohtoBadges': 1, 'wKantoBadges': 1, 'wMoney': 3, 'wCoins': 2, 'wEnemyMonSpecies': 1,
           'wEnemyMonLevel': 1, 'wEnemyMonHP': 2, 'wEnemyMonMaxHP': 2, 'wTrainerClass': 1, 'wBattleType': 1,
           'wGameTimeHours': 2, 'wGameTimeMinutes': 1, 'wGameTimeSeconds': 1, 'wHallOfFameCount': 1,
           'wStepCount': 1, 'wHappinessStepCount': 1}


def synthetic_data():
    symbols, address = {}, 0xD000
    for name, size in SYMBOLS.items():
        symbols[name] = (1, address)
        address += size
    assert address <= 0xE000
    symbols['sBox'] = (1, 0xA000)
    for box in range(14):
        symbols[f'sBox{box + 1}'] = (2 + box // 7, 0xA000 + box % 7 * 1102)
    species = {str(i): {'name': f'Species {i}', 'stats': [40 + i % 60] * 6, 'types': [i % 17],
                        'gender_ratio': i % 256, 'growth': 'MEDIUM_FAST'} for i in range(1, 252)}
    moves = {str(i): {'name': f'Move {i}', 'pp': 5 + i % 35, 'type': i % 17} for i in range(1, 252)}
    charmap = {str(i): chr(0x41 + i % 26) for i in range(0x80, 0xFA)}
    return GameData({'game': 'gold', 'species': species, 'moves': moves, 'maps': {}, 'charmap': charmap,
                     'item_attributes': {}, 'items': {}, 'types': {f'T{i}': i for i in range(17)}, 'events': {},
                     'map_ids': {}, 'symbols': symbols, 'collisions': {}, 'permissions': {}})


class BankedMemory:
    def __init__(self):
        self.banks = defaultdict(lambda: bytearray(65536))

    def __getitem__(self, key):
        bank, address = key if isinstance(key, tuple) else (0, key)
        return self.banks[bank][address]

    def __setitem__(self, key, value):
        bank, address = key if isinstance(key, tuple) else (0, key)
        self.banks[bank][address] = value


def fill(memory, data, rng):
    for name, (bank, address) in data.symbols.items():
        size = 1102 if name.startswith('sBox') else SYMBOLS[name]
        memory.banks[bank][address:address + size] = rng.randbytes(size)
    memory.banks[1][data.symbols['wPartyCount'][1]] = rng.randrange(7)
    memory.banks[1][data.symbols['wCurBox'][1]] = rng.randrange(14)
    for name, (bank, address) in data.symbols.items():
        if name.startswith('sBox'):
            memory.banks[bank][address] = rng.randrange(21)
    for name in ('wPartyMons',):
        bank, address = data.symbols[name]
        for slot in range(6):
            memory.banks[bank][address + slot * 48] = rng.randrange(1, 252)
            memory.banks[bank][address + slot * 48 + 31] = rng.randrange(1, 101)


def test_cached_regions_equal_a_fresh_decode():
    data, rng, memory = synthetic_data(), random.Random(21), BankedMemory()
    ram.clear_region_cache()
    fill(memory, data, rng)
    for step in range(40):
        cached = read_snapshot(memory, data, step)
        assert cached == read_snapshot(memory, data, step, cache=False)
        assert cached.to_dict() == read_snapshot(memory, data, step, cache=False).to_dict()
        assert repr(cached) == repr(read_snapshot(memory, data, step, cache=False))
        bank, address = data.symbols[rng.choice(list(data.symbols))]
        for _ in range(rng.randrange(1, 4)):
            memory.banks[bank][address + rng.randrange(64)] = rng.randrange(256)
        if step % 10 == 9:
            fill(memory, data, rng)


def test_unchanged_regions_reuse_their_decoded_objects():
    data, memory = synthetic_data(), BankedMemory()
    ram.clear_region_cache()
    fill(memory, data, random.Random(4))
    first, second = read_snapshot(memory, data), read_snapshot(memory, data)
    assert first.party and first.stored
    assert all(a is b for a, b in zip(first.party + first.stored, second.party + second.stored))
    assert first.tiles is second.tiles and first.seen is second.seen
    bank, address = data.symbols['sBox5']
    memory.banks[bank][address + 22 + 31] ^= 1
    third = read_snapshot(memory, data)
    assert third == read_snapshot(memory, data, cache=False)
    assert [mon for mon in third.stored if mon.box != 4] == [mon for mon in first.stored if mon.box != 4]
    assert all(a is b for a, b in zip(first.party, third.party))


def test_region_cache_is_keyed_on_the_game_data():
    data, other, memory = synthetic_data(), synthetic_data(), BankedMemory()
    ram.clear_region_cache()
    fill(memory, data, random.Random(8))
    first = read_snapshot(memory, data)
    second = read_snapshot(memory, other)
    assert all(mon.data is other for mon in second.party + second.stored)
    assert second == read_snapshot(memory, other, cache=False)
    assert first.party and first.party[0] is not second.party[0]
