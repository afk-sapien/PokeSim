"""How well the party matches up against a boss's ace, one rule for both generations.

Each party Pokémon scores 0 to 100: the turns it survives the ace's strongest move over the turns it
needs to knock the ace out, one more when it is slower. The team's score is its best member's. Red,
Blue and Yellow (policies/team.py) and Gold, Silver and Crystal (gen2/readiness.py) estimate the
damage their own way and share the score and the gates.

A team trains before a gym until it scores READY or its best fighter is MARGIN levels over the gym's
ace, and before the League until every room scores LEAGUE_READY or its best fighter reaches the
League's top ace level. A Gold run took one Lv 13 fighter and Pokémon at Lv 4 to 5 that knew no attack
into Bugsy, since Gen II gyms after Falkner had no gate at all.
"""

READY = 75
LEAGUE_READY = 60
MARGIN = 10


def score(hp, dealt, taken, enemy_hp, slower):
    """One member's score from its HP, the damage it deals and takes per turn, and the ace's HP."""
    if not dealt or not hp:
        return 0
    turns = enemy_hp / max(1, dealt)
    survival = hp / max(1, taken)
    return min(100, round(100 * survival / max(1, turns + slower)))


def stat(base, level):
    """A trainer Pokémon's stat estimated from its base stat, with middling DVs and no stat experience."""
    return (2 * (base + 8) * level // 100) + 5


def hp_stat(base, level):
    return stat(base, level) + level + 5


def unready(best, level, ace):
    """Whether a team whose best score is ``best`` and best fighter is at ``level`` trains before a gym."""
    return best < READY and level < ace + MARGIN


def league_unready(scores, level, ace):
    """Whether a team trains before the League: a room scores under LEAGUE_READY and the best fighter
    is under ``ace``, the League's top ace level."""
    return level < ace and any(best < LEAGUE_READY for best in scores)
