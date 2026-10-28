"""What a finished Gold, Silver or Crystal run does once the Pokédex work runs out.

Red, Blue and Yellow keep playing after the collection is done: they hunt better-DV copies of owned
species and train the best copy of each species ten levels at a time, picking among those in
rotation. This module is the same director for Gen II, plus a shiny search. A League run is the
fallback once none of those is left, so a finished run never goes quiet.

A shiny search could take tens of thousands of encounters, so it is never run to completion. Each
outing checks up to 100 wild encounters on one grass map, then lets two other activities take their
turn before another outing. An hour of simulated gameplay, including travel, is a fallback limit
if encounters are scarce. A wild shiny met at any time is still always caught, including the last
encounter of an outing. An ongoing battle finishes before switching activities.

Collection work always comes first: the plan is rebuilt every step and only reaches this module when
no Pokédex, trade, breeding or clock-gated work is left.
"""
import random

from pokecore.dvs import dv_probabilities
from pokecore.gen2.ram import calculated_stats, experience_at

from ..investment import GOOD_TAIL, MIN_UPGRADE, SEARCH_BUDGET
from .standdown import DECISIONS_PER_BATTLE, forget, hunt_key, search_expected, stand_down, standing_down, train_key

# Copies a better-DV hunt catches at most before it moves on. Its decisions are budgeted per catch by the monitor.
QUALITY_CATCHES = 3
# What a better copy is worth, per unit of drop in the species' best DV tail (planner design S3).
QUALITY_WEIGHT = 0.5
SHINY_ENCOUNTERS = 100
SHINY_BREAK_ACTIVITIES = 2
# The adventure play clock uses 60 frames per second. Pauses and playback speed do not affect this limit.
SHINY_MAX_FRAMES = 60 * 60 * 60
# Balls a hunt needs on hand to start, the Master Ball aside.
HUNT_BALLS = 5
# A copy below this level with an ordinary DV draw waits for its better-DV hunts before training.
HUNT_FIRST_BELOW = 80
WEIGHTS = {'quality': 4, 'train': 4, 'shiny': 2}
RECENT = 6


def state(policy):
    return policy.collection.setdefault('postgame', {'activity': None, 'recent': [], 'searches': {},
                                                     'shiny_break': 0, 'shiny_maps': []})


def potential(data, mon):
    """Stat total at level 100 with full stat experience, which compares copies of one species."""
    return sum(calculated_stats(data.species[mon.species]['stats'], 100, mon.dvs, (65535,) * 5))


def tail(mon):
    """The chance a random wild copy has at least this DV total, or 1 when the DVs are unreadable."""
    odds = dv_probabilities(list(mon.dvs))
    return odds['at_least_probability'] if odds else 1.0


def catch_value(odds):
    """What the next catch is worth to a species whose best copy has DV tail ``odds``.

    A wild copy's own tail is uniform from 0 to 1, so it beats the best copy with chance ``odds`` and
    then lowers the tail by ``odds / 2`` on average: an expected drop of ``odds ** 2 / 2``.
    """
    return QUALITY_WEIGHT * odds * odds / 2


# The value per decision a better-DV catch has to earn. A species met in every wild battle is worth
# hunting until its best copy reaches GOOD_TAIL, as before. A rarer one stops much sooner: a 5% Larvitar
# hunt ends once its best copy is in the top 22%, where the next catch takes about 1500 decisions and
# rarely gains anything. Early postgame training earns about this much too: a Silver Charmander took
# about 3400 decisions per ten levels, a tenth of its level 100 credit of 0.5.
WORTH = catch_value(GOOD_TAIL) / DECISIONS_PER_BATTLE


def catch_rate(odds, row, effort=(0, 0)):
    """Value per decision of the next catch from ``row``, after ``effort`` (decisions, catches) on site.

    The encounter table's rate counts as one catch already seen. A dry run then stretches the expected
    decisions per catch, so a hunt that meets or catches less than the table says stops paying.
    """
    decisions, catches = effort
    return catch_value(odds) * (1 + catches) / (search_expected(row.get('chance', 10)) + decisions)


