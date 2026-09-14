"""Save-level trades: box slot surgery, and swapping one Pokémon between two checkpoints."""
import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path

import pytest

from pokesim.ram import (BOX_CAPACITY, BOX_DATA_SIZE, W_BOX_COUNT, W_CURRENT_BOX,
                         read_box_counts, read_stored_pokemon)
from pokesim.trade import boxes
from pokesim.trade.execute import TradeError, evolve_on_arrival, perform

ROM = Path(os.environ.get("ROM_PATH", "roms/pokered.gb"))
PEER_ROM = Path(os.environ.get("BLUE_ROM_PATH", str(ROM)))
SAMPLE_STATE = Path(os.environ.get("TRADE_SAMPLE_STATE", "roms/sample.state"))
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="no ROM")

ABRA, KADABRA, ALAKAZAM = 148, 38, 149
HAUNTER, GENGAR = 147, 14
MACHOKE = 41


class Memory:
    """Stands in for pyboy.memory: the flat address space plus cartridge RAM banks."""

    def __init__(self):
        self.flat = bytearray(0x10000)
        self.banks = {bank: bytearray(0x2000) for bank in (1, 2, 3)}

    def _target(self, key):
        if isinstance(key, tuple):
            bank, key = key
            return self.banks[bank], -0xA000, key
        return self.flat, 0, key

    def __getitem__(self, key):
        buf, shift, key = self._target(key)
        if isinstance(key, slice):
            return list(buf[key.start + shift:key.stop + shift])
        return buf[key + shift]

    def __setitem__(self, key, value):
        buf, shift, key = self._target(key)
        if isinstance(key, slice):
            buf[key.start + shift:key.stop + shift] = bytes(value)
        else:
            buf[key + shift] = value


def entry(species, level, nick="ROCKY", trainer="SKYE", dvs=0x9AD4, hp_ev=500):
    """A box entry with distinctive level, DVs and EVs so a trade evolution can be checked."""
    struct = bytearray(boxes.BOX_STRUCT)
    struct[boxes.SPECIES] = species
    struct[boxes.LEVEL] = level
    struct[boxes.TYPE1] = struct[boxes.TYPE2] = 0
    struct[boxes.CATCH_RATE] = 45
    struct[14:17] = (level ** 3).to_bytes(3, "big")
    struct[17:19] = hp_ev.to_bytes(2, "big")
    struct[27:29] = dvs.to_bytes(2, "big")
    return boxes.Slot(0, 0, bytes(struct), boxes.encode_text(nick), boxes.encode_text(trainer))


def populate(mem, active=1, contents=((1, ABRA, 30), (3, MACHOKE, 41))):
    """A game with an open box and a couple of stored Pokémon in named (box, species, level)s."""
    mem[W_CURRENT_BOX] = 0x80 | (active - 1)    # bit 7: the boxes have been initialised
    mem[W_BOX_COUNT] = 0
    mem[W_BOX_COUNT + boxes.OFF_SPECIES_LIST] = boxes.LIST_TERMINATOR
    for bank in (2, 3):
        for i in range(boxes.BOXES_PER_BANK):
            mem[bank, 0xA000 + i * BOX_DATA_SIZE] = 0
            mem[bank, 0xA001 + i * BOX_DATA_SIZE] = boxes.LIST_TERMINATOR
    for box, species, level in contents:
        boxes.write_slot(mem, box, 1, entry(species, level))
    return mem


def test_a_box_slot_survives_a_write_and_read_round_trip():
    mem = populate(Memory())
    for box in (1, 3):
        slot = boxes.read_slot(mem, box, 1)
        assert (slot.level, slot.nick, slot.trainer) == (30 if box == 1 else 41, "ROCKY", "SKYE")
    assert boxes.read_slot(mem, 1, 1).species == ABRA
    # The reader the rest of pokesim uses has to see the same thing.
    assert read_box_counts(mem)[:3] == (1, 0, 1)
    assert read_stored_pokemon(mem) == ((0, ABRA, 30, "ROCKY"), (2, MACHOKE, 41, "ROCKY"))


def test_the_active_box_and_a_stored_box_are_written_the_same_way():
    mem = populate(Memory(), active=3)
    # Box 3 is open, so it lives in WRAM; box 1 is in cartridge RAM. Both round-trip.
    assert boxes.BoxView(mem, 3).active and not boxes.BoxView(mem, 1).active
    assert boxes.read_slot(mem, 3, 1).species == MACHOKE
    assert mem[W_BOX_COUNT] == 1 and mem[W_BOX_COUNT + boxes.OFF_MONS] == MACHOKE
    # The open box is mirrored back into its bank, the way the game does on a box change.
    assert mem[2, 0xA000 + 2 * BOX_DATA_SIZE + boxes.OFF_MONS] == MACHOKE


