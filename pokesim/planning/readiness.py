"""Whether the team is ready for a boss, one definition for both generations.

Each generation reads a boss into ``Boss`` and its party into ``Team`` (``team``). ``judge`` answers
None to go in, or a ``Train`` verdict that names the reason and the level to train to. The boss check
before the battle (boss.py) asks ``short`` here for the HP and PP each Pokémon needs, and the
progress rows (progress_events.py) ask ``target`` for the level a gain counts toward. No other module
keeps a readiness threshold.

The rules, in the order judge asks them:

1. Inside the League's rooms nothing turns back.
2. After a loss the best fighter trains to the loss bar: REGROWTH over the best fighter level that
   lost, up to CEILING over the boss's ace, and never under the boss's floor. losses.py keeps the
   levels in the adventure's store.
3. Inside a gym, or with no matchup score, the matchup rules 4 to 6 stand aside.
4. Before the League a second battler, the partner, trains while its level is under the top ace
   less MARGIN and a room scores under READY. Only Red, Blue and Yellow name a partner.
5. Before the League the team trains while a room scores under LEAGUE_READY and the best fighter is
   under the top ace.
6. Before a gym the team trains while its best score is under READY and its best fighter is under
   MARGIN over the ace.
7. An optional run, the postgame League of Gold, Silver and Crystal, also needs a full attack's PP
   for each opponent among the Pokémon at the League's lowest level or over. After a loss there those
   Pokémon need DEPTH_REGROWTH more levels between them than the team that lost, up to Lv 100 each.

Each member's matchup score runs from 0 to 100: the turns it survives the ace's strongest move over
the turns it needs to knock the ace out, one more when it is slower. The team's score is its best
member's. Red, Blue and Yellow (policies/team.py) and Gold, Silver and Crystal (gen2/readiness.py)
estimate the damage their own way. A Gold run took one Lv 13 fighter and Pokémon at Lv 4 to 5 that
knew no attack into Bugsy, since Gen II gyms after Falkner had no gate at all.
"""
from __future__ import annotations

from dataclasses import dataclass

from .losses import best_level

READY = 75
LEAGUE_READY = 60
MARGIN = 10
REGROWTH = 2
CEILING = 10
DEPTH_REGROWTH = 10
# The highest level a Pokémon reaches, which caps the target a loss raises (target).
LEVEL_CAP = 100
# A gain counts as progress only for a Pokémon this close under the target, one the boss battle
# would use (band). Training a new member from a low level is not progress toward the boss.
TEAM_BAND = 2 * MARGIN
# A Pokémon under this share of its HP, or of its strong attacks' PP, is not ready for a boss.
READY_HP = 0.5
READY_PP = 0.5

LOSS, PARTNER, MATCHUP, STAMINA, DEPTH = 'loss', 'partner', 'matchup', 'stamina', 'depth'


@dataclass(frozen=True)
class Boss:
    """One boss as judge sees it.

    ``key`` names its losses (losses.py). ``ace`` is its ace's level, or None to take the best foe
    level a loss there noted. ``floor`` is the level the best fighter trains to before any loss.
    ``scores`` holds the team's matchup score for each room, one for a gym and one per League room.
    It is empty when the boss has no matchup rule, and a None in it means a score is unknown.
    ``inside`` says the team stands in the boss's room. ``opponents`` and ``low`` describe an
    optional run: the foes it faces and the lowest level among them. ``lost`` is the depth of the
    team that lost the last optional run, or None.
    """
    key: str
    ace: int | None = None
    floor: int = 0
    scores: tuple = ()
    league: bool = False
    inside: bool = False
    opponents: int = 0
    low: int = 0
    lost: int | None = None


@dataclass(frozen=True)
class Team:
    """The team as judge sees it.

    ``level`` is the best fighter's level (losses.py). ``stamina`` is the full PP of the attacks the
    Pokémon at ``Boss.low`` or over know, and ``depth`` the sum of their levels. ``size`` counts the
    party, and ``partner`` is the League partner's level, or None.
    """
    level: int
    stamina: int = 0
    depth: int = 0
    size: int = 0
    partner: int | None = None


