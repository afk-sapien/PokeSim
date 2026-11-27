"""Champion TM catalogue and conservative, recipient-specific shopping plans."""
import hashlib

from .battle_power import battle_power, best_replacement, moveset_score
from .policies.battle import HM_MOVES
from .policies.collection import champion
from .strategy_data import MAPS, MOVES, SPECIES, WORLD, event_set

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
# A League win pays ₽29,799 in Red, Blue and Yellow, measured on 30 wins: 99 for each level of the
# five rooms' last foes (56, 58, 60, 62 and 65).
LEAGUE_PRIZE = 29799
# A TM waits while a better one for the same partner and move slot is on sale and the purse would reach
# it within this many League wins.
SAVE_WINS = 1
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
    return {'before': before, 'after': after, 'gain': gain, 'current_gain': current_gain, 'slot': slot}


def choose(snapshot, moves, compatible, *, owned, skip=()):
    """Greedily choose the largest mature Battle Power gain, one upgrade at a time.

    ``skip`` lists the items left out, such as a purchase standing down. The plan carries the
    partner's battle power at level 100 ``before`` and ``after`` the move, which the move is worth.

    A purchase saves for the best TM: it waits while a better TM for the same partner and move slot is
    on sale and the purse would cover it within ``SAVE_WINS`` League wins.
    """
    if not champion(snapshot):
        return None
    bag = dict(snapshot.items)
    options, best = [], {}
    for item in sorted(LIMITED):
        if bool(bag.get(item)) != owned or item in skip:
            continue
        cost = 0 if owned else PRICES[item] + RESERVE
        if not owned and (len(bag) >= PURCHASE_BAG_LIMIT or snapshot.money + SAVE_WINS * LEAGUE_PRIZE < cost):
            continue
        for index, mon in enumerate(snapshot.party):
            upgrade = projected_upgrade(mon, item, moves, compatible)
            if upgrade is None:
                continue
            key = index, upgrade['slot']
            best[key] = max(best.get(key, 0), upgrade['gain'])
            if snapshot.money >= cost:
                options.append((key, (upgrade['gain'], upgrade['current_gain'], -PRICES[item], -index, -item,
                                      upgrade['before'], upgrade['after'])))
    options = [option for key, option in options if option[0] >= best[key]]
    if not options:
        return None
    _, _, _, index, item, before, after = max(options)
    index, item = -index, -item
    return {'item': item, 'target': index, 'signature': signature(snapshot.party[index]),
            'before': before, 'after': after}


# Each ball on the ground that holds a TM, as (map, object index, text label), from the world data. The
# label names the move, as TEXT_SILPHCO10F_TM_EARTHQUAKE does.
GROUND = tuple((m, index, obj[4]) for m, world in WORLD.items() for index, obj in enumerate(world.get('objects', ()))
               if obj[2] == 'SPRITE_POKE_BALL' and '_TM_' in obj[4])
# The S.S. Anne sails once its captain is helped and never docks again, so a ball left on board is gone.
SHIP = frozenset(m for name, m in MAPS.items() if name.startswith('SS_ANNE'))


def on_ground(snapshot, place):
    """Whether the ball at ``place``, a plan's ``ground`` (map, object index, text label), is still there."""
    if place[0] in SHIP and event_set(snapshot.event_flags, 'EVENT_SS_ANNE_LEFT'):
        return False
    # The pickups module reaches this one through the ledger, so it is read here, when first needed.
    from .policies.pickups import Pickups
    return Pickups.hidden(snapshot, {'map': place[0], 'object': place[1]}) is False


def ground(snapshot, moves, compatible, *, skip=()):
    """The best TM a ball still on the ground holds, chosen as ``choose`` chooses a purchase, as its plan
    with the ball's ``ground`` place (map, object index, text label), or None. The TM is free, so the
    purse does not limit it, and the bag keeps the slot a purchase keeps."""
    if not champion(snapshot):
        return None
    bag = dict(snapshot.items)
    if len(bag) >= PURCHASE_BAG_LIMIT:
        return None
    by_name = {MOVES[mid]['name']: item for item, mid in moves.items()}
    options = []
    for place in GROUND:
        move = place[2].removeprefix('TEXT_').partition('_TM_')[2]
        # A few move names end in _M where the label does not, as PSYCHIC_M does.
        item = by_name.get(move) or by_name.get(move + '_M')
        if item is None or item in skip or bag.get(item) or not on_ground(snapshot, place):
            continue
        for index, mon in enumerate(snapshot.party):
            upgrade = projected_upgrade(mon, item, moves, compatible)
            if upgrade is not None:
                options.append((upgrade['gain'], upgrade['current_gain'], -index, -item,
                                upgrade['before'], upgrade['after'], place))
    if not options:
        return None
    _, _, index, item, before, after, place = max(options)
    index, item = -index, -item
    return {'item': item, 'target': index, 'signature': signature(snapshot.party[index]),
            'before': before, 'after': after, 'ground': place}


def valid_plan(snapshot, plan, moves, compatible, offers=()):
    if plan and plan.get("supply"):
        from .champion_shop import valid_plan as valid_supply
        return valid_supply(snapshot, plan, offers)
    if not plan or not champion(snapshot):
        return False
    index, item = plan['target'], plan['item']
    # A ball on the ground is free, and a purchase needs the price and the reserve.
    reachable = len(snapshot.items) < PURCHASE_BAG_LIMIT and (
        on_ground(snapshot, plan['ground']) if plan.get('ground') else snapshot.money >= PRICES[item] + RESERVE)
    return (0 <= index < len(snapshot.party) and signature(snapshot.party[index]) == plan['signature']
            and projected_upgrade(snapshot.party[index], item, moves, compatible) is not None
            and (dict(snapshot.items).get(item) or reachable))


def label(item, moves):
    name = MOVES[moves[item]]['name'].replace('_M', '').replace('_', ' ').title()
    return f'TM{item - 200:02d} {name}'