def worth_hunting(odds, rows, effort=(0, 0)):
    """Whether a better-DV catch from the best of ``rows`` still earns WORTH per decision."""
    return any(catch_rate(odds, row, effort) >= WORTH for row in rows)


def effort(policy, species, activity=None):
    """Decisions spent on site and copies caught in better-DV hunts for ``species``, ``activity`` included.

    Decisions on the way to the map are left out, as the plan's own map count.
    """
    decisions, catches = state(policy).get('effort', {}).get(str(species), (0, 0))
    if activity is not None:
        on_site = search_expected(activity['row'].get('chance', 10))
        travel = (activity.get('expected') or on_site) - on_site
        decisions += max(0, policy.decisions - activity.get('started', policy.decisions) - travel)
        catches += activity['caught']
    return decisions, catches


def best_tail(snapshot, species):
    return min((tail(mon) for mon in held(snapshot) if mon.species == species), default=1.0)


def perfect(mon):
    return tuple(mon.dvs) == (15,) * 5


def ident(mon):
    return [mon.trainer_id, list(mon.dvs)]


def held(snapshot):
    return [mon for mon in snapshot.party + snapshot.stored if not mon.egg]


def balls(policy, snapshot):
    master = policy.data.items['MASTER_BALL']
    return sum(count for item, count in snapshot.pockets['balls'] if item != master)


def searching(policy):
    """The encounter row a better-DV or shiny search walks, or None."""
    activity = (policy.collection.get('postgame') or {}).get('activity')
    if activity and activity['kind'] in {'quality', 'shiny'}:
        return activity['row']
    return None


def quality_species(policy):
    """The species a better-DV hunt catches every copy of, or None."""
    activity = (policy.collection.get('postgame') or {}).get('activity')
    if policy.collection.get('target'):
        return None
    return activity['species'] if activity and activity['kind'] == 'quality' and not activity.get('suspended') else None


def shiny_session(policy, snapshot):
    """Whether a shiny session is walking its map, where plain wild battles are run from."""
    activity = (policy.collection.get('postgame') or {}).get('activity')
    return bool(activity and activity['kind'] == 'shiny' and not activity.get('suspended') and not policy.collection.get('target')
                and snapshot.map == activity['row']['map'])


def observe(policy, snapshot):
    """Count each wild battle once, including across a checkpoint restored during that battle."""
    activity = (policy.collection.get('postgame') or {}).get('activity')
    if not activity or activity['kind'] != 'shiny':
        return
    wild = snapshot.in_battle == 1
    if wild and not activity.get('in_battle') and shiny_session(policy, snapshot):
        activity['encounters'] = activity.get('encounters', 0) + 1
    activity['in_battle'] = wild


def stall_key(policy):
    """The stand-down key of the search in progress, or None."""
    activity = (policy.collection.get('postgame') or {}).get('activity')
    if not activity or activity['kind'] not in {'quality', 'shiny'}:
        return None
    if activity['kind'] == 'quality':
        return hunt_key(activity['species'])
    return f'shiny:{activity["row"]["map"]}'


def drop(policy):
    """End the search in progress after it stalled or its map could not be reached."""
    key = stall_key(policy)
    if key:
        stand_down(policy, key)
    finish(policy)


def finish(policy):
    data = state(policy)
    activity = data['activity']
    if activity and activity['kind'] == 'quality':
        searches = data['searches']
        searches[str(activity['species'])] = searches.get(str(activity['species']), 0) + 1
        data.setdefault('effort', {})[str(activity['species'])] = list(effort(policy, activity['species'], activity))
        forget(policy, hunt_key(activity['species']))
    if activity and activity['kind'] == 'shiny':
        data['shiny_break'] = SHINY_BREAK_ACTIVITIES
    if activity and activity['kind'] == 'train' and (policy.collection.get('training') or {}).get('postgame'):
        policy.collection['training'] = None
    from .collection import LOADING
    forget(policy, LOADING)
    data['activity'] = None


