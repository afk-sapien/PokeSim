"""Generation I battle estimates and resource decisions.

Damage scores are estimates, not an exhaustive battle simulator. They use the
live battle stats, Generation I type categories, accuracy, and special effects.
"""
from dataclasses import dataclass, replace

from pokecore.dvs import hp_dv

from ..planning.stance import FLEE, HUNT, STORY, TRAVEL, Encounter, stance
from ..planning.throws import THROW_BAR, gen1_throw
from ..ram import PartyMon
from ..strategy_data import ITEMS, MAPS, MATCHUPS, MOVES, PRICES, SPECIES

from pokecore.gen1 import BIT_TRANSFORMED, W_BATTLE_MON, W_ENEMY_MON, W_ENEMY_SPECIES2, W_PLAYER_DISABLED_MOVE
from pokecore.gen1 import W_ENEMY_BATTLE_STATUS3 as W_ENEMY_STATUS3

TRANSFORMED = 1 << BIT_TRANSFORMED
BALLS = (ITEMS["POKE_BALL"], ITEMS["GREAT_BALL"], ITEMS["ULTRA_BALL"])
# Attacks a catch never weakens with: they cost the user, knock out at once, or hit too often to judge.
RISKY_CHIPS = ('EXPLODE_EFFECT', 'RECOIL_EFFECT', 'OHKO_EFFECT', 'TWO_TO_FIVE_ATTACKS_EFFECT')
# Balls a hunt stocks while the purse stays above funds_needed. Postgame hunts on three Red saves threw
# about five Ultra Balls a catch, so the collecting 15 sent them to a mart after every catch.
HUNT_STOCK = 30
HM_MOVES = {15, 19, 57, 70, 148}
FROZEN = 32
# Poison and burn wear a foe down every turn. Asleep is bits 0 to 2.
WEARING = 8 | 16
ASLEEP_OR_FROZEN = 7 | FROZEN
# The game's attack once every move is out of PP: Normal, so it cannot touch a Ghost.
STRUGGLE = 165
HOPELESS = 'Nobody here can act and this foe never attacks, so only an earlier save ends the battle'
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
    # Transform copies the player's species over the foe's, and species2 keeps the one that was met.
    species = mem[W_ENEMY_SPECIES2] if base == W_ENEMY_MON and mem[W_ENEMY_STATUS3] & TRANSFORMED else b[0]
    return PartyMon(species, word(1), word(15), b[14], "", b[4], (b[5], b[6]),
                    tuple(b[8:12]), tuple(pp), word(17), word(19), word(21), word(23))


def enemy_dvs(mem):
    """The wild Pokémon's DVs, ordered HP, Attack, Defense, Speed, Special as stored copies are."""
    attack, defense = mem[W_ENEMY_MON + 12] >> 4, mem[W_ENEMY_MON + 12] & 15
    speed, special = mem[W_ENEMY_MON + 13] >> 4, mem[W_ENEMY_MON + 13] & 15
    return (hp_dv(attack, defense, speed, special), attack, defense, speed, special)


def effectiveness(move_type, defender_types):
    factor = 1.0
    for typ in set(defender_types):
        factor *= MATCHUPS.get((move_type, typ), 1.0)
    return factor


def foe_never_attacks(enemy, mon):
    """True when a trainer's Pokémon will only ever use a move that does nothing.

    The trainer routine favours any move whose type is super effective, even one without power.
    Rest and Agility are Psychic, so Lorelei's Dewgong rests and Lance's Dragonair speeds up forever
    against a Poison or Fighting partner, and a partner who cannot act is never knocked out."""
    favoured = [MOVES[mid] for mid in enemy.moves if mid in MOVES and effectiveness(MOVES[mid]['type'], mon.types) > 1]
    return bool(favoured) and not any(move['power'] for move in favoured)


