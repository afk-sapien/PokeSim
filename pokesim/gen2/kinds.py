"""The rules of each Gen II goal kind: the Pokédex hunt's target, training and the postgame activities.

Gen II keeps three goal records in its collection state, each a GoalRun (planning/goals.py) with its
kind's rules from here: the hunt target ``collection['target']``, the training project
``collection['training']`` and the postgame activity ``collection['postgame']['activity']``. The other
collection rungs keep their own tables.

``run`` names the fields a kind writes once its goal is under way. Every other field is a param, and
GoalRun refuses a write to one. The design is in docs/design/typed-goals.md.
"""
from __future__ import annotations

from ..pcvalue import RARITY_STEP
from ..planning.goals import GoalRun, Rules
from . import postgame as pg
from .standdown import forget, hunt_key, standing_down, train_key


class Kind(Rules):
    """A Gen II goal kind's rules."""
    # The tier progress_events files the goal's rows under.
    tier = ''
    # A Gen II record names no kind of its own, and a hunt target's ``method`` is its encounter method,
    # a param like any other.
    spec_fields = frozenset()

    # A pickled goal finds its kind's one rules object again by name.
    def __reduce__(self):
        return rules, (self.kind,)

    def spec_key(self, record):
        return self.goal_key(record)[0]

    def goal_key(self, record):
        """The goal's key and tier for the goal rows in progress_events."""
        return None, self.tier

    def counters(self, policy, snapshot, record):
        """The target species and DV rule the encounter counters take, or None (standdown.hunt)."""
        return None


class Hunt(Kind):
    """The Pokédex hunt's target, an encounter row the hunt walks until it catches the species."""
    kind = 'hunt'
    # The walk's expected decisions, which a target from an older save or a replay fills in later.
    run = frozenset({'expected'})

    def goal_key(self, record):
        return hunt_key(record['species']), ''

    def counters(self, policy, snapshot, record):
        return record['species'], None


class Training(Kind):
    """A training project, which levels one Pokémon toward its evolution, item or level goal."""
    kind = 'training'
    run = frozenset({'site', 'refused', 'experience', 'gained'})

    def goal_key(self, record):
        return train_key(record['identity']), ''


class TerminalTraining(Training):
    """Training with no evolution to reach, so the trainee's species follows it as it evolves."""
    kind = 'training.terminal'
    run = Training.run | {'species', 'target'}


class Activity(Kind):
    """A postgame activity. A kind with no class of its own walks its row as a search, as the old
    switch's last branch did."""
    kind = 'postgame'
    # Every activity is suspended while other work holds the plan (policy.story).
    run = frozenset({'suspended'})
    phase = 'shiny hunting'

    def goal_key(self, record):
        return record['kind'], self.tier

    def search_row(self, activity):
        """The encounter row a better-DV or shiny search walks, or None."""
        return None

    def stall_key(self, activity):
        """The stand-down key of a search, or None."""
        return None

    def observe(self, policy, snapshot, activity):
        """Watch the step for the activity, as each one is observed even while other work holds the plan."""

    def picked(self, policy, activity):
        """Note that the arbiter picked the activity."""

    def outranked(self, policy, snapshot, activity, current_time):
        """Whether another offer takes the turn from the activity in progress."""
        return False

    def done(self, policy, snapshot, activity, current_time):
        if policy.no_room(snapshot) or not snapshot.can_catch or pg.balls(policy, snapshot) < 1:
            return True
        from .collection import matching_time
        if not matching_time(activity['row']['time'], current_time):
            return True
        return self.searched(policy, snapshot, activity)

    def searched(self, policy, snapshot, activity):
        shinies = sum(mon.shiny for mon in pg.held(snapshot))
        return shinies > activity['shinies'] or standing_down(policy, self.stall_key(activity))

    def finish(self, policy, data, activity):
        data['finished'] += 1

    def label(self, policy, activity):
        return 'Search for a shiny'

    def goal(self, policy, snapshot, mem, Goal, data, activity):
        from .collection import hunt
        goal = hunt(policy, snapshot, Goal, target=activity['row'], label=self.label(policy, activity))
        if data['activity'] is activity:
            policy.collection['phase'] = self.phase
            activity['suspended'] = goal is None
        return goal

    def step(self, policy, snapshot, mem, Goal, data, activity):
        """The activity's goal, or False once it just ended."""
        goal = self.goal(policy, snapshot, mem, Goal, data, activity)
        if goal is None:
            pg.finish(policy)
            return False
        from .collection import while_waiting
        return while_waiting(policy, snapshot, mem, goal, Goal)


