"""Generation I battle estimates and resource decisions.

Damage scores are estimates, not an exhaustive battle simulator. They use the
live battle stats, Generation I type categories, accuracy, and special effects.
"""
from dataclasses import dataclass

from ..ram import PartyMon
from ..strategy_data import ITEMS, MATCHUPS, MOVES, PRICES, SPECIES

W_BATTLE_MON = 0xD014
W_ENEMY_MON = 0xCFE5
W_PLAYER_DISABLED_MOVE = 0xD06D
BALLS = (ITEMS["POKE_BALL"], ITEMS["GREAT_BALL"], ITEMS["ULTRA_BALL"])
HM_MOVES = {15, 19, 57, 70, 148}
HEALING = {ITEMS["POTION"]: 20, ITEMS["SUPER_POTION"]: 50, ITEMS["HYPER_POTION"]: 200,
           ITEMS["MAX_POTION"]: 999, ITEMS["FULL_RESTORE"]: 999,
           ITEMS["FRESH_WATER"]: 50, ITEMS["SODA_POP"]: 60, ITEMS["LEMONADE"]: 80}
CURES = {ITEMS["ANTIDOTE"]: 8, ITEMS["BURN_HEAL"]: 16, ITEMS["ICE_HEAL"]: 32,
         ITEMS["AWAKENING"]: 7, ITEMS["PARLYZ_HEAL"]: 64, ITEMS["FULL_HEAL"]: 127, ITEMS["FULL_RESTORE"]: 127}


def read_battler(mem, base):
    b = bytes(mem[base:base + 29])
    word = lambda i: int.from_bytes(b[i:i + 2], "big")
    pp = [v & 63 for v in b[25:29]]
    if base == W_BATTLE_MON:
        # The upper nibble is a one-based move slot, the lower nibble counts turns.
        disabled = (mem[W_PLAYER_DISABLED_MOVE] >> 4) - 1
        if 0 <= disabled < len(pp):
            pp[disabled] = 0
    return PartyMon(b[0], word(1), word(15), b[14], "", b[4], (b[5], b[6]),
                    tuple(b[8:12]), tuple(pp), word(17), word(19), word(21), word(23))


def effectiveness(move_type, defender_types):
    factor = 1.0
    for typ in set(defender_types):
        factor *= MATCHUPS.get((move_type, typ), 1.0)
    return factor