def test_appending_to_a_box_grows_the_count_and_moves_the_terminator():
    mem = populate(Memory())
    boxes.write_slot(mem, 1, 2, entry(HAUNTER, 25, nick="SPOOK"))
    view = boxes.BoxView(mem, 1)
    assert view.count == 2
    assert list(view.read(boxes.OFF_SPECIES_LIST, 3)) == [ABRA, HAUNTER, boxes.LIST_TERMINATOR]
    assert boxes.read_slot(mem, 1, 2).nick == "SPOOK"
    with pytest.raises(ValueError):
        boxes.write_slot(mem, 1, 4, entry(HAUNTER, 25))      # would leave a gap
    with pytest.raises(LookupError):
        boxes.read_slot(mem, 1, 3)


def test_a_full_box_keeps_its_terminator_inside_the_species_list():
    mem = populate(Memory(), contents=())
    for position in range(1, BOX_CAPACITY + 1):
        boxes.write_slot(mem, 2, position, entry(ABRA, position))
    view = boxes.BoxView(mem, 2)
    assert view.count == BOX_CAPACITY
    # The list is 21 bytes: twenty species and the terminator, which is still inside the box.
    assert view.read(boxes.OFF_SPECIES_LIST + BOX_CAPACITY)[0] == boxes.LIST_TERMINATOR
    assert boxes.OFF_SPECIES_LIST + BOX_CAPACITY < boxes.OFF_MONS
    assert boxes.read_slot(mem, 2, BOX_CAPACITY).level == BOX_CAPACITY


def test_writing_a_box_leaves_the_bank_checksums_correct():
    # Boxes 1-6 live in bank 2 and 7-12 in bank 3, so touch one of each.
    mem = populate(Memory(), contents=((1, ABRA, 30), (7, MACHOKE, 41)))
    for bank in (2, 3):
        data = bytes(mem[bank, 0xA000:0xA000 + boxes.BOXES_PER_BANK * BOX_DATA_SIZE])
        assert mem[bank, boxes.SRAM_ALL_BOXES_CHECKSUM] == (~sum(data)) & 0xFF
        for i in range(boxes.BOXES_PER_BANK):
            chunk = data[i * BOX_DATA_SIZE:(i + 1) * BOX_DATA_SIZE]
            assert mem[bank, boxes.SRAM_BOX_CHECKSUMS + i] == (~sum(chunk)) & 0xFF


def test_text_encoding_is_the_inverse_of_the_snapshot_reader():
    from pokesim.ram import decode_text
    for name in ("ABRA", "MR.MIME", "FARFETCH'D", "NIDORAN♂", "Rocky2"):
        assert decode_text(boxes.encode_text(name)) == name
    assert len(boxes.encode_text("A" * 30)) == boxes.NAME_LENGTH


def test_a_trade_evolution_keeps_level_experience_dvs_and_evs():
    before = entry(HAUNTER, 44, nick="SPOOK")
    after, evolved_from = evolve_on_arrival(before)
    assert (evolved_from, after.species, after.level) == (HAUNTER, GENGAR, 44)
    assert after.struct[8:] == before.struct[8:]     # experience, EVs, DVs and PP untouched
    assert after.nick == "SPOOK"                     # a real nickname survives evolution
    assert after.struct[boxes.TYPE1:boxes.TYPE2 + 1] != before.struct[boxes.TYPE1:boxes.TYPE2 + 1]


def test_a_default_named_pokemon_is_renamed_when_it_evolves_on_arrival():
    after, _ = evolve_on_arrival(entry(KADABRA, 30, nick="KADABRA"))
    assert (after.species, after.nick) == (ALAKAZAM, "ALAKAZAM")


def test_a_pokemon_that_does_not_evolve_by_trade_arrives_unchanged():
    before = entry(ABRA, 12)
    after, evolved_from = evolve_on_arrival(before)
    assert evolved_from is None and after == before