class Quality(Activity):
    """A better-DV hunt, which ends at its first better copy of its species."""
    kind = 'postgame.quality'
    run = Activity.run | {'seen', 'caught', 'better', 'counted', 'tail'}
    phase = 'upgrading'

    def search_row(self, activity):
        return activity['row']

    def stall_key(self, activity):
        return hunt_key(activity['species'])

    def counters(self, policy, snapshot, record):
        species = record['species']
        return species, lambda raw: pg.hunt_catch(policy, snapshot, species, raw)

    def searched(self, policy, snapshot, activity):
        new = {repr(row) for row in activity['seen']}
        species = activity['species']
        # Older saves did not record the tail the hunt set out to beat, so they beat today's best.
        start = activity.setdefault('tail', pg.best_tail(policy.data, snapshot, species))
        better = False
        for mon in pg.held(snapshot):
            if mon.species == species and repr(pg.ident(mon)) not in new:
                activity['seen'].append(pg.ident(mon))
                activity['caught'] += 1
                # Better as the PC counts it: at least RARITY_STEP times rarer (pcvalue.worth).
                better = better or pg.tail(policy.data, mon) * RARITY_STEP <= start
        # The hunt ends at its first better copy, which makes the next one rarer, so the arbiter weighs
        # it afresh. It also ends once the next catch is worth less per decision than WORTH, as at a hunt
        # running dry. That ends it before the stand-down budget, which is left for stuck hunts.
        activity['better'] = activity.get('better') or better
        return (activity['better'] or standing_down(policy, hunt_key(species))
                or not pg.worth_hunting(pg.best_tail(policy.data, snapshot, species), [activity['row']],
                                        pg.effort(policy, species, activity)))

    def finish(self, policy, data, activity):
        super().finish(policy, data, activity)
        species = str(activity['species'])
        data['searches'][species] = data['searches'].get(species, 0) + 1
        data.setdefault('effort', {})[species] = list(pg.effort(policy, activity['species'], activity))
        forget(policy, hunt_key(activity['species']))

    def label(self, policy, activity):
        return f'Search for a stronger {policy.data.species[activity["species"]]["name"]}'


class Shiny(Activity):
    """A shiny session on one grass map, which runs until it meets a shiny or stalls."""
    kind = 'postgame.shiny'
    run = Activity.run | {'encounters', 'in_battle', 'asked', 'counted'}

    def search_row(self, activity):
        return activity['row']

    def stall_key(self, activity):
        return f'shiny:{activity["row"]["map"]}'

    def counters(self, policy, snapshot, record):
        from ..shiny import shiny_bytes
        return None, shiny_bytes

    def observe(self, policy, snapshot, activity):
        # Count each wild battle once, including across a checkpoint restored during that battle.
        wild = snapshot.in_battle == 1
        if wild and not activity.get('in_battle') and pg.shiny_session(policy, snapshot):
            activity['encounters'] = activity.get('encounters', 0) + 1
        activity['in_battle'] = wild

    def picked(self, policy, activity):
        data = pg.state(policy)
        data['shiny_maps'] = (data['shiny_maps'] + [activity['row']['map']])[-3:]

    def outranked(self, policy, snapshot, activity, current_time):
        # A shiny search has no end of its own short of a shiny, so this is what hands the turn back,
        # asked once after each of its battles.
        if activity.get('in_battle') or snapshot.in_battle:
            return False
        met = activity.get('encounters', 0)
        if met <= activity.get('asked', 0):
            return False
        activity['asked'] = met
        found = pg.offers(policy, snapshot, current_time, shiny_search=False)
        options = ([pg.candidate(policy, snapshot, other) for other in found.values()]
                   + [pg.candidate(policy, snapshot, activity)])
        pick = pg.arbiter.choose(options, snapshot)
        return pick is not None and pick.key != 'shiny'

    def finish(self, policy, data, activity):
        super().finish(policy, data, activity)
        forget(policy, self.stall_key(activity))


