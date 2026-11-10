from dataclasses import FrozenInstanceError

import pytest

from pokecore.storage import decode_box, memory_bytes
from pokecore.gen1 import decode_text
from pokecore.gen1_ui import read_storage, screen_rows


def test_cache_records_are_immutable_and_new_bytes_invalidate():
    block = bytearray(33)
    block[0], block[3] = 177, 50
    names = bytes([0x80, 0x50] + [0] * 9)
    first = decode_box(bytes(block), names)
    assert first is decode_box(bytes(block), names)
    with pytest.raises(FrozenInstanceError):
        first[0].level = 100
    block[3] = 51
    assert decode_box(bytes(block), names)[0].level == 51
    assert first[0].level == 50
    for structs, nick in ((b'x', b''), (bytes(33), b''), (bytes(33 * 21), bytes(11 * 21))):
        with pytest.raises(ValueError):
            decode_box(structs, nick)


def test_storage_bulk_reads_and_results_do_not_share_mutable_lists():
    class Memory:
        def __init__(self):
            self.reads = 0
            self.mem = bytearray(65536)
            self.mem[0xDA80] = 20
            self.mem[0xDA80 + 22] = 177
        def __getitem__(self, key):
            self.reads += 1
            return self.mem[key]
    mem = Memory()
    first = read_storage(mem)
    assert mem.reads < 40
    first['boxes'][0]['pokemon'][0]['moves'][0] = 999
    assert read_storage(mem)['boxes'][0]['pokemon'][0]['moves'][0] == 0


def test_scalar_fallback_and_short_blocks():
    class Scalar:
        def __getitem__(self, key):
            if isinstance(key, slice):
                raise TypeError()
            return key % 256
    assert memory_bytes(Scalar(), None, 0, 4) == bytes(range(4))
    with pytest.raises(ValueError):
        memory_bytes(bytearray(3), None, 0, 4)


def test_cached_glyph_modes_match_previous_decoders_for_every_tile():
    raw = bytes(range(256)) + bytes(104)
    actual = ''.join(screen_rows(raw))
    expected = ''.join('>' if t == 0xED else '?' if t == 0xE6 else decode_text(bytes([t])).replace('?', ' ') or ' ' for t in raw)
    assert actual == expected
    assert ''.join(screen_rows(raw, raw_text=True)) == ''.join(decode_text(bytes([t])) or ' ' for t in raw)


@pytest.mark.parametrize('bank', [None, 1])
def test_empty_memory_block_never_accesses_native_memory(bank):
    class NativeMemory:
        def __getitem__(self, key):
            raise AssertionError('Native backend rejects empty slices')
        def snapshot_window(self, *args):
            raise AssertionError('Empty reads do not need a bank window')
    assert memory_bytes(NativeMemory(), bank, 0xDA80, 0) == b''
