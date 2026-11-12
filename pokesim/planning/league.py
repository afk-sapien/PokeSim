"""The rules around the bosses, one copy for both generations.

This module holds the boss order, the next boss, the readiness target, boss and story training, the
loss note and the boss gate. Each generation gives a boss table (``Table``) and a matchup scorer: Red,
Blue and Yellow keep theirs in policies/progression.py and policies/team.py, Gold, Silver and Crystal
in gen2/readiness.py. The oracle that judges a boss is readiness.py, the levels that lost are kept by
losses.py, and the heal check before a boss is boss.py. Each generation still words its own goals.

A table names its maps the way its generation reads them: Red, Blue and Yellow by map id, Gold,
Silver and Crystal by map constant. Every ``here`` passed in uses the same form.

Two settings stay different between the generations (docs/design/one-bot.md, Differences that stay):

1. ``partner``: before the League, Red, Blue and Yellow train a sturdy second battler, the partner,
   while its level is low and a room's matchup is poor (readiness.PARTNER). Gold, Silver and Crystal
   name none.
2. ``rematch``: a postgame League run in Gold, Silver and Crystal also needs a full attack's PP for
   each opponent and, after a loss there, a deeper team (readiness.STAMINA and DEPTH). Red, Blue and
   Yellow have no such gate.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, NamedTuple

from .boss import UNREADY, Gate, healed_event, unready_event
from .losses import best_level, boss_trainer
from .readiness import Boss, band, judge, target, team

LEAGUE = 'league'


@dataclass(frozen=True)
class Row:
    """One boss in a generation's table.

    ``key`` names its losses, and the League's rooms share the key 'league'. ``name`` is how the
    training goal names it and ``ace`` the level of its ace when the cartridge gives none.
    ``training`` is the map the team trains on before it, one name or a tuple of them. ``rooms`` are
    the maps it battles on. ``badge`` is the badge bit that marks it won, 0 when the Hall of Fame
    does, or None when nothing does. ``floor`` is the level the best fighter trains to before any
    loss. ``scores`` holds what the scorer reads for each room the matchup rule judges, one for a gym
    and one per League room, and is empty when no matchup rule judges it. ``aim`` makes a level gain
    count toward the matchup level even so (``readiness_target``).
    """
    key: str
    name: str
    ace: int
    training: object
    rooms: frozenset
    badge: int | None
    floor: int = 0
    scores: tuple = ()
    aim: bool = False

    @property
    def league(self):
        return self.key == LEAGUE


@dataclass(frozen=True)
class Table:
    """A generation's bosses in story order, and the settings that differ between generations.

    ``goals`` are the goal keys that end in a boss battle or lead into the League's. ``league`` are
    the maps inside the League, where nothing turns back. A boss goal starts with ``challenge`` when
    the boss check guards it, or any boss goal does when it is None. ``partner`` gives the base HP of
    a species, by which the League partner is chosen, or is None when the League takes no partner.
    ``rematch`` turns on the stamina and depth gate of a postgame League run. ``rematches`` are the
    goal keys of that run, room by room. The boss check guards them as it guards the League row's own
    goals, and asks for a party restored in full before the first room (check). They name no row for
    training, since league.run judges a postgame run. ``generation`` names the boss trainer classes
    (losses.BOSS_CLASSES).
    """
    generation: int
    rows: tuple
    goals: frozenset
    league: frozenset
    challenge: str | None = None
    partner: Callable[[int], int] | None = None
    rematch: bool = False
    rematches: frozenset = frozenset()

    def row(self, key):
        """The row a boss goal ``key`` names, or None for any other goal."""
        if key not in self.goals:
            return None
        key = boss_key(key)
        return next((row for row in self.rows if row.key == key), None)

    def room(self, here):
        """The row of the boss that battles on ``here``, or None."""
        return next((row for row in self.rows if here in row.rooms), None)

    @property
    def league_row(self):
        return next(row for row in self.rows if row.league)


class Training(NamedTuple):
    """Train before a goal: the boss ``row``, or None for a story goal, the oracle's ``verdict`` and
    the map ``where`` the team trains."""
    row: Row | None
    verdict: object
    where: object


def boss_key(key):
    """The key a boss goal keeps its losses under: 'league' for any League room."""
    return LEAGUE if key.startswith('league_') else key


def won(row, snapshot):
    if row.badge is None:
        return False
    if row.badge == 0:
        return bool(getattr(snapshot, 'hall_of_fame_count', 0))
    return bool(snapshot.badges & row.badge)


def next_row(table, snapshot):
    """The first boss in story order not won yet, or None once all are."""
    return next((row for row in table.rows if not won(row, snapshot)), None)


def plain(row, ace=None):
    """The boss ``row`` as the oracle sees it before the scores are read."""
    return Boss(row.key, row.ace if ace is None else ace(row), floor=row.floor,
                scores=(None,) * len(row.scores), league=row.league)


def readiness_target(table, snapshot, ace=None, losses=None):
    """The level a Pokémon's gain counts toward as progress (readiness.target), or None.

    A boss with ``aim`` counts gains toward the matchup level over its ace with no matchup rule, as
    Gold, Silver and Crystal do before Red. A loss to the next boss that ``losses`` keeps raises the
    target, since the boss is still not won. Only the progress rows read it, so play does not change."""
    row = next_row(table, snapshot)
    return None if row is None else row_target(row, ace, losses)


def row_target(row, ace=None, losses=None):
    """The readiness target of the boss ``row``, won or not, raised once after a loss ``losses`` keeps."""
    boss = plain(row, ace)
    if row.aim and not boss.scores:
        boss = replace(boss, scores=(None,))
    return target(boss, losses is not None and row.key in losses.levels())


def top_level(snapshot):
    """The party's highest level, eggs aside, or 0."""
    return max((mon.level for mon in getattr(snapshot, 'party', ()) if not getattr(mon, 'egg', False)), default=0)


