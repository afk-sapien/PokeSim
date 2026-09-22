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


def test_yes_no_ignores_pokemon_names_behind_confirmation():
    from test_events import snap
    from test_strategy import menu

    for cursor_row in (8, 10):
        memory = menu({8: '     MR MIME    ?YES?',
                       10: '     HITMONLEE  ?NO ?'},
                      (15, cursor_row), top=(15, 8))
        screen = Screen(memory)
        assert screen.yes_no
        assert screen.kind(snap(textbox=True)) == 'yes_no'


def test_yes_no_requires_complete_labels_in_the_selected_column():
    from test_strategy import menu

    memory = menu({4: '     YESMAN', 6: '     NOBODY', 8: '     CANCEL'},
                  (4, 4), top=(4, 4))
    assert not Screen(memory).yes_no
    memory = menu({4: '     CANCEL', 8: '               YES', 10: '               NO'},
                  (4, 4), top=(4, 4))
    assert not Screen(memory).yes_no


def test_tile_table_matches_decode_text_for_every_tile():
    """rows() reads a precomputed table instead of calling decode_text per tile."""
    from pokesim.ram import decode_text
    from pokesim.screen import _TILE_CHARS

    assert len(_TILE_CHARS) == 256
    for tile in range(256):
        assert _TILE_CHARS[tile] == (decode_text(bytes([tile])) or " "), hex(tile)


def test_rows_decodes_every_tile_value_the_old_way():
    """A screen covering all 256 tile ids decodes as the per-tile implementation did."""
    from pokesim.ram import decode_text
    from pokesim.screen import rows

    mem = bytearray(0x10000)
    for i in range(360):
        mem[W_TILEMAP + i] = i % 256
    expected = ["".join(decode_text(bytes([mem[W_TILEMAP + r * 20 + c]])) or " " for c in range(20))
                for r in range(18)]
    assert rows(mem) == expected
