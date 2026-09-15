"""Useful exchanges between trusted peers, using only expendable boxed partners."""
from ..strategy_data import SPECIES
from ..ram import DEX_NAMES
from ..policies.collection import EVOS

EVOLVES = {sid: row['species'] for sid, rows in EVOS.items() for row in rows if row['method'] == 'trade'}


def benefit(inv, incoming):
    arrived = EVOLVES.get(incoming.species, incoming.species)
    dex = SPECIES[arrived]['dex']
    new = {incoming.dex, dex} - inv.owned - {None}
    if new:
        return 100 * len(new), f"{inv.instance.title()} registers {' and '.join(DEX_NAMES[n] for n in sorted(new))}"
    copies = [p for p in inv.party if p['species'] == arrived]
    copies += [p.as_side() for p in inv.stored if p.species == arrived]
    if not copies:
        return 20, f'{inv.instance.title()} restores a missing collection partner'
    best_level = max(p['level'] for p in copies)
    if incoming.level >= best_level + 5:
        return 10, f'{inv.instance.title()} gains a partner at least five levels stronger'
    if incoming.level >= best_level - 5 and len(incoming.dvs) == 5:
        known = [sum(p['dvs']) for p in copies if len(p.get('dvs', ())) == 5]
        if len(known) == len(copies) and sum(incoming.dvs) >= max(known) + 4:
            return 5, f'{inv.instance.title()} improves total DVs by at least four'
    if incoming.level >= best_level and len(incoming.stat_exp) == 5:
        known = [sum(p['stat_exp']) for p in copies if len(p.get('stat_exp', ())) == 5]
        if len(known) == len(copies) and sum(incoming.stat_exp) >= max(known) + 20000:
            return 5, f'{inv.instance.title()} gains at least 20,000 stat experience'
    return 0, ''


def proposals(inventories, limit=12):
    live = [inv for inv in inventories if inv.started and inv.reachable]
    candidates = []
    for i, us in enumerate(live):
        for peer in live[i + 1:]:
            for give in us.spares:
                for take in peer.spares:
                    mine, reason_mine = benefit(us, take)
                    theirs, reason_theirs = benefit(peer, give)
                    if not mine and not theirs:
                        continue
                    score = (mine + theirs, bool(mine and theirs), -(give.level + take.level))
                    candidates.append((score, {'give': give.as_side(), 'take': take.as_side(),
                        'reason': '. '.join(r for r in [reason_mine, reason_theirs] if r),
                        'price': 'trusted exchange', 'spends': {'give': 'spare', 'take': 'spare'}}))
    selected, claimed, outcomes = [], set(), set()
    for _, proposal in sorted(candidates, key=lambda row: row[0], reverse=True):
        sides = [proposal[k] for k in ['give', 'take']]
        keys = {(s['instance'], s['box'], s['position']) for s in sides}
        outcome = tuple((s['instance'], s['species']) for s in sides)
        if keys & claimed or outcome in outcomes:
            continue
        selected.append(proposal)
        claimed.update(keys)
        outcomes.add(outcome)
        if len(selected) >= limit:
            break
    return selected
