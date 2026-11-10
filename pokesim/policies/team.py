"""Opponent preparation and party development using observable team capabilities."""
from dataclasses import asdict

from .battle import HEALING, damage, effectiveness, ranked_moves
from ..events import LEGENDARY_DEX
from ..game_data import current_variant
from ..planning.readiness import READY, hp_stat, score as matchup, stat as trainer_stat
from ..ram import BOX_CAPACITY, DEX_NAMES, PartyMon
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
if current_variant() == 'yellow':
    # Yellow's leaders field the teams from the anime, from pret/pokeyellow parties.asm.
    OPPONENTS.update({
        1: ('Brock', 'ONIX', 12), 4: ('Lt. Surge', 'RAICHU', 28), 8: ('Erika', 'WEEPINBELL', 32),
        16: ('Koga', 'VENOMOTH', 50), 32: ('Sabrina', 'ALAKAZAM', 50),
        64: ('Blaine', 'ARCANINE', 54), 128: ('Giovanni', 'RHYDON', 55),
    })
# A randomized adventure with shuffled trainers meets whatever now holds each ace's party slot.
from ..randomized import gen1_opponents
OPPONENTS = gen1_opponents(OPPONENTS, SPECIES)


# Yellow's Pikachu follows the player and loses friendship when it leaves the party,
# so it never becomes a deposit candidate there.
STAYS_IN_PARTY = ({sid for sid, data in SPECIES.items() if data.get('name') == 'PIKACHU'}
                  if current_variant() == 'yellow' else set())


def stays_in_party(s, mon):
    """Whether this party member is Yellow's starter Pikachu, which never leaves the party.

    pret/pokeyellow IsStarterPikachuAliveInOurParty treats a Pikachu as the starter only when its
    trainer ID is the player's. A Pikachu traded in from another game can go to the PC like any
    other Pokémon. Kept for every Pikachu, a party of HM holders and a traded Pikachu had no one
    left to deposit, so every trade into Yellow failed to make room.
    """
    species = mon['species'] if isinstance(mon, dict) else mon.species
    if species not in STAYS_IN_PARTY:
        return False
    player = getattr(s, 'player_id', None)
    trainer = mon.get('trainer_id') if isinstance(mon, dict) else getattr(mon, 'trainer_id', None)
    return player is None or trainer is None or trainer == player


def potential(species, teammates=()):
    data = SPECIES.get(species, {})
    covered = {t for p in teammates for t in p.types}
    return sum(data.get('stats', [0])) + 70 * len(set(data.get('types', [])) - covered)


def storage_headroom(s):
    """Free slots across every box."""
    return sum(BOX_CAPACITY - count for count in s.box_counts)


def release_rated(s, preferences=None, roles=(), stock=(), partners=frozenset(), gifts=frozenset(),
                  rewards=frozenset(), requested=None, demand=None, favor=None, extra=(), team=frozenset()):
    """Every Pokémon scored with pcvalue.rate. ``demand`` maps a Pokédex number to the linked adventures
    missing it, which keeps that many copies and counts as trade demand. ``favor`` is the Favor shiny or
    Favor DVs setting, ``extra`` adds rows such as an incoming trade, ``team`` is pcvalue.Inputs.team
    and the rest are as in ``entries``."""
    from collections import Counter
    from ..investment import dex_rarity
    from ..pcvalue import Inputs, rate
    return rate([*entries(s, preferences, roles, stock, partners, gifts, rewards, requested), *extra],
                Inputs(demand=dict(demand or {}), wishes=Counter(demand or {}), favor=favor, rarity=dex_rarity,
                       team=frozenset(team)))


def team_keys(party):
    """The (dex, DVs) of each party member with known DVs, for pcvalue.Inputs.team."""
    return frozenset((SPECIES.get(mon.species, {}).get('dex', 0), tuple(mon.dvs)) for mon in party
                     if len(getattr(mon, 'dvs', ())) == 5)


def spare_copies(s, stock=()):
    """Boxed duplicates that may be given up, lowest value first, as (box, position, level).

    Species in ``stock`` hold a plan role for their best copies (pcvalue.ROLE_COPIES).
    """
    from ..pcvalue import queue
    return [(*row.entry.slot, row.entry.level) for row in queue(release_rated(s, stock=stock))
            if row.status == 'spare' and not row.entry.requested]


# The last release_target inputs, its answer, and the chosen Pokémon's species and PC value text with
# whether nothing at all may go (release_note).
_RELEASE = [None, None, None]