def hurts(mon, enemy):
    """Whether ``mon`` can wear ``enemy`` down with what it has PP for: an attack that connects, poison
    that takes, or Dream Eater behind its own sleep move. A poisoned or burned foe is worn down already.
    With every move out of PP the game uses Struggle."""
    if enemy.status & WEARING:
        return True
    usable = [mid for mid, pp in zip(mon.moves, mon.pp) if mid in MOVES and pp] or [STRUGGLE]
    sleeps = any(MOVES[mid]['effect'] == 'SLEEP_EFFECT' for mid in usable)
    for mid in usable:
        move = MOVES[mid]
        if damage(mid, mon, enemy) > 0:
            return True
        if move['effect'] == 'DREAM_EATER_EFFECT' and sleeps and effectiveness(move['type'], enemy.types):
            return True
        if move['effect'] == 'POISON_EFFECT' and not enemy.status and 3 not in enemy.types:
            return True
    return False


def spent(mon):
    """Whether a move it knows is out of PP. A Kakuna that only ever had Harden is not spent."""
    return any(mid and not pp for mid, pp in zip(mon.moves, mon.pp))


def lose_attempt(snapshot, enemy, active, slot):
    """Nobody can end the battle and this foe never knocks the battler out. A partner it does attack
    loses the attempt instead, and the blackout heals everyone at a Pokémon Center."""
    targets = [(max((damage(mid, enemy, mon) for mid in enemy.moves if mid), default=0) / mon.hp, i)
               for i, mon in enumerate(snapshot.party)
               if i != active and mon.hp > 0 and not foe_never_attacks(enemy, mon)]
    if targets:
        return Decision("switch", max(targets)[1], reason="Nobody can act, so let the foe end an attempt that cannot be won")
    return Decision("fight", slot, reason=HOPELESS)


def damage_division_safe(move_id, attacker, defender):
    """Reject attacks whose scaled defensive stat becomes a zero divisor in Gen I."""
    move = MOVES.get(move_id)
    if not move or not move['power'] or move['effect'] in ('EXPLODE_EFFECT', 'OHKO_EFFECT'):
        return True
    physical = move['type'] < 20
    attack = attacker.attack if physical else attacker.special
    defense = defender.defense if physical else defender.special
    if attack > 255 or defense > 255:
        defense = (defense >> 2) & 255
    return defense > 0


def damage(move_id, attacker, defender):
    """Expected connected-hit damage before accuracy, including common special moves."""
    move = MOVES.get(move_id)
    if not move:
        return 0.0
    name, effect = move["name"], move["effect"]
    # Night Shade's data power is 0, so the level-damage case comes before the power check.
    if name in ("SEISMIC_TOSS", "NIGHT_SHADE"):
        return float(attacker.level)
    if not move["power"]:
        return 0.0
    # Generation I Dream Eater does nothing unless the target is asleep (status bits 0-2).
    if effect == "DREAM_EATER_EFFECT" and not getattr(defender, "status", 0) & 7:
        return 0.0
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


def long_odds(rate, ball, enemy):
    """Whether one throw of ``ball`` catches ``enemy`` as it stands less than one time in ten."""
    name = ('POKE_BALL', 'GREAT_BALL', 'ULTRA_BALL')[BALLS.index(ball)]
    return gen1_throw(rate, name, enemy.hp, enemy.max_hp, enemy.status) < THROW_BAR


def ranked_moves(me, enemy, used_status=()):
    return sorted([(move_score(mid, me, enemy, used_status), slot) for slot, (mid, pp)
                   in enumerate(zip(me.moves, me.pp))
                   if mid and pp and damage_division_safe(mid, me, enemy)], reverse=True)


def replacement_slot(mon, new_move):
    """Use the actual attacking stats and coverage while preserving field moves."""
    from ..battle_power import best_replacement, moveset_score
    slot = best_replacement(mon, new_move, HM_MOVES)
    if slot is not None or new_move not in HM_MOVES or new_move in mon.moves:
        return slot
    choices = [i for i, mid in enumerate(mon.moves) if mid not in HM_MOVES]
    return min(choices, key=lambda i: moveset_score(mon, (mon.moves[i],)), default=None)


