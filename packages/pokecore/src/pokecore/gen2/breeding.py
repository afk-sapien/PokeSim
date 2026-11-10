"""Day Care rules for Gen II: who can breed, what hatches and what retrieval costs.

Ported from PokeSim's pokesim/gen2/breeding.py and tracking.py. Each function reads
decoded Mon objects (or anything with the same fields) and consumer game tables.
The cached helpers key on ``data`` itself, so it must be hashable (by identity, as a
plain class or :class:`GameTables` is).
"""
from collections import Counter
from functools import lru_cache

from .ram import calculated_stats, experience_at

DITTO = 132
TYROGUE = 236


def offspring(data, first, second):
    """Species the pair can produce as an egg, or an empty set when they cannot breed.

    Ditto with Ditto, eggs, the NONE egg group, a same-sex pair, no shared egg group and
    parents whose Defense and Special DVs look related all produce nothing, as in the cartridge.
    Nidoran♀ lines can produce either Nidoran.
    """
    if first.egg or second.egg or first.species == second.species == DITTO:
        return set()
    groups = [set(data.species[mon.species]['egg_groups']) for mon in (first, second)]
    if any('NONE' in group for group in groups):
        return set()
    if first.dvs[2] == second.dvs[2] and first.dvs[4] % 8 == second.dvs[4] % 8:
        return set()
    if first.species == DITTO or second.species == DITTO:
        mother = second if first.species == DITTO else first
    elif groups[0] & groups[1] and {first.gender, second.gender} == {'Male', 'Female'}:
        mother = first if first.gender == 'Female' else second
    else:
        return set()
    previous = _pre_evolutions(data)
    species = mother.species
    for _ in range(2):
        species = previous.get(species, species)
    return {29, 32} if species == 29 else {species}


def retrieval_cost(data, snapshot):
    """Money the Day Care asks to return every parent in ``snapshot.daycare`` (100 plus 100 per level gained)."""
    total = 0
    for mon in getattr(snapshot, 'daycare', ()):
        if mon:
            growth = data.species[mon.species]['growth']
            level = max(level for level in range(mon.level, 101) if experience_at(level, growth) <= mon.experience)
            total += (level - mon.level + 1) * 100
    return total


def branch_parents(data, snapshot, baby, branches):
    """Whether the snapshot's party and storage hold enough of ``baby`` to evolve into every species in ``branches``.

    Tyrogue's branch depends on Attack against Defense at the level it would evolve.
    """
    available = [mon for mon in snapshot.party + snapshot.stored if mon.species == baby]
    if baby != TYROGUE:
        return len(available) >= len(branches)
    possible = set()
    for mon in available:
        stats = calculated_stats(data.species[baby]['stats'], max(20, mon.level + 1), mon.dvs, mon.stat_exp)
        possible.add(107 if stats[1] < stats[2] else 106 if stats[1] > stats[2] else 237)
    return branches <= possible


def ancestors(data, species):
    """``species`` and every species that evolves into it, directly or not."""
    family = {species}
    while True:
        parents = {sid for sid, row in data.species.items()
                   if any(evo['species'] in family for evo in row['evolutions'])}
        if parents <= family:
            return frozenset(family)
        family.update(parents)


def level_credit(data, species):
    """The species a level-up of ``species`` counts toward: itself, or its whole line when it is final."""
    return {species} if data.species[species]['evolutions'] else ancestors(data, species)


def _pre_evolutions(data):
    """Each species' pre-evolution, the first in species order as a scan of the table would find it.

    A breeding search asks once for every pair of Pokémon the player owns, so the map is built once
    per species table rather than by scanning the whole table for every pair.
    """
    cached = getattr(data, '_pre_evolutions', None)
    if cached is not None and cached[0] is data.species:
        return cached[1]
    previous = {}
    for sid, row in data.species.items():
        for evo in row['evolutions']:
            previous.setdefault(evo['species'], sid)
    try:
        data._pre_evolutions = (data.species, previous)
    except AttributeError:
        pass
    return previous


@lru_cache(maxsize=8)
def families(data):
    """Every species mapped to its whole evolution family, babies included."""
    parents = {evo['species']: sid for sid, row in data.species.items() for evo in row['evolutions']}
    result = {}
    for species in data.species:
        root = species
        while root in parents:
            root = parents[root]
        result.setdefault(root, set()).add(species)
    return {species: frozenset(members) for members in result.values() for species in members}


@lru_cache(maxsize=8)
def single_source(data):
    """Families this cartridge never offers in the wild, keyed by member.

    Bill's Eevee, Togepi, Kiyo's Tyrogue, Sudowoodo, Snorlax, Lapras and Pokémon that arrived by cable
    appear once per save. The Day Care is the only way to make another copy, so a family whose members
    can still breed is worth keeping a parent of. ``data.encounters`` rows name each wild ``species``.
    """
    wild = {row['species'] for row in data.encounters}
    return {species: family for species, family in families(data).items()
            if not family & wild and any('NONE' not in data.species[sid]['egg_groups'] for sid in family)}


def lines(data, baby):
    """Each later stage of ``baby`` with the species along its way and the methods that reach it.

    Rows are ``(species, path, methods)`` where ``path`` includes ``baby`` and ``species``.
    """
    result, stack = [], [(baby, frozenset({baby}), frozenset())]
    while stack:
        species, path, methods = stack.pop()
        for evo in data.species[species]['evolutions']:
            row = (evo['species'], path | {evo['species']}, methods | {evo['method']})
            result.append(row)
            stack.append(row)
    return result


def breeding_stock(data, species):
    """Species whose only held copy should stay home as a Day Care parent.

    ``species`` lists every held Pokémon that is not an egg. The last Ditto pairs with anything, and the
    last member of a family with no wild source is the only way to breed that family again.
    """
    held, single = Counter(species), single_source(data)
    keep = {DITTO} if held[DITTO] == 1 else set()
    for sid, count in held.items():
        if count == 1 and sid in single and sum(held[member] for member in single[sid]) == 1:
            keep.add(sid)
    return keep


def egg_lines(data, snapshot):
    """Every species in the family of an egg held in the party or the PC.

    An egg only hatches while it travels in the party. One left in a box keeps its line unhatched, so
    breeding that line again would only collect another egg for the PC.
    """
    family = families(data)
    return frozenset(species for mon in snapshot.party + snapshot.stored if mon.egg
                     for species in family.get(mon.species, {mon.species}))


def free_slots(snapshot):
    """Empty PC box slots across ``snapshot.box_counts``, or 99 when the counts are unknown."""
    counts = getattr(snapshot, 'box_counts', None)
    return 99 if counts is None else sum(max(0, 20 - count) for count in counts)


def descendants_wanted(data, snapshot, demand, baby):
    """Whether demand for a later stage of a single source family needs another ``baby`` hatched.

    ``demand`` maps species to the copies wanted, for example by another adventure over the cable.
    Espeon, Umbreon or a Hitmon can only come from breeding an Eevee or a Tyrogue and raising it.
    Stone evolutions are left out because a cartridge has few of each stone.
    """
    if baby not in single_source(data):
        return False
    held = snapshot.party + snapshot.stored
    return any(demand.get(target) and 'item' not in methods
               and sum(mon.species in path for mon in held) <= demand[target]
               for target, path, methods in lines(data, baby))
