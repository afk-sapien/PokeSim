"""Opponent preparation and party development using observable team capabilities."""
from .battle import HEALING, damage, effectiveness, ranked_moves
from ..ram import PartyMon
from ..strategy_data import ITEMS, MAPS, MOVES, SPECIES, event_set

OPPONENTS = {
    1: ('Brock', 'ONIX', 14), 2: ('Misty', 'STARMIE', 21),
    4: ('Lt. Surge', 'RAICHU', 24), 8: ('Erika', 'VILEPLUME', 29),
    16: ('Koga', 'WEEZING', 43), 32: ('Sabrina', 'ALAKAZAM', 43),
    64: ('Blaine', 'ARCANINE', 47), 128: ('Giovanni', 'RHYDON', 50),
    256: ('Lorelei', 'LAPRAS', 56), 257: ('Bruno', 'MACHAMP', 58),
    258: ('Agatha', 'GENGAR', 60), 259: ('Lance', 'DRAGONITE', 62),
    260: ('the Champion', 'ALAKAZAM', 59),
}


def potential(species, teammates=()):
    data = SPECIES.get(species, {})
    covered = {t for p in teammates for t in p.types}
    return sum(data.get('stats', [0])) + 70 * len(set(data.get('types', [])) - covered)


def reserve_to_deposit(s):
    strongest = max(range(len(s.party)), key=lambda i: s.party[i].level, default=None)
    candidates = [i for i, p in enumerate(s.party) if i != strongest
                  and not any(move in (15, 19, 57, 70, 148)
                              and not any(move in other.moves for j, other in enumerate(s.party) if j != i)
                              for move in p.moves)]
    return min(candidates, key=lambda i: s.party[i].level * 10 + potential(s.party[i].species)) if candidates else None


def development_candidate(s, encounter_level):
    if len(s.party) < 2:
        return None
    lead_level = max(p.level for p in s.party)
    candidates = [i for i, p in enumerate(s.party)
                  if p.level < lead_level * 0.8 and p.level + 2 >= encounter_level
                  and p.hp >= p.max_hp * 0.85 and not p.status
                  and any(MOVES.get(m, {}).get('power') and pp for m, pp in zip(p.moves, p.pp))]
    return max(candidates, key=lambda i: potential(s.party[i].species, [p for j, p in enumerate(s.party) if i != j])) if candidates else None


def next_opponent(s):
    for bit in (1, 2, 4, 8, 16, 32, 64, 128):
        if not s.badges & bit:
            return bit
    flags = ('EVENT_BEAT_LORELEIS_ROOM_TRAINER_0', 'EVENT_BEAT_BRUNOS_ROOM_TRAINER_0',
             'EVENT_BEAT_AGATHAS_ROOM_TRAINER_0', 'EVENT_BEAT_LANCE')
    rooms = ('LORELEIS_ROOM', 'BRUNOS_ROOM', 'AGATHAS_ROOM', 'LANCES_ROOM', 'CHAMPIONS_ROOM')
    current = next((i for i, room in enumerate(rooms) if MAPS[room] == s.map), None)
    if current is None:
        return 256
    return min(260, 256 + current + int(current < 4 and event_set(s.event_flags, flags[current])))


def readiness(s, bit=None):
    bit = bit or next_opponent(s)
    name, species_name, level = OPPONENTS[bit]
    sid, data = next(((sid, data) for sid, data in SPECIES.items() if data.get('name') == species_name))
    hp, attack, defense, speed, special = data['stats']
    stat = lambda base: (2 * (base + 8) * level // 100) + 5
    max_hp = stat(hp) + level + 5
    enemy_moves = list(data.get('initial_moves', [33]))
    for learned_level, mid in data.get('learnset', []):
        if learned_level <= level and mid not in enemy_moves:
            enemy_moves.append(mid)
            enemy_moves = enemy_moves[-4:]
    special_moves = {1: 'BIDE', 2: 'BUBBLEBEAM', 4: 'THUNDERBOLT', 8: 'MEGA_DRAIN',
                     16: 'TOXIC', 32: 'PSYWAVE', 64: 'FIRE_BLAST', 128: 'FISSURE',
                     256: 'BLIZZARD', 257: 'FISSURE', 258: 'TOXIC', 259: 'BARRIER'}
    special_move = next((mid for mid, move in MOVES.items() if move['name'] == special_moves.get(bit)), None)
    if special_move:
        enemy_moves = enemy_moves[:3] + [special_move]
    enemy_moves = tuple(enemy_moves)
    enemy = PartyMon(sid, max_hp, max_hp, level, name, types=tuple(data['types']), moves=enemy_moves,
                     pp=(20,) * len(enemy_moves), attack=stat(attack), defense=stat(defense),
                     speed=stat(speed), special=stat(special))
    members = []
    for i, p in enumerate(s.party):
        moves = ranked_moves(p, enemy)
        attack_damage = max((damage(p.moves[k], p, enemy) * MOVES[p.moves[k]]['accuracy'] / 100
                             for _, k in moves), default=0)
        incoming = max((damage(mid, enemy, p) * MOVES[mid]['accuracy'] / 100 for mid in enemy.moves), default=1)
        turns = enemy.hp / max(1, attack_damage)
        survival = p.hp / max(1, incoming)
        score = min(100, round(100 * survival / max(1, turns + (p.speed < enemy.speed)))) if attack_damage and p.hp else 0
        if p.status:
            score //= 2
        members.append({'index': i, 'name': p.nick or p.name, 'level': p.level, 'score': score,
                        'coverage': any(effectiveness(MOVES[p.moves[k]]['type'], enemy.types) > 1 for _, k in moves),
                        'pp': sum(pp for m, pp in zip(p.moves, p.pp) if MOVES.get(m, {}).get('power'))})
    best = max(members, key=lambda row: row['score'], default=None)
    healing = sum(qty for item, qty in s.items if item in HEALING)
    revives = dict(s.items).get(ITEMS['REVIVE'], 0)
    concerns = []
    if not best or best['score'] < 75:
        concerns.append('The strongest matchup still needs preparation')
    if any(p.status or not p.hp for p in s.party):
        concerns.append('Heal fainted partners or status conditions')
    if best and best['pp'] < 8:
        concerns.append('Restore attack PP before the next challenge')
    if healing < (6 if bit >= 256 else 2):
        concerns.append('Carry more healing items')
    if bit >= 256 and revives < 2:
        concerns.append('Bring Revives for the League')
    return {'opponent': name, 'score': best['score'] if best else 0,
            'lead': best['index'] if best else 0, 'members': members, 'concerns': concerns,
            'status': 'Prepared' if not concerns else 'Preparing',
            'note': 'Estimate against a representative opponent, not a win probability'}