def field_cure(items, mon, league=False):
    """The cure to use on ``mon`` outside battle, the cheapest in ``items`` that clears its status, or None.

    Outside the League a Full Restore is kept for the HP it restores."""
    if not mon.hp or not mon.status:
        return None
    found = [(item in HEALING, PRICES.get(item, 1000), item) for item, qty in items
             if qty and mon.status & CURES.get(item, 0) and (league or item not in HEALING)]
    return min(found)[2] if found else None


def cured(party, items):
    """``party`` once the field cures in ``items`` clear what they can, one cure a Pokémon."""
    stock = dict(items)
    treated = []
    for mon in party:
        cure = field_cure(tuple(stock.items()), mon)
        if cure is not None:
            stock[cure] -= 1
            mon = replace(mon, status=0)
        treated.append(mon)
    return tuple(treated)


def needs_healing(party, items=()):
    """Whether the party is due at a Pokémon Center. A status a cure in ``items`` clears in the field is
    left out, since the cure goes first. Fuchsia made four trips to poison at 164 of 169 HP otherwise."""
    if not party:
        return False
    # PC withdrawal can retain stored HP above the recalculated maximum.
    # The nurse repairs this through normal play before the party leaves the Center.
    if any(p.hp > p.max_hp for p in party):
        return True
    # The heal line is the battle stance's HP and PP budget (planner design S5), so one rule decides both.
    from .ledger import walk_spent
    return walk_spent(cured(party, items) if items else party)


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


def shopping_item(items, stock, money, league=False, collecting=False, legendary=False, reserve=300,
                  hunt_reserve=None, cure_room=False):
    """The next item to buy, or None. ``hunt_reserve``, during a hunt, is the money kept back while
    the ball stock grows past the collecting 15 toward HUNT_STOCK. ``cure_room`` lets a first cure into
    a bag past the 18 entries a new kind needs (shopping.cure_room)."""
    counts = dict(items)
    if legendary and not counts.get(ITEMS['MASTER_BALL']):
        if ITEMS['ULTRA_BALL'] not in stock:
            return None
        repel = next((name for name in ('MAX_REPEL', 'SUPER_REPEL', 'REPEL') if ITEMS[name] in stock), 'MAX_REPEL')
        for name, target in (('ULTRA_BALL', 20), (repel, 3), ('HYPER_POTION', 5)):
            item = ITEMS[name]
            if item in stock and counts.get(item, 0) < target and PRICES[item] <= money - reserve:
                if item in counts or len(items) < 20:
                    return item
        return None
    desired = {ITEMS["POKE_BALL"]: 5, ITEMS["POTION"]: 3, ITEMS["SUPER_POTION"]: 3,
               ITEMS["ANTIDOTE"]: 2, ITEMS["PARLYZ_HEAL"]: 1}
    ball_count = sum(counts.get(i, 0) for i in BALLS)
    heal_count = sum(counts.get(i, 0) for i in HEALING)
    heal_target = 3
    if league:
        # The League kit is sized for its rooms with money kept for a second run (planning/boss.py kit),
        # the same rule Gold, Silver and Crystal shop by.
        # The Indigo Plateau mart sells no Hyper Potion, so its cheapest strong restore is the kit's.
        from ..planning import boss
        strong = sorted((ITEMS[name] for name in ("HYPER_POTION", "MAX_POTION", "FULL_RESTORE") if ITEMS[name] in stock),
                        key=lambda item: PRICES[item])
        revives = counts.get(ITEMS["REVIVE"], 0) + counts.get(ITEMS["MAX_REVIVE"], 0)
        restores, extra = boss.kit(heal_count, revives, money - reserve,
                                   PRICES[strong[0] if strong else ITEMS["HYPER_POTION"]], PRICES[ITEMS["REVIVE"]])
        heal_target = heal_count + restores
        desired[ITEMS["REVIVE"]] = counts.get(ITEMS["REVIVE"], 0) + extra
        # Freeze never thaws, and Lance's Dragonair can stall forever against a frozen last partner.
        desired[ITEMS["FULL_HEAL"]] = 3
    elif ITEMS["ANTIDOTE"] not in stock:
        # Fuchsia, Saffron and Cinnabar sell no Antidote, so their cure is a Full Heal.
        desired[ITEMS["FULL_HEAL"]] = max(0, 2 - counts.get(ITEMS["ANTIDOTE"], 0))
    order = sorted(stock, key=lambda item: (item not in strong, strong.index(item) if item in strong else 0,
                                            item != ITEMS["REVIVE"])) if league else stock
    for item in order:
        target = desired.get(item, 0)
        if item in BALLS:
            target = max(0, (15 if collecting else 5) - ball_count + counts.get(item, 0))
            if hunt_reserve is not None and PRICES.get(item, 0) <= money - hunt_reserve:
                target = max(target, HUNT_STOCK - ball_count + counts.get(item, 0))
        if item in HEALING:
            target = max(0, heal_target - heal_count + counts.get(item, 0))
        first_cure = cure_room and item in CURES and item not in HEALING
        if counts.get(item, 0) >= target or (len(items) >= (20 if league else 18) and item not in counts
                                             and not first_cure):
            continue
        if 0 < PRICES.get(item, 0) <= money - reserve:
            return item
    return None