def release_target(s, stock=(), reserved=(), partners=frozenset(), gifts=frozenset(), preferences=None,
                   demand=None, rewards=frozenset(), requested=None, roles=(), favor=None, team=frozenset()):
    """The next Pokémon to release as (box, position), or None (pcvalue.py). Only a stored spare may go:
    the party, a plan's trainee or partner and a ``team`` member deposited at this visit are floors.

    The lowest-value Pokémon that may go is chosen among the ones a refill needs, ordered for one PC
    visit: the open box first, then the box holding the most of them. This ranks every stored copy and
    is asked on every step while storage is tight, so the answer is kept until the party, the PC or the
    inputs change. A slot the PC list cannot reach, or whose release just failed, belongs in
    ``reserved``. The other inputs are as in ``entries``.
    """
    reserved = frozenset(reserved)
    freeze = lambda mapping: tuple(sorted((mapping or {}).items()))  # noqa: E731
    key = (tuple(s.party), getattr(s, 'stored_details', None), getattr(s, 'stored_pokemon', None),
           frozenset(stock.items() if isinstance(stock, dict) else stock), reserved, frozenset(partners), frozenset(gifts),
           getattr(s, 'player_id', None),
           getattr(s, 'active_box', None), tuple(getattr(s, 'box_counts', ()) or ()),
           tuple(sorted((key, (value or {}).get('state')) for key, value in (preferences or {}).items())),
           freeze(demand), frozenset(rewards), freeze(requested), frozenset(roles), favor, frozenset(team))
    try:
        hash(key)
    except TypeError:
        key = object()
    if _RELEASE[0] != key:
        _RELEASE[:] = [key, *_release_target(s, stock, reserved, partners, gifts, preferences, demand, rewards,
                                             requested, roles, favor, team)]
    return _RELEASE[1]


def release_note():
    """The last release_target answer's (species, PC value text), None when it found none, and whether
    nothing at all may go, so the journal can say why and say once that the PC is full."""
    note = _RELEASE[2]
    return (note[0] if note else None), bool(note and note[1])


def stock_kind(stock, species):
    """'plan', 'trade' or None for a species in ``stock``. A plain set counts as plan stock."""
    if species not in stock:
        return None
    return stock[species] if isinstance(stock, dict) else 'plan'


def entries(s, preferences=None, roles=(), stock=(), partners=frozenset(), gifts=frozenset(), rewards=frozenset(),
            requested=None):
    """The party and PC as pcvalue rows.

    ``preferences`` are the stored trade preferences: Keep locks a Pokémon, and an offered one is
    capped stock. ``roles`` are the trade keys of the Pokémon a running project relies on and ``stock``
    the species it works with (a dict from plan_inputs marks a trade's give 'trade', which holds a role
    but no floor), ``partners`` the linked adventures' trainer ids, ``gifts`` the species this version
    gives only as a gift or fossil, ``rewards`` the League reward marks (rewards.marks) and
    ``requested`` maps an identity to an owner's release request.
    """
    from ..pcvalue import Entry
    from ..rewards import mark
    from ..trade.preferences import identity, legacy_lock
    preferences, requested = preferences or {}, requested or {}
    player = getattr(s, 'player_id', None)
    rows = []
    for mon in [*(asdict(mon) | {'box': None} for mon in s.party), *s.storage_entries()]:
        data = SPECIES.get(mon['species'], {})
        dex, trainer, dvs = data.get('dex', 0), mon.get('trainer_id'), tuple(mon.get('dvs') or ())
        state = (preferences.get(identity(mon)) or {}).get('state') if preferences and trainer is not None else None
        kind = stock_kind(stock, mon['species'])
        if trainer is not None and len(dvs) == 5 and mark(trainer, dvs) in rewards:
            origin = 'reward'
        elif dex in LEGENDARY_DEX:
            origin = 'legendary'
        elif trainer == player and mon['species'] in gifts:
            origin = 'gift'
        elif player is not None and trainer is not None and trainer != player and trainer not in partners:
            origin = 'traded'
        else:
            origin = 'caught'
        rows.append(Entry(
            None if mon['box'] is None else (mon['box'], mon['position']), (dex, 0),
            DEX_NAMES.get(dex, data.get('name', '?').replace('_', ' ').title()),
            mon['level'], mon.get('experience', 0), dvs, tuple(mon.get('stat_exp') or ()), False, origin,
            state in ('locked', 'withdrawn') or bool(preferences) and legacy_lock(preferences, mon),
            trainer is not None and identity(mon) in roles, state == 'offered' or kind is not None,
            requested.get(identity(mon), '') if trainer is not None else '', mon,
            kind == 'trade' or state == 'offered' and kind != 'plan'))
    return rows


def requested_slots(s, requested, preferences=None, reserved=()):
    """The boxed slots of the owner's release requests that a release may take, outside ``reserved``.
    A Keep, party, egg or unconfirmed last copy request waits, so it never starts a visit."""
    from ..pcvalue import requested as asked
    if not requested:
        return []
    return [row.entry.slot for row in asked(release_rated(s, preferences, requested=requested))
            if row.entry.slot not in frozenset(reserved)]