def gain_band(table, snapshot, ace=None, losses=None):
    """The levels a Pokémon's gain counts toward as progress (readiness.band), or None: from near the
    party's best level up to the readiness target."""
    return band(readiness_target(table, snapshot, ace, losses), top_level(snapshot))


def boss(table, row, here, score, ace=None):
    """The boss ``row`` as the oracle judges it, with the scores ``score`` gives for each of its
    rooms. The team is inside when ``here`` is one of its rooms, or anywhere in the League."""
    inside = here in (table.league if row.league else row.rooms)
    return replace(plain(row, ace), scores=tuple(score(room) for room in row.scores), inside=inside)


def partner(party, base_hp):
    """The slot of the sturdy partner to train beside the strongest, chosen the same way whatever the
    party order, or None.

    The partner is moved to the lead, so a choice that depended on position changed once it was
    made: with Muk and Charizard both at level 54, Lapras and Muk traded the lead forever."""
    bulk = lambda i: (party[i].max_hp + party[i].attack, party[i].level, party[i].experience)
    # Ties go to the later partner, so that an identical twin already leading stays the one to train.
    strongest = max(range(len(party)), key=lambda i: (party[i].level, *bulk(i), i))
    candidates = [i for i, mon in enumerate(party) if i != strongest and base_hp(mon.species) >= 90]
    return max(candidates, key=lambda i: (bulk(i), -i)) if candidates else None


def training(table, snapshot, goal_key, here, power, losses, score, ace=None):
    """Training before the goal ``goal_key``, or None once the oracle finds the team ready.

    A boss goal is judged by its loss bar and its matchup scores, and any other goal by the loss bar
    a loss on the way to it set. Inside the League nothing turns back, so its rooms carry on. A story
    goal trains where the team would before the next boss not won, or the League once all are."""
    if goal_key is None or losses is None or here in table.league:
        return None
    row = table.row(goal_key)
    if row is None and goal_key not in losses.levels():
        # With no loss on the way, a story goal's bar is no level at all, so the party need not be read.
        return None
    party = snapshot.party
    if row is None:
        verdict = judge(Boss(goal_key), team(party, power), losses)
        if verdict is None:
            return None
        ahead = next_row(table, snapshot) or table.league_row
        return Training(None, verdict, ahead.training)
    slot = partner(party, table.partner) if row.league and table.partner else None
    fighters = team(party, power, partner=None if slot is None else party[slot].level)
    verdict = judge(boss(table, row, here, score, ace), fighters, losses)
    return None if verdict is None else Training(row, verdict, row.training)