@dataclass(frozen=True)
class Decision:
    kind: str
    index: int = 0
    target: int = 0
    reason: str = ""
    partner_key: str | None = None
    # A run the battle stance chose, which the policy counts as a flee attempt.
    stance: bool = False
    # A run from a catch nobody can weaken, which leaves its species for a new move, member or ball.
    defer: bool = False


# Why the battle stance runs, by goal kind, with the shiny case first.
FLEE_REASONS = {
    'shiny': 'Run from the shiny rather than knock it out without a way to catch it',
    TRAVEL: 'Run from the wild battle and keep travelling',
    HUNT: 'Run from the wild battle and keep hunting for the target',
    STORY: 'Run from the wild battle to save HP and PP for the walk to the next stop',
}


def useful_capture(snapshot, species, level, required_move=None, keeps=None):
    """Whether an incidental capture is worth a ball.

    A field-move carrier and a missing entry keep their own rules. An owned species is caught only
    when ``keeps``, the PC's catch rule (collection.improves), says the PC would keep the wild copy.
    Its rarity has no level term, so a higher level or a new type is no reason, and without ``keeps``
    an owned species is not caught. A missing entry is a keep under that rule anyway.
    """
    known = SPECIES.get(species, {})
    if required_move and required_move in known.get('hms', []):
        return True
    if known.get('dex') not in snapshot.owned:
        team_level = max((p.level for p in snapshot.party), default=1)
        return len(snapshot.party) < 3 or level >= team_level * 0.4
    return keeps is not None and bool(keeps())