class Train(Activity):
    """Postgame training of the best copy of a species to its next multiple of ten levels."""
    kind = 'postgame.train'

    def done(self, policy, snapshot, activity, current_time):
        project = policy.collection.get('training')
        return not project or not project.get('postgame') or project['identity'] != activity['identity']

    def finish(self, policy, data, activity):
        super().finish(policy, data, activity)
        if (policy.collection.get('training') or {}).get('postgame'):
            policy.collection['training'] = None

    def goal(self, policy, snapshot, mem, Goal, data, activity):
        return pg.train(policy, snapshot, mem, Goal, activity)


class Marathon(Activity):
    """A Johto Marathon race, whose clock runs on every step."""
    kind = 'postgame.marathon'
    run = Activity.run | {'checkpoint', 'race_frames', 'gains', 'healed_here', 'progress_frame'}
    tier = 'RACE'

    def observe(self, policy, snapshot, activity):
        from . import marathon
        marathon.observe(policy, snapshot, activity)
        # The race ends here even while other work holds the plan, so it never outruns its budget.
        if snapshot.valid and marathon.done(policy, snapshot, activity):
            pg.finish(policy)

    def done(self, policy, snapshot, activity, current_time):
        from . import marathon
        return marathon.done(policy, snapshot, activity)

    def finish(self, policy, data, activity):
        from . import marathon
        marathon.finish(policy, activity)

    def step(self, policy, snapshot, mem, Goal, data, activity):
        # A race goes straight to the next checkpoint. Clock-gated filler waits until it is over.
        from . import marathon
        policy.collection['phase'] = 'racing'
        return marathon.goal(policy, activity, Goal)


class League(Activity):
    """A League run, the fallback once the arbiter has nothing else."""
    kind = 'postgame.league'

    def done(self, policy, snapshot, activity, current_time):
        return True

    def step(self, policy, snapshot, mem, Goal, data, activity):
        # The League loop in collection.journey carries the run on until its Hall of Fame entry.
        data['activity'] = None
        data['finished'] += 1
        policy.collection['league_loop'] = snapshot.hall_of_fame_count + 1
        policy.collection['phase'] = 'league'
        from .collection import league_funding
        return league_funding(policy, snapshot, Goal, again=True)


HUNT = Hunt()
TRAINING = Training()
TERMINAL = TerminalTraining()
OTHER = Activity()
ACTIVITIES = {rules.kind.removeprefix('postgame.'): rules for rules in (Quality(), Shiny(), Train(), Marathon(), League())}
RULES = {rules.kind: rules for rules in (HUNT, TRAINING, TERMINAL, OTHER, *ACTIVITIES.values())}


def rules(kind):
    """The rules of the kind named ``kind``."""
    return RULES[kind]


def activity(record):
    """The rules of the postgame activity ``record``."""
    return ACTIVITIES.get(record['kind'], OTHER)


def training(record):
    """The rules of the training project ``record``."""
    return TERMINAL if record.get('terminal') else TRAINING


def start(rules, record):
    """A goal of ``rules`` from ``record``, which a save or an offer built, or None for no record."""
    if record is None or isinstance(record, GoalRun):
        return record
    return GoalRun.start(record, rules)


def target(record):
    """The hunt target's goal from ``record``."""
    return start(HUNT, record)


def project(record):
    """The training project's goal from ``record``."""
    return start(training(record), record)


def running(collection):
    """The rules and record of the goal in progress: the postgame activity, else the hunt target, else
    the training project. (None, None) when there is none."""
    record = (collection.get('postgame') or {}).get('activity')
    if record:
        return activity(record), record
    if record := collection.get('target'):
        return HUNT, record
    if record := collection.get('training'):
        return training(record), record
    return None, None


def adopt(collection):
    """Make the goal records in a loaded collection state GoalRuns, after standdown.migrate tidied them."""
    if collection.get('target'):
        collection['target'] = target(collection['target'])
    if collection.get('training'):
        collection['training'] = project(collection['training'])
    postgame = collection.get('postgame')
    if isinstance(postgame, dict) and postgame.get('activity'):
        postgame['activity'] = start(activity(postgame['activity']), postgame['activity'])
    tower = collection.get('tower')
    if isinstance(tower, dict) and tower.get('previous_training'):
        tower['previous_training'] = project(tower['previous_training'])
