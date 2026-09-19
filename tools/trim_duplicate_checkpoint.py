"""Offline maintenance helpers for a backed-up, stopped adventure checkpoint.

These helpers do not alter the running game's capture or release policy.
The caller must retain the source checkpoint and verify the output before adoption.
"""
from collections import defaultdict
from dataclasses import asdict

from pokesim.duplicates import quality
from pokesim.trade.boxes import (
    BoxView, LIST_TERMINATOR, OFF_COUNT, OFF_SPECIES_LIST, read_slot, write_slot,
)
from pokesim.trade.preferences import identity


def plan_removals(snapshot, preferences, protected=(), keep=3, threshold=5):
    """Trim large groups, retaining top quality, best DVs, and protected copies.

    Box coordinates match Snapshot and are zero based. Party members never leave.
    Groups of five or fewer remain untouched, even when keep is three.
    """
    if keep < 1 or threshold < keep:
        raise ValueError('Invalid retention limits')
    groups = defaultdict(list)
    for mon in [*(asdict(mon) for mon in snapshot.party), *snapshot.storage_entries()]:
        groups[mon['species']].append(mon)
    removed = []
    for species, copies in groups.items():
        if len(copies) <= threshold or species in protected:
            continue
        ranked = sorted(copies, key=quality, reverse=True)
        retained = {id(mon) for mon in ranked[:keep]}
        retained.add(id(max(copies, key=lambda mon: (sum(mon['dvs']), quality(mon)))))
        for mon in copies:
            if 'box' not in mon or id(mon) in retained:
                continue
            if preferences.get(identity(mon), {}).get('state') in ('locked', 'offered'):
                continue
            removed.append(mon)
    return removed


def compact_boxes(memory, removals):
    """Remove planned slots and preserve every retained record byte for byte.

    Validate the entire selection before writing. Only compact within each box.
    """
    selected = {(mon['box'] + 1, mon['position'] + 1) for mon in removals}
    if len(selected) != len(removals):
        raise ValueError('Duplicate removal coordinates')
    groups = defaultdict(set)
    for mon in removals:
        box, position = mon['box'] + 1, mon['position'] + 1
        slot = read_slot(memory, box, position)
        if slot.species != mon['species'] or slot.level != mon['level']:
            raise ValueError('Removal plan does not match checkpoint')
        groups[box].add(position)
    for box, positions in groups.items():
        view = BoxView(memory, box)
        survivors = [read_slot(memory, box, position)
                     for position in range(1, view.count + 1) if position not in positions]
        for position, slot in enumerate(survivors, 1):
            write_slot(memory, box, position, slot)
        view.write(OFF_COUNT, bytes([len(survivors)]))
        view.write(OFF_SPECIES_LIST + len(survivors), bytes([LIST_TERMINATOR]))
        view.flush()
        actual = [read_slot(memory, box, position)
                  for position in range(1, view.count + 1)]
        assert [(s.struct, s.nickname, s.ot_name) for s in actual] == [
            (s.struct, s.nickname, s.ot_name) for s in survivors]
