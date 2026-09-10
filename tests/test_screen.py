from pokesim.ram import W_TILEMAP
from pokesim.screen import Screen


def encode(text: str) -> bytes:
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(0x80 + ord(ch) - ord("A"))
        elif "a" <= ch <= "z":
            out.append(0xA0 + ord(ch) - ord("a"))
        elif ch == " ":
            out.append(0x7F)
        elif ch == "/":
            out.append(0xF3)
        else:
            out.append(0x7F)
    return bytes(out)


def fake_mem(lines: dict[int, str]) -> bytearray:
    mem = bytearray(0x10000)
    for r in range(18):
        mem[W_TILEMAP + r * 20:W_TILEMAP + (r + 1) * 20] = bytes([0x7F]) * 20
    for r, text in lines.items():
        enc = encode(text.ljust(20)[:20])
        mem[W_TILEMAP + r * 20:W_TILEMAP + r * 20 + 20] = enc
    return mem


def test_battle_menu():
    scr = Screen(fake_mem({14: "         FIGHT PKMN ", 16: "         ITEM  RUN  "}))
    assert scr.battle_menu and not scr.list_menu and not scr.yes_no


def test_list_menu_and_yes_no():
    assert Screen(fake_mem({4: "     CANCEL         "})).list_menu
    scr = Screen(fake_mem({12: "  YES", 13: "  NO"}))
    assert scr.yes_no
    assert Screen(fake_mem({12: "  BUY", 13: "  SELL"})).shop
    assert Screen(fake_mem({12: "  WITHDRAW"})).pc
    assert Screen(fake_mem({5: "  A B C D E F G H I "})).naming
    assert not Screen(fake_mem({})).battle_menu