def held_identities(s):
    """The trade identity of every Pokémon in the party and the PC, or None while a boxed row is only the
    compact species and level fallback, which names no trainer, so no request can be told gone."""
    from ..trade.preferences import identity
    stored = s.storage_entries()
    if any(mon.get('trainer_id') is None for mon in stored):
        return None
    return {identity(mon) for mon in [*(asdict(mon) for mon in s.party), *stored] if mon.get('trainer_id') is not None}


def _release_target(s, stock, reserved, partners, gifts, preferences, demand, rewards, requested, roles, favor, team=frozenset()):
    from ..planning.ledger import box_wanted
    from ..pcvalue import deadlocked, releases, requested as asked
    every = release_rated(s, preferences, roles, stock, partners, gifts, rewards, requested, demand, favor, team=team)
    rated = [row for row in every if row.entry.slot not in reserved]
    # The visit takes every owner request, as in Gold, Silver and Crystal (gen2/ledger.py).
    chosen = releases(rated, max(box_wanted(storage_headroom(s), True), len(asked(rated)), 1),
                      getattr(s, 'active_box', None))
    row = chosen[0] if chosen else None
    return (row.entry.slot if row else None,
            ((row.entry.record['species'], row.describe()) if row else None,
             deadlocked(every, storage_headroom(s))))


def reserve_to_deposit(s, *, prefer_completed=False):
    strongest = max(range(len(s.party)), key=lambda i: s.party[i].level, default=None)
    candidates = [i for i, p in enumerate(s.party) if i != strongest and not stays_in_party(s, p)
                  and not any(move in (15, 19, 57, 70, 148)
                              and not any(move in other.moves for j, other in enumerate(s.party) if j != i)
                              for move in p.moves)]
    return min(candidates, key=lambda i: (not (prefer_completed and s.party[i].level >= 100),
                                         s.party[i].level * 10 + potential(s.party[i].species))) if candidates else None


def development_candidate(s, encounter_level):
    if len(s.party) < 2:
        return None
    lead_level = max(p.level for p in s.party)
    # Yellow's Pikachu cannot be boxed, so it is trained first. Battle switching covers a tougher opponent
    # and shares the experience.
    candidates = [i for i, p in enumerate(s.party)
                  if p.level < lead_level * 0.8 and stays_in_party(s, p) and p.level + 12 >= encounter_level
                  and p.hp >= p.max_hp * 0.85 and not p.status
                  and any(MOVES.get(m, {}).get('power') and pp for m, pp in zip(p.moves, p.pp))]
    if candidates:
        return candidates[0]
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


_READINESS = {}


def readiness(s, bit=None):
    """Estimate the party against the next opponent, or the one ``bit`` names.

    The planner asks several times per step, so each answer is kept until the opponent, the
    party or the bag changes. Callers get their own copy, as a fresh estimate would give them.
    """
    bit = bit or next_opponent(s)
    tables = (id(SPECIES), id(MOVES), id(OPPONENTS), id(HEALING), id(ITEMS), damage, ranked_moves, effectiveness)
    if _READINESS.get('tables') != tables or len(_READINESS) > 64:
        _READINESS.clear()
        _READINESS['tables'] = tables
    key = (bit, tuple(s.party), tuple(s.items))
    try:
        hash(key)
    except TypeError:
        # Stand-in party members that cannot be hashed are estimated every time.
        return _readiness(s, bit)
    result = _READINESS.get(key)
    if result is None:
        result = _READINESS[key] = _readiness(s, bit)
    return {**result, 'members': [dict(row) for row in result['members']], 'concerns': list(result['concerns'])}


def _readiness(s, bit):
    name, species_name, level = OPPONENTS[bit]
    sid, data = next(((sid, data) for sid, data in SPECIES.items() if data.get('name') == species_name))
    hp, attack, defense, speed, special = data['stats']
    stat = lambda base: trainer_stat(base, level)  # noqa: E731
    max_hp = hp_stat(hp, level)
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
        score = matchup(p.hp, attack_damage, incoming, enemy.hp, p.speed < enemy.speed)
        if p.status:
            score //= 2
        members.append({'index': i, 'name': p.nick or p.name, 'level': p.level, 'score': score,
                        'coverage': any(effectiveness(MOVES[p.moves[k]]['type'], enemy.types) > 1 for _, k in moves),
                        'pp': sum(pp for m, pp in zip(p.moves, p.pp) if MOVES.get(m, {}).get('power'))})
    best = max(members, key=lambda row: row['score'], default=None)
    healing = sum(qty for item, qty in s.items if item in HEALING)
    revives = dict(s.items).get(ITEMS['REVIVE'], 0)
    concerns = []
    if not best or best['score'] < READY:
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
