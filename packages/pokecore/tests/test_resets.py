import pytest

from pokecore.gen1 import W_CUR_MAP, W_IS_IN_BATTLE, W_TILEMAP
from pokecore.resets import Flag, update_flags, reset_encounter, reset_events


def memory():
    mem = bytearray(65536)
    mem[0xFF40], mem[0xFF47] = 128, 228
    mem[0xD800], mem[0xD801] = 255, 255
    return mem


def test_paired_encounter_reset_preserves_other_flags_and_is_idempotent():
    mem = memory()
    args = dict(event=Flag(0xD800, 1), visibility=Flag(0xD801, 2), room=42)
    receipt = reset_encounter(mem, **args)
    assert [(c.address, c.before, c.after) for c in receipt] == [(0xD800, 255, 253), (0xD801, 255, 251)]
    assert reset_encounter(mem, **args) == ()


@pytest.mark.parametrize('address,value', [(W_CUR_MAP,42),(W_IS_IN_BATTLE,1),(W_TILEMAP + 240,0x79),
                                          (W_TILEMAP + 10,0x79),(W_TILEMAP,0xED),(0xFF40,0),(0xFF47,255)])
def test_unsafe_context_never_writes(address, value):
    mem = memory()
    mem[address] = value
    before = bytes(mem)
    with pytest.raises(ValueError):
        reset_events(mem, [Flag(0xD800, 1)], rooms=[42])
    assert bytes(mem) == before


def test_batch_merges_same_byte_and_preflights_conflicts():
    mem = memory()
    changes = [(Flag(0xD800, 0), False), (Flag(0xD800, 1), False)]
    assert len(update_flags(mem, changes)) == 1
    assert mem[0xD800] == 252
    before = bytes(mem)
    with pytest.raises(ValueError):
        update_flags(mem, changes + [(Flag(0xD800, 0), True)])
    assert bytes(mem) == before


def test_write_failure_rolls_back_earlier_bytes():
    class Memory(dict):
        failed = False
        def __setitem__(self, key, value):
            if key == 0xD801 and not self.failed:
                self.failed = True
                raise OSError('injected failure')
            super().__setitem__(key, value)
    mem = Memory({0xD800: 255, 0xD801: 255})
    with pytest.raises(OSError):
        update_flags(mem, [(Flag(0xD800, 0), False), (Flag(0xD801, 0), False)])
    assert mem == {0xD800: 255, 0xD801: 255}


def test_invalid_flags_and_missing_preflight_read_never_write():
    for base, bit in ((0xBFFF, 0), (0xDFFF, 8), (0xD800, -1), (0xD800, True)):
        with pytest.raises(ValueError):
            Flag(base, bit)
    mem = {0xD800: 255}
    with pytest.raises(KeyError):
        update_flags(mem, [(Flag(0xD800, 0), False), (Flag(0xD801, 0), False)])
    assert mem == {0xD800: 255}
