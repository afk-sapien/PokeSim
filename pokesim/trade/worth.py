"""What a trade may give and what an incoming Pokémon is worth to its recipient, both read from the PC
value rows (pcvalue.py), so a trade keeps and lets go of Pokémon by the rules a release follows.

A trade gives a spare, or a copy the PC keeps for a linked adventure that lacks the species
(pcvalue.gives). An incoming Pokémon gains what the recipient's PC would keep it for: a new Pokédex
entry, the only copy, a copy its evolution family needs, or a rarer, shiny or trained copy. Level is no
gain, since any copy can be trained. A copy kept only to pass on gains nothing, so the same species is
not traded on down a chain of adventures.
"""
from dataclasses import dataclass

from .. import pcvalue
from ..pcvalue import Entry, Inputs
from ..rarity import generic

GEN2 = ('gold', 'silver', 'crystal')
# Points for each new Pokédex entry an incoming Pokémon brings, counting the one it evolves into.
NEW_ENTRY = 100
# Points for the reason the recipient's PC keeps an incoming copy of a registered species.
POINTS = {'Only copy': 20, pcvalue.FAMILY: 10, 'Rarer': 5, 'Shiny': 5, 'Trained': 5, 'Needed': 5}


@dataclass(frozen=True)
class Gain:
    """What one incoming Pokémon is worth to its recipient: ranking ``points``, the PC's ``reason``
    and the Pokédex numbers it registers."""
    points: int
    reason: str = ''
    new: tuple = ()


def _gen2(inventory):
    return inventory.get('cartridge_generation') == 2 or inventory.get('version') in GEN2


def inputs(inventory, demand=None):
    """The pcvalue.Inputs for a payload: the version's own rarity, the linked adventures' ``demand``
    by Pokédex number, and in Red, Blue and Yellow the evolution families its Pokédex still needs.
    Gold, Silver and Crystal rate by the DV total here, since their tables load only in their own
    adventure."""
    demand = {int(dex): count for dex, count in (demand or {}).items() if count}
    if _gen2(inventory):
        return Inputs(demand=demand, rarity=generic)
    from ..investment import dex_rarity
    from ..policies.team import evolutions
    owned = inventory.get('owned')
    return Inputs(demand=demand, rarity=dex_rarity, evolutions=evolutions(),
                  owned=None if owned is None else frozenset(owned))


def experience(mon):
    """A payload record's total experience. Gold, Silver and Crystal records carry the progress through
    the level (pokecore's experience_progress) in its place. pcvalue.rate keys its rows by Entry, so a
    row holding that dict cannot be rated."""
    value = mon.get('experience')
    if isinstance(value, dict):
        value = value.get('total')
    return value if type(value) is int else 0


def entries(party, stored):
    """PC value rows for a payload's party and boxed Pokémon, grouped by Pokédex number. Keep and
    Never trade lock a Pokémon, and Prefer to trade marks an offered partner."""
    rows = []
    for index, mon in enumerate([*party, *stored]):
        preference = mon.get('trade_preference')
        rows.append(Entry(None if index < len(party) else (mon.get('box', 1), mon.get('position', index)),
                          (mon.get('dex') or mon['species'], 0), mon.get('name', ''), mon.get('level', 0),
                          experience(mon), tuple(mon.get('dvs') or ()), tuple(mon.get('stat_exp') or ()),
                          bool(mon.get('egg')), locked=preference in ('locked', 'withdrawn'),
                          stock=preference == 'offered', trade=preference == 'offered', record=mon))
    return rows


def spares(party, stored, inventory, demand=None):
    """The boxed records a trade may give (pcvalue.gives), lowest value first."""
    rated = pcvalue.rate(entries(party, stored), inputs(inventory, demand))
    return [row.entry.record for row in pcvalue.queue(rated) if pcvalue.gives(row)]


def given(rated):
    """The boxed slots, as (box, position) counted from 1, that a trade may give from the PC's own
    rows (pc_rated), which know the plan, the hunt and the party."""
    return frozenset((row.entry.slot[0] + 1, row.entry.slot[1] + 1) for row in rated
                     if row.entry.slot is not None and pcvalue.gives(row))


def gain(inventory, mon):
    """What ``mon``, an offer from another adventure, is worth to the adventure whose payload is
    ``inventory``. It arrives as ``arrived_dex`` when the cable evolves it. The PC's family and rarity
    rules decide it as the next release would (pcvalue.verdict). Copies kept for other adventures come
    after the adventure's own, so leaving the demand out changes no points."""
    dex = mon.get('arrived_dex', mon.get('dex'))
    owned = set(inventory.get('owned') or ())
    new = tuple(sorted({mon.get('dex'), dex} - owned - {None}))
    if new:
        return Gain(NEW_ENTRY * len(new), 'New entry', new)
    party = list(inventory.get('party') or ())
    stored = list((inventory.get('storage') or {}).get('pokemon') or ())
    incoming = Entry((-1, 0), (dex, 0), mon.get('name', ''), mon.get('level', 5), dvs=tuple(mon.get('dvs') or ()),
                     stat_exp=tuple(mon.get('stat_exp') or ()), origin='traded')
    given_inputs = inputs(inventory)
    # The new copy's own rating reads only its species and later stages (pcvalue.family_need), so the
    # rest of the PC is left out. The coordinator rates every offer against every linked adventure.
    line = _line(dex, given_inputs.evolutions)
    rows = [row for row in entries(party, stored) if row.dex in line]
    found = pcvalue.verdict(pcvalue.rate([*rows, incoming], given_inputs))
    return Gain(POINTS.get(found.reason, 0) if found.keep else 0, found.reason)


def _line(dex, evolutions):
    """``dex`` and every later stage of its family."""
    seen, todo = set(), [dex]
    while todo:
        here = todo.pop()
        if here not in seen:
            seen.add(here)
            todo.extend(evolutions.get(here, ()))
    return seen


def why(game, species, found):
    """The line a suggested trade shows for what ``game`` gains from ``species``, or '' for no gain."""
    if found.new:
        return f'New Pokédex entry for {game}: {species}'
    if not found.points:
        return ''
    return {'Only copy': f'{game} has no {species} right now',
            pcvalue.FAMILY: f'{game} needs a {species} to evolve for a missing Pokédex entry',
            'Rarer': f'A rarer {species} for {game}',
            'Shiny': f'A shiny {species} for {game}',
            'Trained': f'A trained {species} for {game}'}.get(found.reason, f'{game} needs another {species}')
