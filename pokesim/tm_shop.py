"""Champion TM catalogue and conservative, recipient-specific shopping plans."""
import hashlib

from .battle_power import battle_power, best_replacement, moveset_score
from .policies.battle import HM_MOVES
from .policies.collection import champion
from .strategy_data import MAPS, MOVES, SPECIES

# The twelve renewable cartridge TMs keep their original shops and prices.
RENEWABLE = {1, 2, 5, 7, 9, 15, 17, 23, 32, 33, 37, 50}
LIMITED = frozenset(200 + number for number in range(1, 51) if number not in RENEWABLE)
PREMIUM = {6, 8, 13, 14, 24, 26, 28, 29, 38}
STANDARD = {3, 19, 21, 22, 25, 41, 44, 45, 48}
PRICES = {item: 50000 if item - 200 in PREMIUM else 25000 if item - 200 in STANDARD else 10000
          for item in LIMITED}
RESERVE = 20000
# Leave one cartridge bag slot for story items and other pickups.
PURCHASE_BAG_LIMIT = 19
MIN_LEVEL = 50
COUNTER = (MAPS['CELADON_MART_2F'], 6, 5)


def cartridge_data(rom):
    """Read compatibility from verified cartridges, including older data bundles."""
    from .catches import TRACKED
    if hashlib.sha1(rom).hexdigest() not in TRACKED:
        return {}, {}
    # The move table ends with the five HMs. Verify all preceding move IDs too.
    suffix = bytes((15, 19, 57, 70, 148))
    ends = [i for i in range(50, len(rom)) if rom[i:i + 5] == suffix
            and all(mid in MOVES for mid in rom[i - 50:i])]
    if len(ends) != 1:
        raise ValueError('The cartridge TM move table could not be verified')
    moves = {201 + i: mid for i, mid in enumerate(rom[ends[0] - 50:ends[0]])}
    compatible = {}
    for sid, mon in SPECIES.items():
        prefix = bytes((mon['dex'], *mon['stats'], *mon['types'], mon['catch_rate']))
        start = rom.find(prefix)
        if start < 0 or rom.find(prefix, start + 1) >= 0:
            raise ValueError('The cartridge TM compatibility table could not be verified')
        flags = int.from_bytes(rom[start + 20:start + 27], 'little')
        if {mid for i, mid in enumerate(suffix, 50) if flags & (1 << i)} != set(mon['hms']):
            raise ValueError('The cartridge HM compatibility disagrees with the reference data')
        compatible[sid] = frozenset(item for item in moves if flags & (1 << (item - 201)))
    return moves, compatible


def signature(mon):
    return (mon.species, mon.trainer_id, tuple(mon.dvs), mon.nick)


def improvement(mon, item, moves, compatible):
    mid = moves.get(item)
    if (item not in LIMITED or item not in compatible.get(mon.species, ()) or not mid
            or mon.level < MIN_LEVEL or mon.hp <= 0 or mon.status):
        return None
    # Save finite original copies when this partner will learn the same move naturally.
    if any(level > mon.level and move == mid for level, move in SPECIES[mon.species].get('learnset', ())):
        return None
    slot = best_replacement(mon, mid, HM_MOVES)
    if slot is None:
        return None
    baseline = moveset_score(mon)
    new = list(mon.moves)
    new[slot] = mid
    gain = moveset_score(mon, new) - baseline
    return gain if gain > max(1, baseline * 0.08) else None


def projected_upgrade(mon, item, moves, compatible):
    """Value the actual planned replacement at level 100, preserving this partner's DVs."""
    current_gain = improvement(mon, item, moves, compatible)
    if current_gain is None:
        return None
    slot = best_replacement(mon, moves[item], HM_MOVES)
    projected = {'species': mon.species, 'level': 100, 'dvs': mon.dvs,
                 'stat_exp': (65535,) * 5, 'moves': mon.moves}
    before = battle_power(projected)
    if before is None:
        return None
    changed = list(mon.moves)
    changed[slot] = moves[item]
    after = battle_power({**projected, 'moves': changed})
    gain = after - before
    if gain <= max(1, before * 0.08):
        return None
    return {'before': before, 'after': after, 'gain': gain, 'current_gain': current_gain}


def choose(snapshot, moves, compatible, *, owned):
    """Greedily choose the largest mature Battle Power gain, one upgrade at a time."""
    if not champion(snapshot):
        return None
    bag = dict(snapshot.items)
    options = []
    for item in sorted(LIMITED):
        if bool(bag.get(item)) != owned:
            continue
        if not owned and (len(bag) >= PURCHASE_BAG_LIMIT or snapshot.money < PRICES[item] + RESERVE):
            continue
        for index, mon in enumerate(snapshot.party):
            upgrade = projected_upgrade(mon, item, moves, compatible)
            if upgrade is not None:
                options.append((upgrade['gain'], upgrade['current_gain'], -PRICES[item], -index, -item))
    if not options:
        return None
    _, _, _, index, item = max(options)
    index, item = -index, -item
    return {'item': item, 'target': index, 'signature': signature(snapshot.party[index])}


def valid_plan(snapshot, plan, moves, compatible, offers=()):
    if plan and plan.get("supply"):
        from .champion_shop import valid_plan as valid_supply
        return valid_supply(snapshot, plan, offers)
    if not plan or not champion(snapshot):
        return False
    index, item = plan['target'], plan['item']
    return (0 <= index < len(snapshot.party) and signature(snapshot.party[index]) == plan['signature']
            and projected_upgrade(snapshot.party[index], item, moves, compatible) is not None
            and (dict(snapshot.items).get(item) or len(snapshot.items) < PURCHASE_BAG_LIMIT
                 and snapshot.money >= PRICES[item] + RESERVE))


def label(item, moves):
    name = MOVES[moves[item]]['name'].replace('_M', '').replace('_', ' ').title()
    return f'TM{item - 200:02d} {name}'
