"""Read-only English Red/Blue/Yellow UI, sprite, battler and owned storage primitives.

Addresses follow pret/pokered a1a22aaf84d1675bcdbaeb194592379d586d838e.
These are raw facts, not an agent observation policy. Consumers must filter them.
The tilemap, menu, and sprite addresses sit below 0xCF1B and are the same in
Yellow, where sprite slot 15 is the following Pikachu. Readers of shifted
fields take ``version`` like the ``gen1`` readers.
"""
from .yellow import red_layout
from .storage import decode_box, memory_bytes
from .gen1 import W_TILEMAP, decode_text, W_CURRENT_BOX, W_BOX_COUNT, BOX_DATA_SIZE


_RAW_GLYPHS = tuple(decode_text(bytes([tile])) or " " for tile in range(256))
_VISIBLE_GLYPHS = tuple(
    ">" if tile == 0xED else "?" if tile == 0xE6 else _RAW_GLYPHS[tile].replace("?", " ")
    for tile in range(256))


def screen_rows(raw, *, raw_text=False):
    """Decode exactly one tilemap, using cached immutable glyph tables."""
    if len(raw) != 360:
        raise ValueError("A screen tilemap must contain 360 bytes")
    glyphs = _RAW_GLYPHS if raw_text else _VISIBLE_GLYPHS
    return ["".join(glyphs[tile] for tile in raw[y * 20:(y + 1) * 20]) for y in range(18)]


def read_screen(memory, *, raw_text=False):
    raw = bytes(memory[W_TILEMAP:W_TILEMAP + 360])
    rows = screen_rows(raw, raw_text=raw_text)
    cursors = [(i % 20, i // 20) for i, tile in enumerate(raw) if tile == 0xED]
    active = (memory[0xCC25], memory[0xCC24] + 2 * memory[0xCC26])
    cursor = active if active in cursors else next(iter(cursors), None)
    return {"rows": rows, "cursor": cursor, "menu_index": memory[0xCC26],
            "scroll": memory[0xCC36], "textbox": raw[240] == 0x79,
            "pause": raw[10] == 0x79, "tiles": list(raw)}


def read_sprites(memory):
    sprites = []
    for slot in range(16):
        one, two = 0xC100 + 16 * slot, 0xC200 + 16 * slot
        sprites.append({"slot": slot, "picture": memory[one], "movement": memory[one + 1],
                        "image": memory[one + 2], "screen_y": memory[one + 4],
                        "screen_x": memory[one + 6], "facing": memory[one + 9],
                        "walk_counter": memory[two], "x": memory[two + 5] - 4,
                        "y": memory[two + 4] - 4})
    return sprites


def read_battler(memory, base=0xD014, *, version=None):
    memory = red_layout(memory, version)
    block = bytes(memory[base:base + 29])
    word = lambda offset: int.from_bytes(block[offset:offset + 2], "big")
    return {"species": block[0], "hp": word(1), "max_hp": word(15),
            "status": block[4], "types": list(block[5:7]), "moves": list(block[8:12]),
            "level": block[14], "pp": [value & 63 for value in block[25:29]]}


def read_storage(memory, *, version=None):
    """Read all initialized boxes. Inactive boxes require banked memory support.

    Unavailable bank reads are explicitly marked. Never switch banks or write RAM.
    Yellow keeps cartridge RAM boxes at the same addresses.
    """
    memory = red_layout(memory, version)
    current = memory[W_CURRENT_BOX]
    active = current & 0x7F
    if active >= 12:
        return {"active_box": None, "boxes": [], "available": False}
    boxes = []
    for box in range(12):
        base = W_BOX_COUNT if box == active else 0xA000 + (box % 6) * BOX_DATA_SIZE
        get = (lambda address: memory[address]) if box == active else (lambda address: memory[2 + box // 6, address])
        try:
            count = min(get(base), 20) if box == active or current & 0x80 else 0
            bank = None if box == active else 2 + box // 6
            structs = memory_bytes(memory, bank, base + 22, count * 33)
            names = memory_bytes(memory, bank, base + 902, count * 11)
            mons = [{"slot": mon.position + 1, "species": mon.species, "level": mon.level,
                     "hp": mon.hp, "status": mon.status, "types": list(mon.types),
                     "moves": list(mon.moves), "pp": list(mon.pp), "nick": mon.nick}
                    for mon in decode_box(structs, names)]
            boxes.append({"box": box + 1, "available": True, "pokemon": mons})
        except (TypeError, IndexError, KeyError, ValueError):
            boxes.append({"box": box + 1, "available": False, "pokemon": []})
    return {"active_box": active + 1, "boxes": boxes, "available": True}
