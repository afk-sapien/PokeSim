"""Differential checks keep the optional decoder interchangeable with Python."""
import random

import pytest

from pokecore import snapshot
from pokecore.identity import pokemon_identity


@pytest.mark.parametrize('seed', range(160))
def test_random_wram_matches_python(seed, monkeypatch):
    pytest.importorskip('pokesim_core_native')
    rng = random.Random(seed)
    memory = bytearray(rng.randbytes(65536))
    memory[0xd163] = [0, 1, 2, 6, 7, 255][seed % 6]
    moves = {index: {'pp': rng.randrange(100)} for index in range(256)}
    expected = snapshot._read_fields_python(memory, moves)
    before = bytes(memory)
    monkeypatch.setenv('POKESIM_CORE_DECODER', 'rust')
    assert snapshot.read_fields(memory, moves) == expected
    assert bytes(memory) == before


def test_zero_slots_and_output_ownership(monkeypatch):
    pytest.importorskip('pokesim_core_native')
    memory = bytearray(65536)
    memory[0xd163] = 6
    monkeypatch.setenv('POKESIM_CORE_DECODER', 'rust')
    first = snapshot.read_fields(memory)
    assert first == snapshot._read_fields_python(memory)
    first['party'][0]['species'] = 42
    first['party'].clear()
    assert len(snapshot.read_fields(memory)['party']) == 6


@pytest.mark.parametrize('length', [0, 8191, 8193])
def test_native_rejects_incomplete_or_oversized_memory(length):
    native = pytest.importorskip('pokesim_core_native')
    with pytest.raises(ValueError):
        native.decode_snapshot(bytes(length), ())


def test_native_rejects_incomplete_pp():
    native = pytest.importorskip('pokesim_core_native')
    memory = bytearray(8192)
    memory[0x1163] = 1
    with pytest.raises(ValueError):
        native.decode_snapshot(bytes(memory), ())


def test_forced_python_does_not_need_native(monkeypatch):
    monkeypatch.setenv('POKESIM_CORE_DECODER', 'python')
    assert snapshot.decoder_backend() == 'python'
    assert snapshot.read_fields(bytes(65536)) == snapshot._read_fields_python(bytes(65536))


def test_invalid_backend_name_is_not_silently_ignored(monkeypatch):
    monkeypatch.setenv('POKESIM_CORE_DECODER', 'typo')
    with pytest.raises(ValueError):
        snapshot.read_fields(bytes(65536))


def test_identity_matches_existing_serialization_and_tracks_mutation():
    import hashlib
    import json
    dvs = [1, 2, 3, 4, 5]
    for trainer in (0, 1, 65535):
        expected = hashlib.sha256(json.dumps([trainer, dvs]).encode()).hexdigest()[:24]
        assert pokemon_identity(trainer, dvs) == expected
        assert pokemon_identity(trainer, tuple(dvs)) == expected
    before = pokemon_identity(1, dvs)
    dvs[0] = 4
    assert pokemon_identity(1, dvs) != before
    assert pokemon_identity(None, dvs) is None
    assert pokemon_identity(1, ()) is None


def test_identity_preserves_distinct_numeric_json_types():
    assert pokemon_identity(1, (1, 2, 3, 4, 5)) != pokemon_identity(True, (1, 2, 3, 4, 5))
    assert pokemon_identity(1, (1, 2, 3, 4, 5)) != pokemon_identity(1, (1.0, 2, 3, 4, 5))


@pytest.mark.parametrize('native', [False, True])
def test_wild_shiny_transform_and_capture_protection(native, monkeypatch):
    if native:
        pytest.importorskip('pokesim_core_native')
        monkeypatch.setenv('POKESIM_CORE_DECODER', 'rust')
    shiny, plain = b'\x2a\xaa', b'\xff\xff'

    def read(memory):
        fields = snapshot.read_fields(memory)
        assert fields == snapshot._read_fields_python(memory)
        return fields['enemy_shiny']

    memory = bytearray(65536)
    memory[0xd057] = 1
    memory[0xcff1:0xcff3] = shiny
    assert read(memory)
    memory[0xcff1:0xcff3] = plain
    assert not read(memory)
    # Ditto copied a shiny player's DVs; the original wild DVs are ordinary.
    memory[0xd069] = 8
    memory[0xcff1:0xcff3] = shiny
    memory[0xcceb:0xcced] = plain
    assert not read(memory)
    # Ditto copied ordinary DVs; the original wild DVs are shiny.
    memory[0xcff1:0xcff3] = plain
    memory[0xcceb:0xcced] = shiny
    assert read(memory)
    # A completed capture sets TRANSFORMED-restore state but needs no protection.
    memory[0xd11c] = 132
    assert not read(memory)
    memory[0xd11c] = 0
    memory[0xcf0b] = 2
    assert not read(memory)
    memory[0xcf0b] = 0
    for battle in (0, 2):
        memory[0xd057] = battle
        assert not read(memory)