def run(table, boss, party, power, pp, lineup, lost):
    """A postgame League run against ``boss`` and the team that would take it, as the oracle reads them.

    With ``rematch`` set, nothing restores PP inside the League. A level 100 Vaporeon beside Pokémon
    too weak to face the Elite Four ran out of attacks at Lance and the battle never ended. So the
    oracle counts the attacks the Pokémon at the League's lowest level or over know, at full PP since
    the boss check restores the party in full at the last Pokémon Center before the run (check).
    ``lineup`` gives the opponents and that lowest level. A live Crystal run took one level 71
    Poliwhirl and its trainees back to Lance every twenty minutes and lost each time, so a lost run
    leaves ``lost``, the depth of the team that lost, for the next one to beat."""
    if not table.rematch:
        return boss, team(party, power)
    opponents, low = lineup
    return replace(boss, opponents=opponents, low=low, lost=lost), team(party, power, pp, low)


def note_loss(table, losses, goal_key, here, snapshot, power, rooms=None):
    """Remember the best fighter level that lost to the boss the goal names, which raises its bar.

    A loss is a black out or a battle that cannot end in the boss's room, or anywhere in the League.
    ``rooms`` are where a boss goal's loss counts, its boss's own rooms when None. A reload into a
    battle leaves no goal yet, so then the room alone names the boss. A loss to the rival or a
    villain elsewhere counts against the goal under way, which waits on the win."""
    row = table.row(goal_key)
    if row is not None:
        inside = here in (row.rooms if rooms is None else rooms)
    else:
        row = table.room(here)
        inside = row is not None
    if inside:
        losses.note(row.key, best_level(snapshot.party, power))
    elif goal_key is not None and boss_trainer(snapshot, table.generation) is not None:
        losses.note(goal_key, best_level(snapshot.party, power), snapshot.enemy_level)


def challenges(table, goal):
    """Whether ``goal`` takes on its boss, which the boss check guards. A postgame League run's goals
    (``rematches``) take on the League."""
    return goal is not None and (goal.key in table.rematches or goal.key in table.goals
                                 and (table.challenge is None or goal.title.startswith(table.challenge)))


def check(table, owner, goal, fighters, reachable, *, where, inside, center, treatment, title, names,
          quiet=False):
    """The boss check before ``goal`` (boss.py): READY, HEAL or UNREADY, and the journal rows it writes.

    A party with a Pokémon under half its HP or its strong attacks' PP heals first when a nurse can
    be reached (``reachable``), or, between League rooms (``inside``), when ``treatment`` says the bag
    holds an item that treats it. Otherwise it goes in as it stands, and the journal says so once per
    leg. Each Pokémon Center the party steps into (``center``, at ``where``) starts a leg with fresh
    trips. ``title`` and ``names`` give the goal's title and the party's names for the journal. A
    ``quiet`` check writes nothing and leaves a finished heal trip to be written by the next."""
    gate = getattr(owner, 'boss_gate', None)
    if gate is None:
        gate = owner.boss_gate = Gate()
    key = goal.key if challenges(table, goal) else None
    supply = key is not None and inside and treatment()
    # Nothing restores PP inside the League, and run counts a postgame run's attacks at full PP. So at
    # a Pokémon Center before that run, a party short of full heals first, not only one under half. A
    # Gold Typhlosion walked in from the Indigo Plateau Center with Earthquake at 8 of 10 and
    # Flamethrower at 12 of 15, which the half rule calls ready.
    full = key in table.rematches and center
    verdict = gate.decide(key, fighters, reachable, where=where, center=center, supply=supply, full=full)
    rows = []
    if verdict == UNREADY and not quiet and gate.note():
        rows.append(unready_event(title(), fighters, names()))
    if not quiet and gate.healed():
        rows.append(healed_event(title(), full))
    return verdict, rows
