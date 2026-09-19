"""Reading and writing one stored Pokémon inside a Generation I storage box.

Box layout (pret/pokered `sBox` / `box_struct`, the revision game_data pins). Every offset
below was re-derived from the disassembly and then confirmed byte for byte against a real
240-Pokémon save state — see tests/test_trade_save.py:

    +0      count                  0-20, how many slots are in use
    +1      species list           21 bytes: `count` species then a 0xFF terminator
    +22     20 x 33-byte mon       box_struct, below
    +682    20 x 11-byte OT name   0x50-terminated, the trainer who caught it
    +902    20 x 11-byte nickname  0x50-terminated
    = 1122 bytes (ram.BOX_DATA_SIZE)

The last two agree with ram.read_stored_pokemon, which already reads species at
`base + 22 + i*33`, level at `base + 25 + i*33` and the nickname at `base + 902 + i*11`.

box_struct, 33 bytes:

    +0  species          +12 original trainer id (2)   +23 speed EV (2)
    +1  current HP (2)   +14 experience (3)            +25 special EV (2)
    +3  level            +17 HP EV (2)                 +27 DVs (2)
    +4  status           +19 attack EV (2)             +29 PP (4)
    +5  type 1 / type 2  +21 defense EV (2)
    +7  catch rate

Not one field is a computed stat, which is what makes a hand-made trade tractable: the party
struct is this same 33 bytes followed by level and max HP/attack/defense/speed/special
(ram.PARTY_STRUCT == 44 == 33 + 11, and ram.read_snapshot reads party level at +0x21 and the
stats at +0x22..+0x2B), so the game rebuilds every stat from level, DVs and EVs when a
Pokémon is withdrawn. Changing a boxed Pokémon's species — a trade evolution — therefore
needs no stat arithmetic at all.

Where a box lives depends on whether it is open. The active box is the WRAM working copy at
ram.W_BOX_COUNT; the other eleven sit in cartridge RAM bank 2 (boxes 1-6) and bank 3
(boxes 7-12) at 0xA000 + n * 1122, which is exactly how ram.read_box_counts reaches them.

Box and position numbers in this module's public functions are 1-based, matching the
`box` field the web API already publishes (`Snapshot.to_dict` emits `box + 1`).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from ..ram import (BOX_CAPACITY, BOX_COUNT, BOX_DATA_SIZE, SPECIES_NAMES,
                   W_BOX_COUNT, W_CURRENT_BOX, decode_text)

BOX_STRUCT = 33
NAME_LENGTH = 11
BOXES_PER_BANK = 6

OFF_COUNT = 0
OFF_SPECIES_LIST = 1
OFF_MONS = 22
OFF_OT_NAMES = OFF_MONS + BOX_CAPACITY * BOX_STRUCT             # 682
OFF_NICKNAMES = OFF_OT_NAMES + BOX_CAPACITY * NAME_LENGTH       # 902

SRAM_BOXES = 0xA000
SRAM_ALL_BOXES_CHECKSUM = SRAM_BOXES + BOXES_PER_BANK * BOX_DATA_SIZE   # 0xBA4C
SRAM_BOX_CHECKSUMS = SRAM_ALL_BOXES_CHECKSUM + 1                        # 0xBA4D..0xBA52

LIST_TERMINATOR = 0xFF
END_OF_TEXT = 0x50

# box_struct field offsets
SPECIES = 0
LEVEL = 3
TYPE1 = 5
TYPE2 = 6
CATCH_RATE = 7

# Gen I text for the punctuation species names and nicknames actually use.
_ENCODE = {" ": 0x7F, "'": 0xE0, "-": 0xE3, "?": 0xE6, "!": 0xE7, ".": 0xE8,
           "♂": 0xEF, ",": 0xF4, "♀": 0xF5, "é": 0xBA}


def encode_text(text: str, length: int = NAME_LENGTH) -> bytes:
    """Gen I text, 0x50-terminated and padded to `length`. The inverse of ram.decode_text."""
    out = bytearray()
    for ch in text[:length - 1]:
        if "A" <= ch <= "Z":
            out.append(0x80 + ord(ch) - ord("A"))
        elif "a" <= ch <= "z":
            out.append(0xA0 + ord(ch) - ord("a"))
        elif "0" <= ch <= "9":
            out.append(0xF6 + ord(ch) - ord("0"))
        else:
            out.append(_ENCODE.get(ch, 0xE6))   # an unmappable glyph becomes '?', keeping the length
    out.append(END_OF_TEXT)
    return bytes(out).ljust(length, bytes([END_OF_TEXT]))


class BoxView:
    """Byte access to one of the twelve boxes, wherever the game happens to be keeping it."""

    def __init__(self, mem, box: int):
        if not 1 <= box <= BOX_COUNT:
            raise ValueError(f"Box {box} is out of range")
        self.mem, self.box = mem, box
        index = box - 1
        self.active = (mem[W_CURRENT_BOX] & 0x7F) == index
        self.bank = 2 + index // BOXES_PER_BANK
        self.sram = SRAM_BOXES + (index % BOXES_PER_BANK) * BOX_DATA_SIZE
        self.base = W_BOX_COUNT if self.active else self.sram

    def read(self, offset: int, size: int = 1) -> bytes:
        start = self.base + offset
        window = slice(start, start + size)
        return bytes(self.mem[window] if self.active else self.mem[self.bank, window])

    def write(self, offset: int, data: bytes):
        start = self.base + offset
        window = slice(start, start + len(data))
        if self.active:
            self.mem[window] = list(data)
        else:
            self.mem[self.bank, window] = list(data)

    @property
    def count(self) -> int:
        return min(self.read(OFF_COUNT)[0], BOX_CAPACITY)

    def flush(self):
        """Push the open box back to cartridge RAM and re-sum the bank.

        The game itself copies the open box to SRAM whenever it changes box or saves, so the
        SRAM copy of the active box is stale between those moments; mirroring it keeps the two
        copies honest and makes the bank checksum mean something.
        """
        if self.active:
            self.mem[self.bank, self.sram:self.sram + BOX_DATA_SIZE] = \
                list(self.mem[self.base:self.base + BOX_DATA_SIZE])
        refresh_checksums(self.mem, self.bank)


def refresh_checksums(mem, bank: int):
    """Recompute a box bank's checksums: sum the bytes, then complement (pokered `SAVCheckSum`).

    A running game never reads these, but `Continue` from the title screen does, and a bad
    all-boxes checksum makes the game wipe every box — so a hand-edited bank must be re-summed.
    """
    data = bytes(mem[bank, SRAM_BOXES:SRAM_BOXES + BOXES_PER_BANK * BOX_DATA_SIZE])
    mem[bank, SRAM_ALL_BOXES_CHECKSUM] = (~sum(data)) & 0xFF
    for i in range(BOXES_PER_BANK):
        mem[bank, SRAM_BOX_CHECKSUMS + i] = (~sum(data[i * BOX_DATA_SIZE:(i + 1) * BOX_DATA_SIZE])) & 0xFF


@dataclass(frozen=True)
class Slot:
    """One stored Pokémon: everything a box keeps about it, and nothing else."""
    box: int
    position: int
    struct: bytes           # 33 bytes of box_struct
    nickname: bytes         # 11 bytes of Gen I text
    ot_name: bytes          # 11 bytes of Gen I text

    @property
    def species(self) -> int:
        return self.struct[SPECIES]

    @property
    def level(self) -> int:
        return self.struct[LEVEL]

    @property
    def nick(self) -> str:
        return decode_text(self.nickname)

    @property
    def trainer(self) -> str:
        return decode_text(self.ot_name)

    @property
    def name(self) -> str:
        return SPECIES_NAMES.get(self.species, f"#{self.species}")


def read_slot(mem, box: int, position: int) -> Slot:
    """The Pokémon in (box, position), both 1-based. Raises LookupError if the slot is empty."""
    view = BoxView(mem, box)
    if not 1 <= position <= view.count:
        raise LookupError(f"Box {box} holds {view.count} Pokémon, so position {position} is empty")
    i = position - 1
    return Slot(box, position,
                view.read(OFF_MONS + i * BOX_STRUCT, BOX_STRUCT),
                view.read(OFF_NICKNAMES + i * NAME_LENGTH, NAME_LENGTH),
                view.read(OFF_OT_NAMES + i * NAME_LENGTH, NAME_LENGTH))


def write_slot(mem, box: int, position: int, slot: Slot):
    """Put a Pokémon in (box, position), leaving the box internally consistent.

    The species list and the count are what the game reads to draw the box and to decide how
    many entries exist, so both have to follow the struct in. Writing one past the end appends;
    the list stays contiguous because Gen I has no concept of a gap in a box.
    """
    if len(slot.struct) != BOX_STRUCT:
        raise ValueError("A box entry is 33 bytes")
    if len(slot.nickname) != NAME_LENGTH or len(slot.ot_name) != NAME_LENGTH:
        raise ValueError("Box names are 11 bytes")
    view = BoxView(mem, box)
    count = view.count
    if not 1 <= position <= min(count + 1, BOX_CAPACITY):
        raise ValueError(f"Position {position} would leave a gap in box {box} (count {count})")
    i = position - 1
    view.write(OFF_MONS + i * BOX_STRUCT, slot.struct)
    view.write(OFF_NICKNAMES + i * NAME_LENGTH, slot.nickname)
    view.write(OFF_OT_NAMES + i * NAME_LENGTH, slot.ot_name)
    view.write(OFF_SPECIES_LIST + i, bytes([slot.species]))
    if position == count + 1:                       # appended: grow the count, move the terminator
        view.write(OFF_COUNT, bytes([position]))
        view.write(OFF_SPECIES_LIST + position, bytes([LIST_TERMINATOR]))
    view.flush()


def with_species(struct: bytes, species: int, types=None, catch_rate: int | None = None) -> bytes:
    """Change a box entry's species, as an evolution does.

    Level, experience, DVs and EVs are deliberately untouched: the game recomputes the new
    form's stats from them on withdrawal. Types and catch rate are per-species header data that
    pokered's EvolveMon copies out of the new base stats, so they are updated here too.
    """
    out = bytearray(struct)
    out[SPECIES] = species
    if types:
        out[TYPE1], out[TYPE2] = types[0], types[-1]
    if catch_rate is not None:
        out[CATCH_RATE] = catch_rate
    return bytes(out)


def renamed(slot: Slot, nickname: str) -> Slot:
    return replace(slot, nickname=encode_text(nickname))


def inventory(mem) -> tuple[dict, ...]:
    """Every stored Pokémon with the (box, position) a trade proposal needs to name it.

    ram.read_stored_pokemon reports the same Pokémon but not where in the box they sit, and a
    broker cannot address a slot without that.
    """
    out = []
    for box in range(1, BOX_COUNT + 1):
        view = BoxView(mem, box)
        for position in range(1, view.count + 1):
            slot = read_slot(mem, box, position)
            if slot.species in SPECIES_NAMES and 1 <= slot.level <= 100:
                out.append({"box": box, "position": position, "species": slot.species,
                            "level": slot.level, "nick": slot.nick, "name": slot.name})
    return tuple(out)
