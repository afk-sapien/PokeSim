"""The party's matchup against a Gen II boss's ace, read from the cartridge (planning/readiness.py).

The ace is the top level Pokémon of the boss's party in the cartridge's trainer tables, with the moves
the cartridge gives it, so a randomized run meets its own. Damage both ways is the battle's own
estimate (Policy.move_score). Without the cartridge's tables there is no score, and the gates that
ask for one stand aside.
"""
from types import SimpleNamespace

from ..planning.readiness import hp_stat, score, stat

# The trainer class each boss goal battles (planning/losses.py BOSS_CLASSES).
CLASSES = {'zephyr': 1, 'hive': 3, 'plain': 2, 'fog': 4, 'storm': 7, 'mineral': 6, 'glacier': 5, 'clair': 8,
           'league_will': 11, 'league_koga': 15, 'league_bruno': 13, 'league_karen': 14, 'league_lance': 16,
           'brock': 17, 'misty': 18, 'surge': 19, 'erika': 21, 'janine': 26, 'sabrina': 35, 'blaine': 46,
           'blue': 64, 'red': 63}
LEAGUE = ('league_will', 'league_koga', 'league_bruno', 'league_karen', 'league_lance')


def boss_parties(rom_path, game):
    """The party of each boss trainer class on the cartridge, by class, or {} when it cannot be read."""
    from ..planning.cost import game_data
    tables = game_data(rom_path, game)
    if tables is None or tables.generation != 2:
        return {}
    classes = set(CLASSES.values())
    parties = {}
    for row in sorted(tables.trainers.values(), key=lambda row: row['index']):
        if row['class'] in classes and row['party']:
            parties.setdefault(row['class'], row['party'])
    return parties


def ace(data, key):
    """The top level Pokémon of the party boss goal ``key`` battles, or None when it is unknown."""
    party = getattr(data, 'boss_parties', {}).get(CLASSES.get(key))
    return max(party, key=lambda mon: mon['level']) if party else None


def ace_level(data, key):
    """The level of the boss's ace. The key 'league' names the top ace of the Elite Four and Lance."""
    levels = [ace(data, room) for room in (LEAGUE if key == 'league' else (key,))]
    return None if None in levels else max(mon['level'] for mon in levels)


def readiness(policy, party, key):
    """The best party Pokémon's score against the ace of boss goal ``key``, or None when it is unknown.

    The team heals before a boss, so each member is scored at full HP."""
    foe = ace(policy.data, key)
    row = policy.data.species.get(foe['species']) if foe else None
    if row is None:
        return None
    base, level = row['stats'], foe['level']
    stats = (hp_stat(base[0], level), *(stat(value, level) for value in base[1:]))
    attacker = SimpleNamespace(species=foe['species'], level=level, stats=stats, status=0)
    target = SimpleNamespace(enemy_species=foe['species'], enemy_level=level, enemy_hp=stats[0],
                             enemy_defense=stats[2], enemy_special_defense=stats[5])
    best = 0
    for mon in party:
        if mon.egg or not mon.max_hp or mon.species not in policy.data.species:
            continue
        dealt = max((policy.move_score(move, mon, target) for move in mon.moves if move), default=0)
        defender = SimpleNamespace(enemy_species=mon.species, enemy_level=mon.level, enemy_hp=mon.max_hp,
                                   enemy_defense=mon.stats[2], enemy_special_defense=mon.stats[5])
        taken = max((policy.move_score(move, attacker, defender) for move in foe['moves'] if move), default=1)
        best = max(best, score(mon.max_hp, dealt, taken, stats[0], mon.stats[3] < stats[3]))
    return best