def journey(policy, snapshot, mem, Goal, current_time):
    # A finished activity hands over to the next one in the same step, so the run never idles between them.
    for _ in range(3):
        goal = step(policy, snapshot, mem, Goal, current_time)
        if goal is not False:
            return goal
    return None


def step(policy, snapshot, mem, Goal, current_time):
    """The goal of the current activity, None when nothing is left, or False when an activity just ended."""
    from .collection import while_waiting
    data = state(policy)
    activity = data['activity']
    if activity and done(policy, snapshot, activity, current_time):
        finish(policy)
        activity = None
    if activity is None:
        activity = choose(policy, snapshot, mem, current_time)
        if activity is None:
            return None
        data['activity'] = activity
        data['recent'] = (data['recent'] + [activity['kind']])[-RECENT:]
        if activity['kind'] != 'shiny':
            data['shiny_break'] = max(0, data.get('shiny_break', 0) - 1)
    kind = activity['kind']
    if kind == 'league':
        # The League loop in collection.journey carries the run on until its Hall of Fame entry.
        data['activity'] = None
        policy.collection['league_loop'] = snapshot.hall_of_fame_count + 1
        policy.collection['phase'] = 'league'
        from .collection import league_funding
        return league_funding(policy, snapshot, Goal, again=True)
    if kind == 'train':
        goal = train(policy, snapshot, mem, Goal, activity)
    else:
        from .collection import hunt
        name = policy.data.species[activity['species']]['name'] if kind == 'quality' else None
        goal = hunt(policy, snapshot, Goal, target=activity['row'],
                    label=f'Search for a stronger {name}' if name else 'Search for a shiny')
        if data['activity'] is activity:
            policy.collection['phase'] = 'upgrading' if kind == 'quality' else 'shiny hunting'
            activity['suspended'] = goal is None
    if goal is None:
        finish(policy)
        return False
    return while_waiting(policy, snapshot, mem, goal, Goal)


def done(policy, snapshot, activity, current_time):
    kind = activity['kind']
    if kind == 'train':
        project = policy.collection.get('training')
        return not project or not project.get('postgame') or project['identity'] != activity['identity']
    if kind == 'league':
        return True
    if policy.no_room(snapshot) or not snapshot.can_catch or balls(policy, snapshot) < 1:
        return True
    from .collection import matching_time
    if not matching_time(activity['row']['time'], current_time):
        return True
    if kind == 'quality':
        new = {repr(row) for row in activity['seen']}
        for mon in held(snapshot):
            if mon.species == activity['species'] and repr(ident(mon)) not in new:
                activity['seen'].append(ident(mon))
                activity['caught'] += 1
        # Each better copy makes the next one rarer, so the hunt also ends once the next catch is worth
        # less per decision than WORTH, as at a rare species whose best copy is already good, or at a
        # hunt running dry. That ends it before the stand-down budget, which is left for stuck hunts.
        species = activity['species']
        return (activity['caught'] >= QUALITY_CATCHES or standing_down(policy, hunt_key(species))
                or not worth_hunting(best_tail(snapshot, species), [activity['row']], effort(policy, species, activity)))
    shinies = sum(mon.shiny for mon in held(snapshot))
    # Older local checkpoints did not record frames. Give them one bounded outing from now.
    started = activity.setdefault('started_frame', snapshot.frame)
    return (shinies > activity['shinies'] or activity.get('encounters', 0) >= SHINY_ENCOUNTERS
            or snapshot.frame - started >= SHINY_MAX_FRAMES or standing_down(policy, stall_key(policy)))