@dataclass(frozen=True)
class Train:
    """Train before the boss. ``reason`` is LOSS, PARTNER, MATCHUP, STAMINA or DEPTH, and ``target``
    the level to train to, or the stamina or depth the team needs."""
    reason: str
    target: int


def team(party, power, pp=None, low=0, partner=None):
    """Read ``party`` into a ``Team``.

    ``power(move)`` says whether a move deals damage, which makes the Pokémon that knows it a fighter.
    ``pp(move)`` gives the full PP an attack brings to a run, since the team heals first, and 0 for a
    move that is no attack. Stamina and depth count only Pokémon at ``low`` or over, and only when
    ``low`` is given."""
    held = [mon for mon in party if not getattr(mon, 'egg', False) and mon.level >= low] if low else []
    stamina = sum(pp(move) for mon in held for move in mon.moves if move) if pp else 0
    return Team(best_level(party, power), stamina, sum(mon.level for mon in held), len(party), partner)


def loss_bar(boss, losses):
    """The level the best fighter trains to before ``boss``: its floor until a loss there."""
    lost = losses.levels().get(boss.key) if losses is not None else None
    if lost is None:
        return boss.floor
    ace = losses.aces().get(boss.key, lost) if boss.ace is None else boss.ace
    return min(ace + CEILING, max(boss.floor, lost + REGROWTH))


def matched(best):
    """Whether a best matchup score is enough for a gym."""
    return best >= READY


def matchup_level(boss):
    """The level the matchup rules train the best fighter to: the League's top ace, or MARGIN over one boss's ace."""
    return boss.ace if boss.league else boss.ace + MARGIN


def target(boss, lost=False):
    """The level a Pokémon's gain counts toward as progress before ``boss`` (progress_events.gained),
    or None when it sets none.

    It is the matchup rules' level, never under the floor. A boss with no matchup rule (no
    ``scores``) or no ace has its floor alone. After a loss to the boss, ``lost``, the team was not
    ready, so the target rises once by CEILING over the matchup level, up to LEVEL_CAP. Gold lost to
    Red again and again while Typhlosion grew from Lv 92 to 100, over the target of 91. The target
    rises only once, so a loop of losses still adds at most the levels left to it, and the loss loop
    check (stalls.LossLoop) counts the losses themselves."""
    if boss is None:
        return None
    level = max(boss.floor, matchup_level(boss)) if boss.scores and boss.ace is not None else boss.floor
    if lost and boss.ace is not None:
        level = max(boss.floor, min(LEVEL_CAP, matchup_level(boss) + CEILING))
    return level or None


def band(level):
    """The levels a gain counts toward as progress when the target is ``level``, as (lowest, highest),
    or None with no target. Only a Pokémon within TEAM_BAND under the target counts."""
    return None if level is None else (level - TEAM_BAND, level)


def judge(boss, team, losses=None):
    """None when the team may take on ``boss``, or the ``Train`` verdict of the first rule it fails."""
    if boss.league and boss.inside:
        return None
    bar = loss_bar(boss, losses)
    if team.level < bar:
        return Train(LOSS, bar)
    scores = boss.scores
    if scores and None not in scores and not boss.inside and boss.ace is not None:
        aim = matchup_level(boss)
        if boss.league:
            if team.partner is not None and team.partner < boss.ace - MARGIN and not all(map(matched, scores)):
                return Train(PARTNER, boss.ace - MARGIN)
            if team.level < aim and any(best < LEAGUE_READY for best in scores):
                return Train(MATCHUP, aim)
        elif not matched(max(scores)) and team.level < aim:
            return Train(MATCHUP, aim)
    if team.stamina < boss.opponents:
        return Train(STAMINA, boss.opponents)
    if boss.lost is not None and team.depth < (need := min(boss.lost + DEPTH_REGROWTH, 100 * team.size)):
        return Train(DEPTH, need)
    return None


def short(row):
    """Whether one Pokémon (boss.Fighter) is under READY_HP of its HP or READY_PP of its strong attacks' PP."""
    return row.hp < row.max_hp * READY_HP or bool(row.strong_max) and row.strong_pp < row.strong_max * READY_PP


def short_slots(fighters):
    """The party slots that are not ready for a boss."""
    return [index for index, row in enumerate(fighters) if short(row)]


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