def choose_battle(snapshot, me, enemy, active, used_status=(), can_switch=True, catch_attempts=0, required_move=None, collect_missing=False, capture_species=None, repeat_species=None, training_index=None,
                  kind=STORY, flee_tries=0, keeps=None, reserve=None):
    """The next battle decision. ``kind`` is the goal kind the battle stance follows (planning/stance.py),
    ``flee_tries`` counts the failed runs in this battle and ``keeps`` is as in useful_capture.
    ``reserve`` says whether a catch with its own rule may take the upgrade slot
    (collection.reserve_allows). An owned species asks ``keeps``, which holds the slot already."""
    if (snapshot.in_battle == 1
            and MAPS['POKEMON_TOWER_1F'] <= snapshot.map <= MAPS['POKEMON_TOWER_7F']
            and not dict(snapshot.items).get(ITEMS['SILPH_SCOPE'])):
        return Decision('run', reason='Leave the unidentified ghost until the Silph Scope is obtained')
    shiny = snapshot.in_battle == 1 and snapshot.enemy_shiny
    moves = ranked_moves(me, enemy, used_status)
    slot = moves[0][1] if moves else 0
    incoming = max((damage(mid, enemy, me) for mid in enemy.moves if mid), default=me.max_hp * 0.2)
    known = SPECIES.get(enemy.species, {})
    missing_species = known.get("dex") not in snapshot.owned
    required = required_move in known.get('hms', []) if required_move else False
    useful = useful_capture(snapshot, enemy.species, enemy.level, required_move, keeps)
    safe = me.hp > incoming * 1.5 and not me.status
    balls = [(i, item) for item in BALLS for i, (bag_item, qty) in enumerate(snapshot.items) if bag_item == item and qty > 0]
    legendary = known.get('dex') in (144,145,146,150)
    allowed_capture = capture_species is None or enemy.species == capture_species or legendary or shiny
    useful = useful and allowed_capture
    collection_target = (collect_missing or legendary) and missing_species and allowed_capture
    repeat_target = enemy.species == repeat_species and not missing_species
    collection_target |= repeat_target or shiny
    if ((collection_target and not repeat_target or useful and (missing_species or required))
            and reserve is not None and not reserve()):
        collection_target = useful = False
    from .ledger import LEGENDARY_THROWS, battle_ledger, catch_spent, legendary_retreat
    capture_limit = float('inf') if shiny else LEGENDARY_THROWS if legendary else 5 if repeat_target else 20
    master = next((i for i,(item,qty) in enumerate(snapshot.items) if item==ITEMS['MASTER_BALL'] and qty),None)
    wild = snapshot.in_battle == 1 and snapshot.battle_type == 0
    exhausted = catch_spent(snapshot, catch_attempts, capture_limit)
    if legendary and legendary_retreat(snapshot, catch_attempts, missing_species or repeat_target):
        return Decision('run', reason='Retreat and prepare another legendary attempt with balls and storage space')
    # What the run wants and can catch now: a collection target, or an incidental capture the
    # collection counts as useful, exactly when a catch rule below fires. The stance catches it
    # whatever the goal, and runs from a shiny it cannot catch.
    wanted = wild and snapshot.can_catch and (
        collection_target and catch_attempts < capture_limit and (balls or (legendary or shiny) and master is not None)
        # A field-move carrier stays wanted while the catcher is unsafe, so its hunt fights for it.
        or useful and balls and (safe or required) and catch_attempts < (12 if required else 5))
    encounter = Encounter(wild=wild, wanted=bool(wanted), shiny=bool(wild and shiny and exhausted), tries=flee_tries)
    books = battle_ledger()
    if stance(kind, encounter, books, goal=kind, resources=lambda: books.snapshot(snapshot.party)) is FLEE:
        return Decision('run', reason=FLEE_REASONS.get(kind if not encounter.shiny else 'shiny', FLEE_REASONS[STORY]),
                        stance=True)
    if snapshot.in_battle == 1 and snapshot.battle_type == 0 and snapshot.can_catch and collection_target and catch_attempts < capture_limit and (balls or (legendary or shiny) and master is not None):
        if (legendary or shiny) and master is not None:
            return Decision('item',master,reason='Secure the shiny with the Master Ball' if shiny else 'Secure the legendary with the Master Ball')
        healing = healing_item(snapshot.items,me,incoming)
        if me.hp <= incoming * 1.5 and healing is not None:
            return Decision('item',healing,active,'Keep the catcher healthy while preserving the wild Pokémon')
        status_moves = [(MOVES[mid]['accuracy'],i) for i,(mid,pp) in enumerate(zip(me.moves,me.pp))
                        if pp and MOVES.get(mid,{}).get('effect') in ('SLEEP_EFFECT','PARALYZE_EFFECT')
                        and effectiveness(MOVES[mid]['type'],enemy.types)]
        if not enemy.status and status_moves and (me.hp > incoming or me.speed > enemy.speed):
            return Decision('fight',max(status_moves)[1],reason='Use sleep or paralysis to help the catch')
        if can_switch and not enemy.status and not status_moves:
            catchers = [(p.hp,i) for i,p in enumerate(snapshot.party) if i!=active and p.hp>p.max_hp*0.7 and not p.status
                        and any(pp and MOVES.get(mid,{}).get('effect') in ('SLEEP_EFFECT','PARALYZE_EFFECT')
                                and effectiveness(MOVES[mid]['type'],enemy.types) for mid,pp in zip(p.moves,p.pp))
                        and p.hp > max((damage(mid,enemy,p) for mid in enemy.moves),default=0)]
            if catchers:
                return Decision('switch',max(catchers)[1],reason='Bring in a healthy catcher with sleep or paralysis')
        weakening = [(score,i) for score,i in moves if MOVES[me.moves[i]]['effect'] not in RISKY_CHIPS
                     and 0 < damage(me.moves[i],me,enemy) * 2.5 < enemy.hp]
        if not legendary and not shiny and enemy.hp > enemy.max_hp*0.4 and weakening and not enemy.status:
            return Decision('fight',max(weakening)[1],reason='Use a gentle attack with a margin for critical damage')
        one_time = known.get('dex') == 143 or known.get('dex') in (100, 101) and snapshot.map == MAPS['POWER_PLANT']
        if (not (legendary or shiny or one_time) and enemy.hp > enemy.max_hp * 0.4 and not enemy.status
                and long_odds(known.get('catch_rate', 255), balls[-1][1], enemy)):
            # Under 1 in 10 a throw and the battler cannot weaken it (planning.throws).
            chippers = [(p.hp, i) for i, p in enumerate(snapshot.party) if i != active and p.hp > p.max_hp * 0.5
                        and not p.status and p.hp > max((damage(mid, enemy, p) for mid in enemy.moves), default=0)
                        and any(mid and pp and MOVES.get(mid, {}).get('effect') not in RISKY_CHIPS
                                and damage_division_safe(mid, p, enemy)
                                and 0 < damage(mid, p, enemy) * 2.5 < enemy.hp for mid, pp in zip(p.moves, p.pp))]
            if can_switch and chippers:
                return Decision('switch', max(chippers)[1],
                                reason='Bring in a partner that can weaken the target without a knockout')
            if can_switch and not status_moves and enemy.hp >= enemy.max_hp:
                return Decision('run', reason='Leave a catch under 1 in 10 a throw that nobody here can weaken',
                                defer=True)
        return Decision('item',balls[-1][0],reason='Catch the shiny without risking a knockout' if shiny else 'Catch the returned legendary' if repeat_target and legendary
                        else 'Catch another partner for the collection or a useful trade' if repeat_target
                        else 'Catch the missing Pokédex entry without risking a knockout')
    if snapshot.in_battle == 1 and snapshot.battle_type == 0 and snapshot.can_catch and useful and balls and safe and catch_attempts < (12 if required else 5):
        if enemy.hp <= enemy.max_hp * 0.35 or enemy.status or not moves:
            ball_index = balls[-1][0] if known.get("catch_rate", 255) < 100 else balls[0][0]
            return Decision("item", ball_index, reason="Catch a missing species, a needed partner, or a stronger reserve")
        weakening = [(score, k) for score, k in moves if 0 < damage(me.moves[k], me, enemy) < enemy.hp * 0.8]
        if weakening:
            return Decision("fight", max(weakening)[1], reason="Weaken the target without an expected knockout")
        if required:
            return Decision('item', balls[0][0], reason='Catch the field-move partner without knocking it out')
    if snapshot.in_battle == 2 and not me.status & FROZEN and spent(me) and not hurts(me, enemy):
        # Nothing this battler has left can hurt the foe, such as Struggle into Agatha's Ghosts, so items
        # spent on it only lengthen a battle it cannot win. A battler that never had an attack, such as
        # an early Kakuna, keeps the usual path. A partner that can hurt the foe and take its
        # next hit comes in, below the usual bar of twice that hit. No switch brings back a battler that
        # cannot hurt the foe, so this one skips the wait between switches.
        partners = []
        for i, mon in enumerate(snapshot.party):
            if i == active or mon.hp <= 0 or mon.status & ASLEEP_OR_FROZEN or not hurts(mon, enemy):
                continue
            threat = max((damage(mid, enemy, mon) for mid in enemy.moves if mid), default=mon.max_hp * 0.2)
            offense = ranked_moves(mon, enemy)
            if mon.hp > threat:
                partners.append(((offense[0][0] if offense else 0) / max(1, threat), mon.hp, i))
        if partners:
            return Decision("switch", max(partners)[2], reason="Nothing left here can hurt the foe, so bring in a partner who can")
        if foe_never_attacks(enemy, me):
            return lose_attempt(snapshot, enemy, active, slot)
        return Decision("fight", slot, reason="Nothing left here can hurt the foe, so spend no items keeping it in")
    item_index = healing_item(snapshot.items, me, incoming)
    if item_index is not None:
        return Decision("item", item_index, active, "Recover HP or cure status before attacking")
    if me.status & FROZEN:
        # Freeze never thaws by itself in these games. Against a foe that cannot finish the
        # battle either, such as Normal attacks into a Ghost, choosing FIGHT loops forever.
        partners = [(mon.level, i) for i, mon in enumerate(snapshot.party)
                    if i != active and mon.hp > 0 and not mon.status & 39]
        if partners:
            return Decision("switch", max(partners)[1], reason="A frozen Pokémon cannot act, so bring in a partner")
        fainted = [(mon.level, i) for i, mon in enumerate(snapshot.party) if i != active and mon.hp <= 0]
        revive = next((i for name in ("MAX_REVIVE", "REVIVE") for i, (item, qty) in enumerate(snapshot.items)
                       if item == ITEMS[name] and qty > 0), None)
        if fainted and revive is not None:
            return Decision("item", revive, max(fainted)[1], "Revive a partner because a frozen Pokémon can never act")
        if snapshot.in_battle == 1:
            return Decision("run", reason="Leave a battle that a frozen Pokémon cannot finish")
        if foe_never_attacks(enemy, me):
            return lose_attempt(snapshot, enemy, active, slot)
    candidates = []
    unsafe_moves = any(mid and pp and not damage_division_safe(mid, me, enemy)
                       for mid, pp in zip(me.moves, me.pp))
    needs_safe_partner = unsafe_moves and not any(score > 0 for score, _ in moves)
    if can_switch or needs_safe_partner:
        for i, mon in enumerate(snapshot.party):
            if i == active or mon.hp <= 0 or mon.status & 39:
                continue
            offense = ranked_moves(mon, enemy)
            threat = max((damage(mid, enemy, mon) for mid in enemy.moves if mid), default=mon.max_hp * 0.2)
            if offense and any(damage(mon.moves[slot], mon, enemy) > 0 for _, slot in offense) and mon.hp > threat * 2:
                candidates.append((offense[0][0] / max(1, threat), i))
    current_ratio = (moves[0][0] if moves else 0) / max(1, incoming)
    productive_trainee = (active == training_index and me.level < 100 and me.hp > incoming * 2
                          and any(score > 0 and damage(me.moves[index], me, enemy) > 0 for score, index in moves))
    if candidates and (needs_safe_partner or me.hp <= incoming or not moves
                       or not productive_trainee and max(candidates)[0] > current_ratio * 2.5):
        return Decision("switch", max(candidates)[1], reason="Bring in a healthier Pokémon with a better matchup")
    if snapshot.in_battle == 1 and needs_safe_partner and not candidates:
        return Decision('run', reason='Leave a matchup that risks the original game’s damage calculation freeze')
    if snapshot.in_battle == 1 and (not moves or me.hp <= incoming) and not candidates:
        return Decision("run", reason="Avoid a likely blackout in a wild encounter")
    return Decision("fight", slot, reason="Choose the strongest expected outcome from moves with PP")
