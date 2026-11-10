from pokecore.gen1_ui import read_battler, read_screen, read_sprites, read_storage


def test_battler_reads_active_hp_and_pp_without_writes():
    memory = bytearray(65536)
    memory[0xD014] = 177
    memory[0xD015:0xD017] = bytes([0, 8])
    memory[0xD02D] = 0xC5
    before = bytes(memory)
    assert read_battler(memory)["hp"] == 8
    assert read_battler(memory)["pp"][0] == 5
    assert bytes(memory) == before


def test_screen_and_hidden_sprite_are_raw_facts():
    memory = bytearray(65536)
    memory[0xC3A0 + 240] = 0x79
    memory[0xC3A0 + 261] = 0xED
    memory[0xC112] = 255
    assert read_screen(memory)["textbox"]
    assert read_screen(memory)["cursor"] == (1, 13)
    assert read_sprites(memory)[1]["image"] == 255


def test_storage_does_not_guess_unavailable_banks():
    memory = bytearray(65536)
    memory[0xD5A0] = 128
    memory[0xDA80] = 1
    memory[0xDA80 + 22] = 177
    before = bytes(memory)
    boxes = read_storage(memory)["boxes"]
    assert boxes[0]["pokemon"][0]["species"] == 177
    assert not boxes[1]["available"]
    assert bytes(memory) == before