def test_a_mismatched_proposal_is_refused_before_anything_is_written():
    mem = populate(Memory())
    from pokesim.trade.execute import _verify
    with pytest.raises(TradeError, match="the run has moved on"):
        _verify(mem, {"box": 1, "position": 1, "species": ABRA, "level": 31, "name": "Abra"}, "red")
    with pytest.raises(TradeError, match="position 2 is empty"):
        _verify(mem, {"box": 1, "position": 2, "species": ABRA, "level": 30}, "red")


def test_the_inventory_names_every_stored_pokemon_by_box_and_position():
    mem = populate(Memory())
    boxes.write_slot(mem, 1, 2, entry(HAUNTER, 25, nick="SPOOK"))
    found = boxes.inventory(mem)
    assert [(row["box"], row["position"], row["species"]) for row in found] == \
        [(1, 1, ABRA), (1, 2, HAUNTER), (3, 1, MACHOKE)]


# ---------------------------------------------------------------- real emulator, real states

def checkpoint(directory, rom, name, contents, active=1, manifest=True):
    """A save state whose boxes hold `contents`, built by writing into a freshly booted game."""
    from pyboy import PyBoy
    import io
    directory.mkdir(parents=True, exist_ok=True)
    pb = PyBoy(str(rom), window="null", sound_emulated=False)
    try:
        pb.set_emulation_speed(0)
        pb.tick(120, render=False)
        populate(pb.memory, active=active, contents=contents)
        buf = io.BytesIO()
        pb.save_state(buf)
    finally:
        pb.stop(save=False)
    path = directory / (f"auto-v1-{name}.state" if manifest else f"{name}.state")
    path.write_bytes(buf.getvalue())
    if manifest:
        path.with_suffix(".json").write_text(json.dumps({
            "format": 1, "sha256": hashlib.sha256(buf.getvalue()).hexdigest(),
            "rom_sha1": hashlib.sha1(rom.read_bytes()).hexdigest(),
            "pyboy_version": version("pyboy"), "policy": "strategic",
            "policy_state": {}, "run_memory": {}, "frame": 120}))
    return path


def reread(rom, state):
    from pyboy import PyBoy
    pb = PyBoy(str(rom), window="null", sound_emulated=False)
    try:
        pb.set_emulation_speed(0)
        with open(state, "rb") as f:
            pb.load_state(f)
        return read_stored_pokemon(pb.memory), boxes.inventory(pb.memory)
    finally:
        pb.stop(save=False)


@needs_rom
def test_a_slot_written_into_a_real_save_state_is_there_when_it_is_reloaded(tmp_path):
    state = checkpoint(tmp_path, ROM, "red", ((1, ABRA, 30), (3, MACHOKE, 41)))
    stored, found = reread(ROM, state)
    assert stored == ((0, ABRA, 30, "ROCKY"), (2, MACHOKE, 41, "ROCKY"))
    assert [(row["box"], row["position"], row["level"]) for row in found] == [(1, 1, 30), (3, 1, 41)]


@needs_rom
def test_a_trade_swaps_both_sides_and_applies_the_trade_evolution(tmp_path):
    red = checkpoint(tmp_path / "red", ROM, "red", ((2, HAUNTER, 44),))
    blue = checkpoint(tmp_path / "blue", PEER_ROM, "blue", ((2, MACHOKE, 41),))
    proposal = {"give": {"instance": "red", "species": HAUNTER, "box": 2, "position": 1,
                         "level": 44, "nick": "ROCKY", "name": "Haunter"},
                "take": {"instance": "blue", "species": MACHOKE, "box": 2, "position": 1,
                         "level": 41, "nick": "ROCKY", "name": "Machoke"},
                "reason": "Haunter for Machoke", "price": "a spare"}
    sources = {"red": {"rom": ROM, "state": red}, "blue": {"rom": PEER_ROM, "state": blue}}

    result = perform(proposal, sources)

    # Red now holds the Machoke, evolved into Machamp because it was traded; Blue holds Gengar.
    assert reread(ROM, Path(result["states"]["red"]))[0] == ((1, 126, 41, "ROCKY"),)
    assert reread(PEER_ROM, Path(result["states"]["blue"]))[0] == ((1, GENGAR, 44, "ROCKY"),)
    assert result["moved"][0]["received"]["evolved_from"] == MACHOKE
    assert result["moved"][1]["received"]["name"] == "Gengar"
    # The originals are untouched, and each new checkpoint carries a manifest that matches it.
    assert reread(ROM, red)[0] == ((1, HAUNTER, 44, "ROCKY"),)
    for instance, source in (("red", red), ("blue", blue)):
        published = Path(result["states"][instance])
        assert published != source and published.name.startswith("auto-v1-")
        manifest = json.loads(published.with_suffix(".json").read_text())
        assert manifest["sha256"] == hashlib.sha256(published.read_bytes()).hexdigest()
        assert manifest["rom_sha1"] == json.loads(source.with_suffix(".json").read_text())["rom_sha1"]