def choose(policy, snapshot, mem, current_time):
    """Pick the next activity in rotation, the way Gen I's director spreads its projects."""
    data = state(policy)
    options = {}
    hunting = (not policy.no_room(snapshot) and snapshot.can_catch and balls(policy, snapshot) >= HUNT_BALLS)
    if hunting:
        options['quality'] = lambda: quality(policy, snapshot, current_time)
    options['train'] = lambda: trainee(policy, snapshot)
    recent = data['recent']
    rng = random.Random(policy.decisions)
    while options:
        repeat = recent[-1] if len(recent) >= 2 and recent[-1] == recent[-2] else None
        kinds = [kind for kind in options if kind != repeat] or list(options)
        weights = [WEIGHTS[kind] / (1 + recent.count(kind)) for kind in kinds]
        kind = rng.choices(kinds, weights)[0]
        activity = options.pop(kind)()
        if activity:
            return activity
    # A shiny search is filler. One wild Pokémon in 8192 is shiny, so a search earns far less per
    # decision than WORTH, and in the rotation each 100-battle outing took about 150,000 frames
    # without a catch. It runs only once no better-DV hunt or training is left.
    if hunting and data.get('shiny_break', 0) == 0:
        activity = shiny(policy, snapshot, current_time)
        if activity:
            return activity
    # A League run is the fallback once nothing else is left. In the rotation it took about one turn
    # in eleven but ran far longer than a hunt, so Gold spent 28% of its frames on rematches.
    from .collection import postgame_league
    if not any(mon.egg for mon in snapshot.party) and postgame_league(policy, snapshot, mem, current_time):
        return {'kind': 'league'}
    return None


def huntable(policy, snapshot, current_time=None):
    """Encounter rows the party can search now, grouped as {species: [rows]}."""
    from .collection import matching_time, usable
    items = dict(snapshot.items)
    result = {}
    for row in policy.data.encounters:
        if current_time is not None and not matching_time(row['time'], current_time):
            continue
        if usable(policy, snapshot, row, items):
            result.setdefault(row['species'], []).append(row)
    return result


def reachable(policy, snapshot, rows):
    """The closest searchable row with a route there, as a target, or None."""
    from .collection import encounter_points
    groups = {}
    for row in rows:
        key = (row['map'], row['method'], row['time'] == 'rare trees')
        groups.setdefault(key, {**row, 'chance': 0})['chance'] += row['chance']
    ranked = []
    for key, row in groups.items():
        route = policy.nav.route(snapshot.map, key[0])
        if route is not None:
            ranked.append((len(route) + 50 / max(1, row['chance']), key, row))
    for _, (mid, method, rare), row in sorted(ranked, key=lambda entry: entry[0])[:4]:
        points = encounter_points(policy, snapshot, mid, method, rare=rare)
        if points and policy.nav.regions.route(snapshot, mid, [point[:2] for point in points], cut=True, surf=True):
            return row
    return None


def quality(policy, snapshot, current_time):
    """A better-DV hunt for the owned species whose next catch earns the most per decision.

    A party species still goes first. A species whose next catch earns less than WORTH is left out.
    """
    from .collection import wanted
    searches = state(policy)['searches']
    rows = huntable(policy, snapshot, current_time)
    best = {}
    for mon in held(snapshot):
        if mon.species in rows and (mon.species not in best or potential(policy.data, mon) > potential(policy.data, best[mon.species])):
            best[mon.species] = mon
    candidates = []
    for species, mon in best.items():
        odds, spent = tail(mon), effort(policy, species)
        if (not worth_hunting(odds, rows[species], spent) or searches.get(str(species), 0) >= SEARCH_BUDGET
                or standing_down(policy, hunt_key(species)) or wanted(policy, snapshot, species)):
            continue
        party = any(other.species == species and other.box is None for other in held(snapshot))
        rate = max(catch_rate(odds, row, spent) for row in rows[species])
        candidates.append((not party, -rate, species, odds, spent))
    for _, _, species, odds, spent in sorted(candidates)[:6]:
        row = reachable(policy, snapshot, rows[species])
        if row and worth_hunting(odds, [row], spent):
            seen = [ident(mon) for mon in held(snapshot) if mon.species == species]
            nav = getattr(policy, 'nav', None)
            route = nav.route(snapshot.map, row['map']) if nav is not None else None
            expected = search_expected(row.get('chance', 10), len(route) if route is not None else 0)
            return {'kind': 'quality', 'species': species, 'row': dict(row, started=policy.decisions),
                    'started': policy.decisions, 'seen': seen, 'caught': 0, 'expected': expected}
    return None


