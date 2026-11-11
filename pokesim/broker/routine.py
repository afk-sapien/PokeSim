"""Useful exchanges with optional last-copy sharing for new Pokédex entries."""
from ..strategy_data import SPECIES
from ..shiny import is_shiny
from ..milestones import is_perfect
from ..ram import DEX_NAMES
from ..trade.preferences import name as setting_name
from ..trade.worth import gain, why
from ..policies.collection import EVOS

EVOLVES = {sid: row['species'] for sid, rows in EVOS.items() for row in rows if row['method'] == 'trade'}


def benefit(inv, incoming):
    """What ``incoming`` is worth to ``inv`` (trade/worth.py), as (points, reason)."""
    side = {**incoming.as_side(), 'arrived_dex': SPECIES[EVOLVES.get(incoming.species, incoming.species)]['dex']}
    payload = {'owned': inv.owned, 'version': inv.version, 'party': list(inv.party),
               'storage': {'pokemon': [{**copy.as_side(), 'trade_preference': copy.trade_preference}
                                       for copy in inv.stored]}}
    found = gain(payload, side)
    species = ' and '.join(DEX_NAMES[dex] for dex in found.new) or DEX_NAMES.get(side['arrived_dex'], incoming.label)
    return found.points, why(inv.instance.title(), species, found)


def offers(inv, allow_last_copies):
    """Boxed copies this run can trade away: its spares, which include the copies kept for a peer
    that lacks the species (trade/worth.py), the last copy of a species when ``allow_last_copies``,
    and copies set to Prefer to trade while another copy stays behind."""
    held = inv.held
    slots = inv.spare_slots
    return inv.spares + tuple(copy for copy in inv.tradeable
                             if (copy.box, copy.position) not in slots
                             and ((held[copy.species] == 1 and allow_last_copies)
                                  or (held[copy.species] > 1 and copy.trade_preference == 'offered')))


def listings(inv, allow_last_copies=False):
    """Every party and boxed Pokémon with its trade setting, for the Trading page's per-Pokémon list."""
    rows = []
    for mon in inv.stored:
        rows.append({**mon.as_side(), 'shiny': is_shiny(mon.as_side()), 'perfect_dvs': is_perfect(mon.as_side()),
                     'preference': mon.trade_preference, 'setting': setting_name(mon.trade_preference),
                     'editable': bool(mon.trade_key) and not mon.trade_ambiguous})
    for mon in inv.party:
        preference = mon.get('trade_preference', 'auto')
        rows.append({**mon, 'box': 0, 'position': mon.get('slot'), 'preference': preference,
                     'setting': setting_name(preference),
                     'editable': bool(mon.get('trade_key')) and not mon.get('trade_ambiguous')})
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
