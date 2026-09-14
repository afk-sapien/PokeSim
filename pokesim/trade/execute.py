"""Execute an agreed trade at save level: swap one boxed Pokémon between two checkpoints.

pokesim persists PyBoy save states, not cartridge .sav files, so there is no save file to
edit. Instead each side is booted headless on its own ROM, its checkpoint is loaded, the box
bytes are moved through `pyboy.memory` (see boxes.py for the layout), and a fresh state is
written back out. No link cable, no emulation of the trade protocol.

A trade either happens on both sides or on neither. Both new states are produced in memory
before either is published, the originals are never overwritten, and a failed second write
removes the first — so there is no moment at which one run has traded and the other has not.

Proposal shape, as the broker produces it (box and position are 1-based, like the `box` field
the web API already publishes):

    {'give': {'instance': 'red', 'dex': 63, 'species': 148, 'box': 2, 'position': 7,
              'level': 30, 'nick': 'ABRA', 'name': 'Abra'},
     'take': {'instance': 'blue', ...}, 'reason': str, 'price': str}

`sources` maps instance name -> {'rom': Path, 'state': Path}.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import time
from dataclasses import replace
from pathlib import Path

from pyboy import PyBoy

from ..checkpoints import CheckpointStore
from ..policies.collection import EVOS
from ..ram import W_DEX_OWNED, W_DEX_SEEN
from ..strategy_data import SPECIES
from . import boxes

log = logging.getLogger(__name__)

# The four Gen I species that evolve on being traded, straight out of the collection data.
TRADE_EVOS = {sid: row["species"] for sid, rows in EVOS.items()
              for row in rows if row["method"] == "trade"}


class TradeError(Exception):
    """The trade did not happen, and nothing was written."""


def in_game_name(species: int) -> str:
    """The all-caps name the cartridge itself stores, e.g. KADABRA."""
    return SPECIES.get(species, {}).get("name", "").replace("_", " ")


def evolve_on_arrival(slot: boxes.Slot) -> tuple[boxes.Slot, int | None]:
    """Apply a trade evolution to a Pokémon arriving in the other game.

    Returns the arriving slot and the species it evolved from, or None. Only the species
    header changes; pokered's RenameEvolvedMon renames a mon that was still carrying its
    species as a nickname, so do that too and leave a real nickname alone.
    """
    target = TRADE_EVOS.get(slot.species)
    if target is None:
        return slot, None
    base = SPECIES.get(target, {})
    arrived = replace(slot, struct=boxes.with_species(slot.struct, target,
                                                      base.get("types"), base.get("catch_rate")))
    if slot.nick == in_game_name(slot.species):
        arrived = boxes.renamed(arrived, in_game_name(target))
    return arrived, slot.species


def register_arrival(mem, *species):
    """Register both the incoming species and any evolution in the recipient's Pokédex."""
    for sid in species:
        dex = SPECIES[sid]['dex']
        byte, bit = divmod(dex - 1, 8)
        for address in (W_DEX_OWNED, W_DEX_SEEN):
            mem[address + byte] |= 1 << bit


def _boot(rom: Path, state: Path, expect_sha1: str | None) -> PyBoy:
    if expect_sha1 and hashlib.sha1(rom.read_bytes()).hexdigest() != expect_sha1:
        raise TradeError(f"{state.name} was recorded with a different ROM than {rom.name}")
    pb = PyBoy(str(rom), window="null", sound_emulated=False)
    pb.set_emulation_speed(0)
    try:
        with open(state, "rb") as f:
            pb.load_state(f)
    except Exception as error:
        pb.stop(save=False)
        raise TradeError(f"Cannot load {state.name}: {error}") from error
    return pb


def _manifest(state: Path) -> dict | None:
    sidecar = state.with_suffix(".json")
    if not sidecar.exists():
        return None
    data = json.loads(sidecar.read_text())
    if not isinstance(data, dict):
        raise TradeError(f"{sidecar.name} is not a checkpoint manifest")
    return data


def _verify(mem, want: dict, instance: str) -> boxes.Slot:
    """Refuse to trade anything but the exact Pokémon that was negotiated."""
    try:
        slot = boxes.read_slot(mem, int(want["box"]), int(want["position"]))
    except (LookupError, ValueError) as error:
        raise TradeError(f"{instance}: {error}") from error
    if slot.species != int(want["species"]) or slot.level != int(want["level"]):
        raise TradeError(
            f"{instance}: box {want['box']} position {want['position']} holds "
            f"{slot.name} level {slot.level}, not {want.get('name', want['species'])} "
            f"level {want['level']} — the run has moved on since the proposal")
    return slot