def shiny(policy, snapshot, current_time):
    """A shiny session on a grass map with many species, away from the maps searched lately."""
    from .collection import encounter_points
    data = state(policy)
    maps = {}
    for rows in huntable(policy, snapshot, current_time).values():
        for row in rows:
            if row['method'] == 'grass':
                maps.setdefault(row['map'], set()).add(row['species'])
    ranked = []
    for mid, species in maps.items():
        if standing_down(policy, f'shiny:{mid}'):
            continue
        route = policy.nav.route(snapshot.map, mid)
        if route is not None:
            ranked.append((mid in data['shiny_maps'], -len(species), len(route), mid))
    for _, _, _, mid in sorted(ranked)[:4]:
        points = encounter_points(policy, snapshot, mid, 'grass')
        if points and policy.nav.regions.route(snapshot, mid, [point[:2] for point in points], cut=True, surf=True):
            data['shiny_maps'] = (data['shiny_maps'] + [mid])[-3:]
            row = {'map': mid, 'method': 'grass', 'time': 'any', 'species': None,
                   'chance': 100, 'started': policy.decisions}
            return {'kind': 'shiny', 'row': row, 'started': policy.decisions, 'started_frame': snapshot.frame,
                    'encounters': 0, 'in_battle': False,
                    'shinies': sum(mon.shiny for mon in held(snapshot))}
    return None


def trainee(policy, snapshot):
    """Train the best copy of a species to its next multiple of ten levels, as Gen I does.

    A species is skipped when a level 100 copy is already about as strong, and a copy with ordinary
    DVs waits while better-DV hunts for it remain, so the training goes to the copy worth keeping.
    """
    data = policy.data
    searches = state(policy)['searches']
    rows = huntable(policy, snapshot)
    sealed = len(snapshot.party) >= 6 and bool(policy.no_room(snapshot))
    groups = {}
    for mon in held(snapshot):
        groups.setdefault(mon.species, []).append(mon)
    choices = []
    for species, copies in groups.items():
        best = max(copies, key=lambda mon: (potential(data, mon), mon.level))
        if best.level >= 100 or standing_down(policy, train_key(ident(best))) or best.box is not None and sealed:
            continue
        top = max((potential(data, mon) for mon in copies if mon.level >= 100), default=None)
        if top is not None and not perfect(best) and potential(data, best) <= top * (1 + MIN_UPGRADE):
            continue
        if (best.level < HUNT_FIRST_BELOW and species in rows and worth_hunting(tail(best), rows[species], effort(policy, species))
                and searches.get(str(species), 0) < SEARCH_BUDGET):
            continue
        goal = min(100, (best.level // 10 + 1) * 10)
        cost = experience_at(goal, data.species[species]['growth']) - best.experience
        choices.append((best.box is not None, cost, species, ident(best), goal))
    if not choices:
        return None
    _, _, species, identity, goal = min(choices)
    return {'kind': 'train', 'identity': identity, 'species': species, 'level_goal': goal}


def train(policy, snapshot, mem, Goal, activity):
    from . import training
    project = policy.collection.get('training')
    fresh = not project or not project.get('postgame')
    if fresh:
        policy.collection['training'] = {'identity': activity['identity'], 'target': activity['species'], 'item': None,
                                         'species': activity['species'], 'terminal': True,
                                         'level_goal': activity['level_goal'], 'postgame': True}
    goal = training.journey(policy, snapshot, mem, Goal, terminal=True)
    if goal is None and fresh:
        # The trainee could not even start, so it waits before it is picked again.
        stand_down(policy, train_key(activity['identity']))
    return goal
