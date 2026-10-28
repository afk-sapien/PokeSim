"""Progress events read from two snapshots in a row, for both generations.

Gen I and Gen II snapshots share the fields read here: the Pokédex, the bag, the party, the box counts,
the badges, the League count and the event flags. A goal-specific event, such as reaching a target map
or meeting a target species, is added by the goal that knows its target.
"""
from __future__ import annotations

from .monitor import ProgressEvent


def _held(snapshot):
    boxes = getattr(snapshot, 'box_counts', ()) or ()
    if boxes:
        return len(snapshot.party) + sum(boxes)
    stored = getattr(snapshot, 'stored', None)
    if stored is None:
        stored = getattr(snapshot, 'stored_pokemon', ()) or getattr(snapshot, 'boxed_pokemon', ())
    return len(snapshot.party) + len(stored)


def _flags_set(before, after):
    return sum(bin(~a & b & 255).count('1') for a, b in zip(before, after))


def events(previous, snapshot):
    """What ``snapshot`` gained over ``previous``. A missing or unreadable snapshot gains nothing."""
    if previous is None or snapshot is None or not getattr(snapshot, 'valid', True) \
            or not getattr(previous, 'valid', True):
        return []
    found = []
    new = snapshot.owned - previous.owned
    if new:
        found.append(ProgressEvent('dex', len(new)))
    held, before = _held(snapshot), _held(previous)
    if held > before:
        found.append(ProgressEvent('catch'))
    elif held < before:
        # A Pokémon let go frees a slot the next catch needs, which a visit to the PC is for.
        found.append(ProgressEvent('room', before - held))
    bag = dict(previous.items)
    gained = [item for item, count in snapshot.items if count > bag.get(item, 0)]
    if gained:
        found.append(ProgressEvent('item', tuple(gained)))
    levels = [after.level - before.level for before, after in zip(previous.party, snapshot.party)
              if before.species == after.species and after.level > before.level]
    if levels:
        found.append(ProgressEvent('level', sum(levels)))
    if snapshot.badges & ~previous.badges:
        found.append(ProgressEvent('badge'))
    if getattr(snapshot, 'hall_of_fame_count', 0) > getattr(previous, 'hall_of_fame_count', 0):
        found.append(ProgressEvent('league'))
    flags = _flags_set(getattr(previous, 'event_flags', b''), getattr(snapshot, 'event_flags', b''))
    if flags:
        found.append(ProgressEvent('event', flags))
    return found
