"""``input_wait``: a text prompt or a menu's input loop, read from live stack words in both generations."""
from pokecore import yellow
from pokecore.shortcuts import input_wait

SP = 0xDF00
GEN1_HELD = 0xFFB4
GEN2_HELD = 0xFFAA


def gen1_memory(header):
    """Raw memory holding Yellow's text wait at 0x3852 and HandleMenuInput_'s poll loop at 0x3ACF.

    The loop's calls to AnimatePartyMon, JoypadLowSensitivity and HandleDownArrowBlinkTiming return to
    0x3AE8, 0x3AEC and 0x3AF8, as in Red and Blue. JoypadLowSensitivity at 0x3831 reads hJoyHeld.
    """
    raw = bytearray(0x10000)
    raw[0x134:0x13C] = header
    raw[0x3831:0x383F] = bytes.fromhex('cd9a01f0b7a7f0b32802f0b4e0b5')
    raw[0x3852:0x388E] = bytes.fromhex('f08bf5f08cf5afe08b3e06e08ce5fa0000a7280cd5c52100000600cd0000c1d1'
                                       '210000cd0000e1cd00003e2dcd0000f000e6032800f1e08cf1e08bc9')
    raw[0x3ACF:0x3AF8] = bytes.fromhex('afea0000cd0000cd0000e5fa0000a72805060021000ccd0000'
                                       'e1cd0000f000a72000e5210000cd0000')
    return raw


def gen2_memory(header):
    """Raw memory holding _ContText at 0x1200 and the two home menu wrappers at 0x1A66 and 0x1A70.

    _ContText's PromptButton call returns to 0x120D, a <PARA> handler's to 0x1183, and each wrapper's
    far call into the bank 9 loop to 0x1A6C and 0x1A76, as in Gold and Silver. JoyTextDelay at 0xA08
    reads hJoyDown.
    """
    raw = bytearray(0x10000)
    raw[0x134:0x13C] = header
    raw[0xA08:0xA16] = bytes.fromhex('cd3509f0aca7f0a92802f0aae0ab')
    raw[0x1200:0x1212] = bytes.fromhex('b72003cd5009cd7009d5cd600ad1fa0000b7')
    raw[0x1180:0x1183] = bytes.fromhex('cd600a')
    raw[0x1A66:0x1A70] = bytes.fromhex('2100403e09cfcd0020c9')
    raw[0x1A70:0x1A7A] = bytes.fromhex('2120403e09cfcd0020c9')
    return raw


def waits_at(raw, words):
    found = []
    for word in words:
        raw[SP + 6:SP + 8] = word.to_bytes(2, 'little')
        found.append(input_wait(raw, SP))
    return found


def test_gen1_waits_at_its_text_prompt_and_in_the_menu_poll_loop():
    raw = gen1_memory(b'GEN1WAIT')
    assert not input_wait(raw, SP)
    assert waits_at(raw, (0x3870, 0x3878, 0x387C, 0x3881)) == [True] * 4
    assert waits_at(raw, (0x3AE8, 0x3AEC, 0x3AF8)) == [True] * 3
    # The calls before the loop, and any other word, are not a wait.
    assert waits_at(raw, (0x3AD6, 0x3AD9, 0x3AF7, 0x1A6C)) == [False] * 4


def test_gen2_waits_at_a_prompt_and_on_the_return_of_either_menu_wrapper():
    raw = gen2_memory(b'GEN2WAIT')
    assert not input_wait(raw, SP)
    assert waits_at(raw, (0x120D, 0x1183, 0x1A6C, 0x1A76)) == [True] * 4
    # The returns after GetMenuJoypad, the other _ContText calls and Gen I's loop are not a wait.
    assert waits_at(raw, (0x1A6F, 0x1A79, 0x1206, 0x1209, 0x3AEC)) == [False] * 5


def test_a_wait_starts_only_once_the_game_has_read_every_button_up():
    # The game counts a press only against the buttons its last read saw, so a button it still
    # saw held would make the next press of it look held, not new.
    for raw, held, word in ((gen1_memory(b'GEN1HELD'), GEN1_HELD, 0x3AEC),
                            (gen2_memory(b'GEN2HELD'), GEN2_HELD, 0x1A6C)):
        raw[SP:SP + 2] = word.to_bytes(2, 'little')
        raw[held] = 0x01
        assert not input_wait(raw, SP)
        raw[held] = 0
        assert input_wait(raw, SP)


def test_a_cartridge_whose_joypad_read_is_not_found_never_waits():
    raw = gen2_memory(b'NOJOYPAD')
    raw[0xA08:0xA16] = bytes(14)
    raw[SP:SP + 2] = (0x1A6C).to_bytes(2, 'little')
    assert not input_wait(raw, SP)


def test_only_live_stack_words_in_wram_are_read():
    raw = gen2_memory(b'GEN2LIVE')
    raw[SP + 6:SP + 8] = (0x1A6C).to_bytes(2, 'little')
    assert input_wait(raw, SP)
    assert not input_wait(raw, SP + 8)
    assert not input_wait(raw, 0xFFFE)


def test_a_cartridge_with_no_known_wait_never_waits():
    raw = bytearray(0x10000)
    raw[0x134:0x13C] = b'NOWAITS!'
    raw[SP:SP + 2] = (0x1A6C).to_bytes(2, 'little')
    assert not input_wait(raw, SP)


def test_yellow_red_layout_memory_is_read_through_to_the_raw_stack():
    raw = gen1_memory(b'YELLOWMN')
    raw[SP + 6:SP + 8] = (0x3AEC).to_bytes(2, 'little')
    assert input_wait(yellow.RedLayoutMemory(raw), SP)
