"""Useful exchanges with optional last-copy sharing for new Pokédex entries."""
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


def offers(inv, allow_last_copies):
    held = inv.held
    slots = inv.spare_slots
    return inv.spares + tuple(copy for copy in inv.tradeable
                             if (copy.box, copy.position) not in slots
                             and ((held[copy.species] == 1 and allow_last_copies)
                                  or (held[copy.species] > 1 and copy.trade_preference == 'offered')))


def listings(inv, allow_last_copies=False):
    eligible = {(mon.box, mon.position) for mon in offers(inv, allow_last_copies)}
    tradeable = {(mon.box, mon.position) for mon in inv.tradeable}
    rows = []
    for mon in inv.stored:
        slot = (mon.box, mon.position)
        reason = ('Locked against trading and automatic release' if mon.trade_preference == 'locked' else
                  'Withdrawn by you' if mon.trade_preference == 'withdrawn' else
                  'Individual identity is ambiguous' if mon.trade_ambiguous else
                  'Protected by the current project or trade policy' if slot not in tradeable else
                  'Last copy is protected' if inv.held[mon.species] == 1 and not allow_last_copies else
                  'Kept by automatic selection' if slot not in eligible else '')
        rows.append({**mon.as_side(), 'preference': mon.trade_preference,
                     'locked': mon.trade_preference == 'locked',
                     'listed': slot in eligible, 'reason': reason,
                     'can_offer': slot in tradeable and (inv.held[mon.species] > 1 or allow_last_copies)
                     or mon.trade_preference == 'withdrawn',
                     'editable': bool(mon.trade_key) and not mon.trade_ambiguous,
                     'source': 'Selected by you' if mon.trade_preference == 'offered' else 'Automatic'})
    for mon in inv.party:
        rows.append({**mon, 'box': 0, 'position': mon.get('slot'), 'listed': False,
                     'locked': mon.get('trade_preference') == 'locked',
                     'preference': mon.get('trade_preference', 'auto'), 'source': 'Selected by you',
                     'reason': 'Locked against trading and automatic release' if mon.get('trade_preference') == 'locked' else 'Active party is protected',
                     'editable': bool(mon.get('trade_key'))
                     and not mon.get('trade_ambiguous')})
    return rows


def proposals(inventories, limit=12, allow_last_copies=False):
    live = [inv for inv in inventories if inv.started and inv.reachable]
    candidates = []
    for i, us in enumerate(live):
        for peer in live[i + 1:]:
            for give in offers(us, allow_last_copies):
                for take in offers(peer, allow_last_copies):
                    mine, reason_mine = benefit(us, take)
                    theirs, reason_theirs = benefit(peer, give)
                    if not mine and not theirs:
                        continue
                    last_give = us.held[give.species] == 1
                    last_take = peer.held[take.species] == 1
                    # A unique partner can travel for a new registration, never for repeated
                    # restoration or quality upgrades after both peers already know it.
                    if (last_give and theirs < 100) or (last_take and mine < 100):
                        continue
                    selected_by_user = sum(mon.trade_preference == 'offered' for mon in (give, take))
                    score = (mine + theirs, bool(mine and theirs), selected_by_user,
                             -(last_give + last_take), -(give.level + take.level))
                    candidates.append((score, {'give': give.as_side(), 'take': take.as_side(),
                        'reason': '. '.join(r for r in [reason_mine, reason_theirs] if r),
                        'price': 'trusted exchange',
                        'spends': {'give': 'last one' if last_give else 'spare' if (give.box, give.position) in us.spare_slots else 'best copy',
                                   'take': 'last one' if last_take else 'spare' if (take.box, take.position) in peer.spare_slots else 'best copy'}}))
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