def damage(move_id, attacker, defender):
    """Expected connected-hit damage before accuracy, including common special moves."""
    move = MOVES.get(move_id)
    if not move or not move["power"]:
        return 0.0
    name, effect = move["name"], move["effect"]
    if name in ("SEISMIC_TOSS", "NIGHT_SHADE"):
        return float(attacker.level)
    factor = effectiveness(move["type"], defender.types)
    if not factor:
        return 0.0
    if name in ("SONICBOOM", "DRAGON_RAGE"):
        return 20.0 if name == "SONICBOOM" else 40.0
    if name == "SUPER_FANG":
        return float(max(1, defender.hp // 2))
    if name == "PSYWAVE":
        return max(1.0, attacker.level * 0.75)
    if effect == "OHKO_EFFECT":
        return float(defender.hp) if attacker.speed >= defender.speed else 0.0
    if effect in ("COUNTER_EFFECT", "BIDE_EFFECT"):
        return 0.0
    physical = move["type"] < 20
    attack = attacker.attack if physical else attacker.special
    defense = defender.defense if physical else defender.special
    if effect == "EXPLODE_EFFECT":
        defense = max(1, defense // 2)
    power = move["power"]
    raw = ((2 * attacker.level // 5 + 2) * power * max(1, attack) // max(1, defense)) // 50 + 2
    raw *= 1.5 if move["type"] in attacker.types else 1
    raw *= factor * 0.925
    # Generation I uses species base Speed and gives these moves a much higher critical rate.
    base_speed = SPECIES.get(attacker.species, {}).get("stats", [0, 0, 0, attacker.speed])[3]
    threshold = base_speed // 2
    if name in ("RAZOR_LEAF", "SLASH", "CRABHAMMER", "KARATE_CHOP"):
        threshold *= 8
    critical_chance = min(255, threshold) / 256
    critical_multiplier = (4 * attacker.level // 5 + 2) / max(1, 2 * attacker.level // 5 + 2)
    raw *= 1 + critical_chance * (critical_multiplier - 1)
    if effect in ("ATTACK_TWICE_EFFECT", "TWINEEDLE_EFFECT"):
        raw *= 2
    elif effect == "TWO_TO_FIVE_ATTACKS_EFFECT":
        raw *= 3
    return raw


def move_score(move_id, attacker, defender, used_status=()):
    move = MOVES.get(move_id)
    if not move:
        return -1.0
    accuracy = min(255, move["accuracy"] * 255 // 100) / 256
    connected = damage(move_id, attacker, defender)
    if connected:
        score = min(connected, defender.hp) * accuracy
        if connected >= defender.hp:
            score += defender.hp * accuracy * 0.35
        if move["effect"] in ("CHARGE_EFFECT", "FLY_EFFECT", "CHARGE_ATTACK_EFFECT") or move["name"] == "DIG":
            score *= 0.55
        if move["effect"] == "RECHARGE_EFFECT" and connected < defender.hp:
            score *= 0.6
        if move["effect"] == "RECOIL_EFFECT":
            score -= min(connected, defender.hp) * 0.25
        if move["effect"] == "EXPLODE_EFFECT":
            score -= attacker.hp * 1.5
        return score
    if move_id in used_status:
        return -0.5
    effect = move["effect"]
    if effect in ("SLEEP_EFFECT", "PARALYZE_EFFECT", "POISON_EFFECT", "TOXIC_EFFECT"):
        if defender.status or not effectiveness(move["type"], defender.types):
            return -0.5
        if effect in ("POISON_EFFECT", "TOXIC_EFFECT") and 3 in defender.types:
            return -0.5
        return min(defender.hp * 0.25, 15) * accuracy
    if effect == "HEAL_EFFECT" and attacker.hp < attacker.max_hp * 0.5:
        return (attacker.max_hp - attacker.hp) * 0.65
    if effect.endswith(("UP1_EFFECT", "UP2_EFFECT", "DOWN1_EFFECT", "DOWN2_EFFECT")):
        return 2.0 if defender.hp > 15 else 0.0
    return -0.25


def ranked_moves(me, enemy, used_status=()):
    return sorted([(move_score(mid, me, enemy, used_status), slot) for slot, (mid, pp)
                   in enumerate(zip(me.moves, me.pp)) if mid and pp], reverse=True)


def replacement_slot(mon, new_move):
    """Keep HMs and score coverage as well as power when replacing a move."""
    def value(mid):
        move = MOVES.get(mid, {})
        power = move.get("power", 0)
        value = power * move.get("accuracy", 100) / 100 * (1.5 if move.get("type") in mon.types else 1)
        if move.get('name') in ('RAZOR_LEAF', 'SLASH', 'CRABHAMMER', 'KARATE_CHOP'):
            value *= 1.7
        if move.get('effect') in ('CHARGE_EFFECT', 'FLY_EFFECT', 'CHARGE_ATTACK_EFFECT', 'RECHARGE_EFFECT'):
            value *= 0.6
        if move.get('effect') == 'EXPLODE_EFFECT':
            value *= 0.35
        if not power:
            value = 40 if move.get('effect') in ('SLEEP_EFFECT', 'HEAL_EFFECT', 'LEECH_SEED_EFFECT', 'PARALYZE_EFFECT') else 8
        return value
    choices = [(value(mid), slot) for slot, mid in enumerate(mon.moves) if mid not in HM_MOVES]
    if not choices or new_move not in MOVES or new_move in mon.moves:
        return None
    def moveset_value(moves):
        scores = {}
        utility = 0
        for mid in moves:
            m = MOVES.get(mid, {})
            if m.get('power'):
                scores.setdefault(m['type'], []).append(value(mid))
            else:
                utility += value(mid)
        return sum(max(v) + 0.2 * (sum(v) - max(v)) for v in scores.values()) + utility
    slot = max((k for _, k in choices), key=lambda k: moveset_value(tuple(new_move if j == k else mid for j, mid in enumerate(mon.moves))))
    improved = moveset_value(tuple(new_move if j == slot else mid for j, mid in enumerate(mon.moves)))
    return slot if new_move in HM_MOVES or improved > moveset_value(mon.moves) + 5 else None


def needs_healing(party):
    if not party:
        return False
    available = sum(pp for p in party if p.hp for mid, pp in zip(p.moves, p.pp) if MOVES.get(mid, {}).get("power", 0))
    maximum = sum(MOVES.get(mid, {}).get("pp", 0) for p in party if p.hp for mid in p.moves if MOVES.get(mid, {}).get("power", 0))
    lead = party[0]
    lead_pp = sum(pp for mid, pp in zip(lead.moves, lead.pp) if MOVES.get(mid, {}).get("power", 0))
    return ((lead_pp < 2 and any(MOVES.get(mid, {}).get("power",0) for mid in lead.moves)) or any(p.hp == 0 or p.status for p in party)
            or sum(p.hp for p in party) < sum(p.max_hp for p in party) * 0.55
            or available < max(3, maximum * 0.15))


def healing_item(items, mon, incoming=0):
    if mon.hp <= 0:
        return None
    missing = mon.max_hp - mon.hp
    choices = []
    for index, (item, qty) in enumerate(items):
        if qty <= 0:
            continue
        if mon.status & CURES.get(item, 0):
            choices.append((PRICES.get(item, 1000), index))
        amount = HEALING.get(item, 0)
        if missing >= 10 and min(missing, amount) > incoming and mon.hp < mon.max_hp * 0.4:
            choices.append((PRICES.get(item, 1000) + max(0, amount - missing), index))
    return min(choices)[1] if choices else None


def shopping_item(items, stock, money, league=False, collecting=False):
    counts = dict(items)
    desired = {ITEMS["POKE_BALL"]: 5, ITEMS["POTION"]: 3, ITEMS["SUPER_POTION"]: 3,
               ITEMS["ANTIDOTE"]: 2, ITEMS["PARLYZ_HEAL"]: 1}
    if league:
        desired[ITEMS["REVIVE"]] = 5
    ball_count = sum(counts.get(i, 0) for i in BALLS)
    heal_count = sum(counts.get(i, 0) for i in HEALING)
    order = sorted(stock, key=lambda item: (item != ITEMS["REVIVE"],
                   item != ITEMS["HYPER_POTION"])) if league else stock
    for item in order:
        target = desired.get(item, 0)
        if item in BALLS:
            target = max(0, (15 if collecting else 5) - ball_count + counts.get(item, 0))
        if item in HEALING:
            target = max(0, (10 if league else 3) - heal_count + counts.get(item, 0))
        if counts.get(item, 0) >= target or (len(items) >= (20 if league else 18) and item not in counts):
            continue
        if 0 < PRICES.get(item, 0) <= money - 300:
            return item
    return None


@dataclass(frozen=True)
class Decision:
    kind: str
    index: int = 0
    target: int = 0
    reason: str = ""


def choose_battle(snapshot, me, enemy, active, used_status=(), can_switch=True, catch_attempts=0, required_move=None, collect_missing=False):
    moves = ranked_moves(me, enemy, used_status)
    slot = moves[0][1] if moves else 0
    incoming = max((damage(mid, enemy, me) for mid in enemy.moves if mid), default=me.max_hp * 0.2)
    known = SPECIES.get(enemy.species, {})
    missing_species = known.get("dex") not in snapshot.owned
    coverage = set(enemy.types) - {t for p in snapshot.party for t in p.types}
    required = required_move in known.get('hms', []) if required_move else False
    useful = required or (missing_species and (len(snapshot.party) < 3 or enemy.level >= max((p.level for p in snapshot.party), default=1) * 0.4)) or bool(coverage and enemy.level >= me.level * 0.5)
    safe = me.hp > incoming * 1.5 and not me.status
    balls = [(i, item) for item in BALLS for i, (bag_item, qty) in enumerate(snapshot.items) if bag_item == item and qty > 0]
    legendary = known.get('dex') in (144,145,146,150)
    collection_target = collect_missing and missing_species
    capture_limit = 10000 if legendary else 20
    master = next((i for i,(item,qty) in enumerate(snapshot.items) if item==ITEMS['MASTER_BALL'] and qty),None)
    if snapshot.in_battle == 1 and snapshot.battle_type == 0 and snapshot.can_catch and collection_target and catch_attempts < capture_limit and (balls or legendary and master is not None):
        if legendary and master is not None:
            return Decision('item',master,reason='Secure the missing legendary with the Master Ball')
        healing = healing_item(snapshot.items,me,incoming)
        if me.hp <= incoming * 1.5 and healing is not None:
            return Decision('item',healing,active,'Keep the catcher healthy while preserving the wild Pokémon')
        status_moves = [(MOVES[mid]['accuracy'],i) for i,(mid,pp) in enumerate(zip(me.moves,me.pp))
                        if pp and mid not in used_status and MOVES.get(mid,{}).get('effect') in ('SLEEP_EFFECT','PARALYZE_EFFECT')
                        and effectiveness(MOVES[mid]['type'],enemy.types)]
        if not enemy.status and status_moves and me.hp > incoming:
            return Decision('fight',max(status_moves)[1],reason='Use sleep or paralysis to help the catch')
        if can_switch and not enemy.status and not status_moves:
            catchers = [(p.hp,i) for i,p in enumerate(snapshot.party) if i!=active and p.hp>p.max_hp*0.7 and not p.status
                        and any(pp and MOVES.get(mid,{}).get('effect') in ('SLEEP_EFFECT','PARALYZE_EFFECT')
                                and effectiveness(MOVES[mid]['type'],enemy.types) for mid,pp in zip(p.moves,p.pp))
                        and p.hp > 2 * max((damage(mid,enemy,p) for mid in enemy.moves),default=0)]
            if catchers:
                return Decision('switch',max(catchers)[1],reason='Bring in a healthy catcher with sleep or paralysis')
        weakening = [(score,i) for score,i in moves if MOVES[me.moves[i]]['effect'] not in
                     ('EXPLODE_EFFECT','RECOIL_EFFECT','OHKO_EFFECT','TWO_TO_FIVE_ATTACKS_EFFECT')
                     and 0 < damage(me.moves[i],me,enemy) * 2.5 < enemy.hp]
        if enemy.hp > enemy.max_hp*0.4 and weakening and not enemy.status:
            return Decision('fight',max(weakening)[1],reason='Use a gentle attack with a margin for critical damage')
        return Decision('item',balls[-1][0],reason='Catch the missing Pokédex entry without risking a knockout')
    if snapshot.in_battle == 1 and snapshot.battle_type == 0 and snapshot.can_catch and useful and balls and safe and catch_attempts < (12 if required else 5):
        if enemy.hp <= enemy.max_hp * 0.35 or enemy.status or not moves:
            ball_index = balls[-1][0] if known.get("catch_rate", 255) < 100 else balls[0][0]
            return Decision("item", ball_index, reason="Catch a missing species or improve team coverage")
        weakening = [(score, k) for score, k in moves if 0 < damage(me.moves[k], me, enemy) < enemy.hp * 0.8]
        if weakening:
            return Decision("fight", max(weakening)[1], reason="Weaken the target without an expected knockout")
        if required:
            return Decision('item', balls[0][0], reason='Catch the field-move partner without knocking it out')
    item_index = healing_item(snapshot.items, me, incoming)
    if item_index is not None:
        return Decision("item", item_index, active, "Recover HP or cure status before attacking")
    candidates = []
    if can_switch:
        for i, mon in enumerate(snapshot.party):
            if i == active or mon.hp <= 0 or mon.status & 39:
                continue
            offense = ranked_moves(mon, enemy)
            threat = max((damage(mid, enemy, mon) for mid in enemy.moves if mid), default=mon.max_hp * 0.2)
            if offense and any(damage(mid, mon, enemy) > 0 and pp for mid, pp in zip(mon.moves, mon.pp)) and mon.hp > threat * 2:
                candidates.append((offense[0][0] / max(1, threat), i))
    current_ratio = (moves[0][0] if moves else 0) / max(1, incoming)
    if candidates and (me.hp <= incoming or not moves or max(candidates)[0] > current_ratio * 2.5):
        return Decision("switch", max(candidates)[1], reason="Bring in a healthier Pokémon with a better matchup")
    if snapshot.in_battle == 1 and (not moves or me.hp <= incoming) and not candidates:
        return Decision("run", reason="Avoid a likely blackout in a wild encounter")
    return Decision("fight", slot, reason="Choose the strongest expected outcome from moves with PP")
