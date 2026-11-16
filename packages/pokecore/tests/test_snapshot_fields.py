"""Snapshot fields are fresh each read, and identities and shiny checks read the right bytes."""
from pokecore import snapshot
from pokecore.identity import pokemon_identity


def test_zero_slots_and_output_ownership():
    memory = bytearray(65536)
    memory[0xd163] = 6
    before = bytes(memory)
    first = snapshot.read_fields(memory)
    assert bytes(memory) == before
    first['party'][0]['species'] = 42
    first['party'].clear()
    assert len(snapshot.read_fields(memory)['party']) == 6


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


def test_wild_shiny_transform_and_capture_protection():
    shiny, plain = b'\x2a\xaa', b'\xff\xff'

    def read(memory):
        fields = snapshot.read_fields(memory)
        assert fields['enemy_shiny'] == snapshot.wild_shiny(memory)
        return fields['enemy_shiny']

    memory = bytearray(65536)
    memory[0xd057] = 1
    memory[0xcff1:0xcff3] = shiny
    assert read(memory)
    memory[0xcff1:0xcff3] = plain
    assert not read(memory)
    # Ditto copied a shiny player's DVs. The original wild DVs are ordinary.
    memory[0xd069] = 8
    memory[0xcff1:0xcff3] = shiny
    memory[0xcceb:0xcced] = plain
    assert not read(memory)
    # Ditto copied ordinary DVs. The original wild DVs are shiny.
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