@needs_rom
def test_a_proposal_that_no_longer_matches_leaves_both_states_untouched(tmp_path):
    red = checkpoint(tmp_path / "red", ROM, "red", ((2, HAUNTER, 44),))
    blue = checkpoint(tmp_path / "blue", PEER_ROM, "blue", ((2, MACHOKE, 41),))
    before = {path: path.read_bytes() for path in (red, blue)}
    proposal = {"give": {"instance": "red", "species": HAUNTER, "box": 2, "position": 1,
                         "level": 44, "name": "Haunter"},
                "take": {"instance": "blue", "species": MACHOKE, "box": 2, "position": 1,
                         "level": 40, "name": "Machoke"}}     # levelled up since the proposal
    sources = {"red": {"rom": ROM, "state": red}, "blue": {"rom": PEER_ROM, "state": blue}}

    with pytest.raises(TradeError, match="the run has moved on"):
        perform(proposal, sources)

    assert all(path.read_bytes() == data for path, data in before.items())
    assert sorted(p.name for p in tmp_path.glob("*/*.state")) == sorted([red.name, blue.name])


@needs_rom
def test_a_publish_that_fails_leaves_no_half_written_pair(tmp_path):
    red = checkpoint(tmp_path / "red", ROM, "red", ((2, HAUNTER, 44),))
    blue = checkpoint(tmp_path / "blue", PEER_ROM, "blue", ((2, MACHOKE, 41),))
    before = {path: path.read_bytes() for path in (red, blue)}
    proposal = {"give": {"instance": "red", "species": HAUNTER, "box": 2, "position": 1, "level": 44},
                "take": {"instance": "blue", "species": MACHOKE, "box": 2, "position": 1, "level": 41}}
    sources = {"red": {"rom": ROM, "state": red}, "blue": {"rom": PEER_ROM, "state": blue}}
    outputs = {"red": tmp_path / "red" / "traded.state",
               "blue": tmp_path / "nowhere" / "traded.state"}   # the directory does not exist

    with pytest.raises(TradeError, match="Could not publish"):
        perform(proposal, sources, outputs=outputs)

    assert not outputs["red"].exists() and not outputs["blue"].exists()
    assert all(path.read_bytes() == data for path, data in before.items())


@needs_rom
@pytest.mark.skipif(not SAMPLE_STATE.exists(), reason="no populated save state")
def test_a_real_campaign_state_keeps_its_boxes_consistent_after_a_write(tmp_path):
    """The layout has to hold against a save made by the game itself, not only ones we build."""
    from pyboy import PyBoy
    import io
    pb = PyBoy(str(ROM), window="null", sound_emulated=False)
    try:
        pb.set_emulation_speed(0)
        with open(SAMPLE_STATE, "rb") as f:
            pb.load_state(f)
        before = read_stored_pokemon(pb.memory)
        mine = boxes.read_slot(pb.memory, 1, 1)
        boxes.write_slot(pb.memory, 1, 1, boxes.renamed(mine, "TRADED"))
        buf = io.BytesIO()
        pb.save_state(buf)
    finally:
        pb.stop(save=False)
    path = tmp_path / "edited.state"
    path.write_bytes(buf.getvalue())
    after, _ = reread(ROM, path)
    assert len(after) == len(before) == 240
    assert after[0][:3] == before[0][:3] and after[0][3] == "TRADED"
    assert after[1:] == before[1:]


def test_trade_registration_keeps_existing_entries_and_records_both_evolution_stages():
    from pokesim.ram import W_DEX_OWNED, W_DEX_SEEN, flag_bits
    from pokesim.trade.execute import register_arrival
    mem = Memory()
    mem[W_DEX_OWNED] = 1
    mem[W_DEX_SEEN] = 3
    register_arrival(mem, HAUNTER, GENGAR)
    assert set(flag_bits(bytes(mem[W_DEX_OWNED:W_DEX_OWNED + 19]))) == {1, 93, 94}
    assert set(flag_bits(bytes(mem[W_DEX_SEEN:W_DEX_SEEN + 19]))) == {1, 2, 93, 94}
