"""Pairing two inventories into trades both runs would accept.

Pure decision-making: no emulator, no save file, no HTTP. A proposal is a want paired with a
price, and both sides must end up ahead — a give is only offered to a peer that is missing the
species, and a take is only wanted when we are missing it. The one asymmetry is the premium
target: no duplicate can fairly buy a species the cartridge cannot reach on its own, so those are
priced in a trained Pokémon instead.

A proposal is `{'give': side, 'take': side, 'reason': str, 'price': 'duplicate swap' | 'premium',
'spends': {'give': standing, 'take': standing}}`, where each side is
`{instance, dex, species, box, position, level, nick, name}` and a standing is one of 'spare',
'best copy' or 'last one' — what that run actually parts with. **Box and position
are both 1-BASED**, which is what the save-level executor addresses slots with. Getting this wrong
is not a harmless off-by-one: the boxes hold runs of same-species, same-level duplicates, so a
neighbouring slot passes the executor's verification and the wrong individual is traded away.
"""
from __future__ import annotations

from functools import lru_cache

from ..game_data import load
from ..ram import DEX_NAMES
from ..strategy_data import SPECIES
from .inventory import Copy, Inventory

PREMIUM_LEVEL = 90
TRADE_EVOLUTIONS = {65: 'Alakazam', 68: 'Machamp', 76: 'Golem', 94: 'Gengar'}
SPENT_ORDER = {'spare': 0, 'best copy': 1, 'last one': 2}


@lru_cache(maxsize=1)
def premium_dex() -> frozenset[int]:
    """Pokédex numbers a single cartridge cannot reach: link-trade evolutions and exclusives.

    Exclusives are derived rather than listed, so a differently generated data bundle cannot leave
    a stale table behind. A species with a non-trade source in one version and none in the others
    is exclusive, and so is everything it evolves into.
    """
    data = load('collection.json')
    evolutions = {int(sid): rows for sid, rows in data['evolutions'].items()}
    wild = {version: {int(sid) for sid, rows in sources.items()
                      if any(row['method'] != 'trade' for row in rows)}
            for version, sources in data['versions'].items()}
    exclusive = set()
    for version, species in wild.items():
        elsewhere = {sid for name, other in wild.items() if name != version for sid in other}
        exclusive |= species - elsewhere
    frontier = list(exclusive)
    while frontier:
        for step in evolutions.get(frontier.pop(), ()):
            if step['species'] not in exclusive:
                exclusive.add(step['species'])
                frontier.append(step['species'])
    numbers = {SPECIES[sid]['dex'] for sid in exclusive if sid in SPECIES}
    return frozenset(numbers | set(TRADE_EVOLUTIONS))


def display(dex: int | None, fallback: str = 'Unknown') -> str:
    return DEX_NAMES.get(dex, fallback) if dex else fallback


def _cheapest(copies, level_bar: int | None = None) -> list[Copy]:
    """One copy per species — the one a run would part with first: lowest level, earliest box."""
    best: dict[int, Copy] = {}
    for copy in sorted(copies, key=lambda c: (c.level, c.box, c.position)):
        if copy.dex is None:
            continue        # a copy the status could not map to a Pokédex number matches nothing
        if level_bar is not None and copy.level < level_bar:
            continue
        best.setdefault(copy.species, copy)
    return list(best.values())


def _offers(copies, level_bar: int) -> list[Copy]:
    """Copies worth putting on the table: the cheapest of each species, and the cheapest trained
    one, because a premium target is only paid for with something over the bar."""
    shortlist = _cheapest(copies) + _cheapest(copies, level_bar)
    return list({(copy.box, copy.position): copy for copy in shortlist}.values())


def standing(inv: Inventory, copy: Copy) -> str:
    """What this run gives up by parting with one boxed Pokémon."""
    if (copy.box, copy.position) in inv.spare_slots:
        return 'spare'
    return 'last one' if inv.held[copy.species] < 2 else 'best copy'


def _reason(us: Inventory, peer: Inventory, give: Copy, take: Copy, both_gain: bool) -> str:
    mine, theirs = us.instance.title(), peer.instance.title()
    want = f'{mine} is missing {display(take.dex, take.name)}'
    if both_gain:
        return f'{want}; {theirs} is missing {display(give.dex, give.name)}'
    return (f'{want}, which no single cartridge can reach; {theirs} takes a level '
            f'{give.level} {display(give.dex, give.name)} for it')


def _candidates(us: Inventory, peer: Inventory, level_bar: int):
    """Every swap this direction could offer, each tagged with how valuable it is.

    Offers are drawn from everything boxed, not only the spares, so a run can spend a keeper when
    a proposal needs one. `cost` keeps that a preference rather than a licence: it is the same for
    both orientations of a swap, so a spare-backed alternative always outranks the keeper version
    of the same outcome and claims the Pokémon first.

    The level bar guards whichever side receives the premium target, not just ours: letting a
    Gengar cross for a spare Rattata would price the whole board wrong.
    """
    premium = premium_dex()
    wants = [take for take in _offers(peer.tradeable, level_bar) if take.dex not in us.owned]
    gives = _offers(us.tradeable, level_bar)
    for take in wants:
        for give in gives:
            both_gain = give.dex not in peer.owned
            priced = take.dex in premium or give.dex in premium
            if not both_gain and take.dex not in premium:
                continue                            # an ordinary want buys nothing the peer has
            if take.dex in premium and give.level < level_bar:
                continue
            if give.dex in premium and take.level < level_bar:
                continue
            spends = {'give': standing(us, give), 'take': standing(peer, take)}
            cost = sum(SPENT_ORDER[what] for what in spends.values())
            # Both directions generate the same swap; preferring the one that *acquires* the
            # premium target decides which way round the board tells the story.
            yield ((not both_gain, not priced, cost, take.dex not in premium, give.level, take.dex, give.dex),
                   {'give': give.as_side(), 'take': take.as_side(),
                    'reason': _reason(us, peer, give, take, both_gain),
                    'price': 'premium' if priced else 'duplicate swap', 'spends': spends},
                   (give.instance, give.box, give.position), (take.instance, take.box, take.position))


def proposals(inventories, *, level_bar: int = PREMIUM_LEVEL, limit: int | None = None) -> list[dict]:
    """Trades the runs could agree on, most valuable first.

    Ranked so that swaps where both sides register a new species come first, then the premium
    acquisitions, then the cheapest price. Accepted greedily in that order because each entry is
    one physical Pokémon: once it is promised it cannot back a second proposal.
    """
    live = [inv for inv in inventories if inv.started and inv.reachable]
    candidates = [candidate for us in live for peer in live if us is not peer
                  for candidate in _candidates(us, peer, level_bar)]
    accepted, claimed = [], set()
    for _, proposal, give_key, take_key in sorted(candidates, key=lambda row: row[0]):
        if give_key in claimed or take_key in claimed:
            continue
        claimed.update((give_key, take_key))
        accepted.append(proposal)
        if limit and len(accepted) >= limit:
            break
    return accepted