def _destination(state: Path, manifest: dict | None) -> Path:
    """A new checkpoint beside the old one, so a trade is picked up like any other autosave.

    Emulator.start restores the newest `auto-*.state`, which makes publishing a new file both
    the safest write (the original stays readable if anything goes wrong) and the one the run
    already knows how to resume from. A state with no manifest is not an autosave and keeps
    its own name, since an `auto-v1-` file without a sidecar cannot be restored.
    """
    stamp = time.time_ns()
    return state.parent / (f"auto-v1-{stamp}.state" if manifest else f"{state.stem}-trade-{stamp}.state")


def perform(proposal: dict, sources: dict, outputs: dict | None = None) -> dict:
    """Carry out an agreed swap and return what moved.

    `outputs` optionally names the destination state file per instance; by default each side
    gets a fresh checkpoint next to the one it came from.
    """
    try:
        give, take = proposal["give"], proposal["take"]
    except (KeyError, TypeError) as error:
        raise TradeError("A proposal needs a give and a take") from error
    if give["instance"] == take["instance"]:
        raise TradeError("A trade needs two different instances")

    machines: dict[str, PyBoy] = {}
    try:
        held, manifests, states = {}, {}, {}
        for role, want in (("give", give), ("take", take)):
            name = want["instance"]
            try:
                source = sources[name]
            except KeyError:
                raise TradeError(f"No save was supplied for {name}") from None
            states[role] = Path(source["state"])
            manifests[role] = _manifest(states[role])
            machines[role] = _boot(Path(source["rom"]), states[role],
                                   (manifests[role] or {}).get("rom_sha1"))
            held[role] = _verify(machines[role].memory, want, name)

        # Each side's Pokémon lands in the slot the other one just vacated, evolving on the way.
        moved = []
        for role, other in (("give", "take"), ("take", "give")):
            want, arriving = proposal[role], held[other]
            landed, evolved_from = evolve_on_arrival(arriving)
            boxes.write_slot(machines[role].memory, int(want["box"]), int(want["position"]), landed)
            register_arrival(machines[role].memory, arriving.species, landed.species)
            moved.append({"instance": want["instance"], "box": int(want["box"]),
                          "position": int(want["position"]),
                          "sent": {"species": held[role].species, "name": held[role].name,
                                   "level": held[role].level, "nick": held[role].nick},
                          "received": {"species": landed.species, "name": landed.name,
                                       "level": landed.level, "nick": landed.nick,
                                       "evolved_from": evolved_from}})

        blobs = {role: _state_bytes(machines[role]) for role in ("give", "take")}
    finally:
        for pb in machines.values():
            pb.stop(save=False)

    written: list[Path] = []
    try:
        for role in ("give", "take"):
            name = proposal[role]["instance"]
            target = Path(outputs[name]) if outputs and name in outputs \
                else _destination(states[role], manifests[role])
            _publish(target, blobs[role], manifests[role])
            written.append(target)
            moved[0 if role == "give" else 1]["state"] = str(target)
    except OSError as error:
        for path in written:                # a half-written pair is worse than no trade at all
            path.unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)
        raise TradeError(f"Could not publish the traded states: {error}") from error

    log.info("traded %s <-> %s", moved[0]["sent"]["name"], moved[1]["sent"]["name"])
    return {"moved": moved, "reason": proposal.get("reason", ""), "price": proposal.get("price", ""),
            "states": {entry["instance"]: entry["state"] for entry in moved}}


def _state_bytes(pb: PyBoy) -> bytes:
    buf = io.BytesIO()
    pb.save_state(buf)
    return buf.getvalue()


def _publish(path: Path, state: bytes, manifest: dict | None):
    """Write a state, and its manifest if the source had one, the way the store does."""
    CheckpointStore.atomic_write(path, state)
    if manifest is not None:
        updated = dict(manifest, sha256=hashlib.sha256(state).hexdigest())
        CheckpointStore.atomic_write(path.with_suffix(".json"), json.dumps(updated).encode())
