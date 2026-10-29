"""What a finished Gold, Silver or Crystal run does once the Pokédex work runs out.

Red, Blue and Yellow keep playing after the collection is done: they hunt better-DV copies of owned
species and train the best copy of each species ten levels at a time. This module is the same work
for Gen II, plus a shiny search. The utility arbiter (planning/arbiter.py) picks among them:

1. A due Johto Marathon, in Tier.RACE, outranks every upgrade. Its six hour cooldown keeps it rare.
2. Training is Tier.UPGRADE and goes ahead of better-DV hunts, as in Red, Blue and Yellow.
3. Better-DV hunts sit in HUNT_TIER, the same constant Gen I uses. A shiny search shares that tier
   at a value so small that it runs only once no hunt, training or race is offered.
4. A League run is the fallback once the arbiter has nothing, so a finished run never goes quiet.

A better-DV hunt ends at its first better copy, so the arbiter weighs the next one afresh. A shiny
search runs until it meets a shiny or stalls, and the arbiter is asked again after each of its wild
battles, so a race that comes due or any other offer takes over. A wild shiny met at any time is
still always caught. An ongoing battle finishes before switching activities.

Collection work always comes first: the plan is rebuilt every step and only reaches this module when
no Pokédex, trade, breeding or clock-gated work is left.
"""
from pokecore.dvs import dv_probabilities
from pokecore.gen2.ram import calculated_stats, experience_at

from ..investment import GOOD_TAIL, MIN_UPGRADE, SEARCH_BUDGET
from ..planning import arbiter, values
from ..planning.arbiter import Candidate, Tier
from ..planning.values import QUALITY, quality_catch
from ..policies.collection import HUNT_TIER
from .standdown import DECISIONS_PER_BATTLE, forget, hunt_key, search_expected, stand_down, standing_down, train_key

# What a better copy is worth, per unit of drop in the species' best DV tail (planner design S3).
QUALITY_WEIGHT = QUALITY
# One wild Pokémon in this many is shiny.
SHINY_ODDS = 8192
# Balls a hunt needs on hand to start, the Master Ball aside.
HUNT_BALLS = 5
# A copy below this level with an ordinary DV draw waits for its better-DV hunts before training.
HUNT_FIRST_BELOW = 80


def state(policy):
    data = policy.collection.setdefault('postgame', {'activity': None, 'searches': {}, 'shiny_maps': []})
    # Activities finished, which a marathon waits on. Older saves only kept the recent ones, so they
    # count those. The rotation's recent list and shiny break are gone with the rotation.
    data.setdefault('finished', len(data.get('recent', ())))
    data.pop('recent', None)
    data.pop('shiny_break', None)
    data.setdefault('searches', {})
    data.setdefault('shiny_maps', [])
    return data


def potential(data, mon):
    """Stat total at level 100 with full stat experience, which compares copies of one species."""
    return sum(calculated_stats(data.species[mon.species]['stats'], 100, mon.dvs, (65535,) * 5))


def tail(mon):
    """The chance a random wild copy has at least this DV total, or 1 when the DVs are unreadable."""
    odds = dv_probabilities(list(mon.dvs))
    return odds['at_least_probability'] if odds else 1.0


def catch_value(odds):
    """What the next catch is worth to a species whose best copy has DV tail ``odds``, as the arbiter values it."""
    return quality_catch(odds)


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
    """Count each wild battle once, including across a checkpoint restored during that battle.

    A marathon is observed on every step too, so its race clock runs on while other work suspends it.
    """
    activity = (policy.collection.get('postgame') or {}).get('activity')
    if activity and activity['kind'] == 'marathon':
        from . import marathon
        marathon.observe(policy, snapshot, activity)
        # The race ends here even while other work holds the plan, so it never outruns its budget.
        if snapshot.valid and marathon.done(policy, snapshot, activity):
            finish(policy)
        return
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
    if activity and activity['kind'] == 'marathon':
        from . import marathon
        marathon.finish(policy, activity)
    elif activity:
        data['finished'] += 1
    if activity and activity['kind'] == 'quality':
        searches = data['searches']
        searches[str(activity['species'])] = searches.get(str(activity['species']), 0) + 1
        data.setdefault('effort', {})[str(activity['species'])] = list(effort(policy, activity['species'], activity))
        forget(policy, hunt_key(activity['species']))
    if activity and activity['kind'] == 'shiny':
        forget(policy, f'shiny:{activity["row"]["map"]}')
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
    if activity and (done(policy, snapshot, activity, current_time) or outranked(policy, snapshot, activity, current_time)):
        finish(policy)
        activity = None
    if activity is None:
        activity = choose(policy, snapshot, mem, current_time)
        if activity is None:
            return None
        data['activity'] = activity
    kind = activity['kind']
    if kind == 'league':
        # The League loop in collection.journey carries the run on until its Hall of Fame entry.
        data['activity'] = None
        data['finished'] += 1
        policy.collection['league_loop'] = snapshot.hall_of_fame_count + 1
        policy.collection['phase'] = 'league'
        from .collection import league_funding
        return league_funding(policy, snapshot, Goal, again=True)
    if kind == 'marathon':
        # A race goes straight to the next checkpoint. Clock-gated filler waits until it is over.
        from . import marathon
        policy.collection['phase'] = 'racing'
        return marathon.goal(policy, activity, Goal)
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
    if kind == 'marathon':
        from . import marathon
        return marathon.done(policy, snapshot, activity)
    if policy.no_room(snapshot) or not snapshot.can_catch or balls(policy, snapshot) < 1:
        return True
    from .collection import matching_time
    if not matching_time(activity['row']['time'], current_time):
        return True
    if kind == 'quality':
        new = {repr(row) for row in activity['seen']}
        species = activity['species']
        # Older saves did not record the tail the hunt set out to beat, so they beat today's best.
        start = activity.setdefault('tail', best_tail(snapshot, species))
        better = False
        for mon in held(snapshot):
            if mon.species == species and repr(ident(mon)) not in new:
                activity['seen'].append(ident(mon))
                activity['caught'] += 1
                better = better or tail(mon) < start
        # The hunt ends at its first better copy, which makes the next one rarer, so the arbiter weighs
        # it afresh. It also ends once the next catch is worth less per decision than WORTH, as at a hunt
        # running dry. That ends it before the stand-down budget, which is left for stuck hunts.
        activity['better'] = activity.get('better') or better
        return (activity['better'] or standing_down(policy, hunt_key(species))
                or not worth_hunting(best_tail(snapshot, species), [activity['row']], effort(policy, species, activity)))
    shinies = sum(mon.shiny for mon in held(snapshot))
    return shinies > activity['shinies'] or standing_down(policy, stall_key(policy))


def hunting(policy, snapshot):
    """Whether a hunt may start: room for a catch, a ball pocket that can catch and HUNT_BALLS balls."""
    return not policy.no_room(snapshot) and snapshot.can_catch and balls(policy, snapshot) >= HUNT_BALLS


def offers(policy, snapshot, current_time, shiny_search=True):
    """What each postgame activity would start now, by kind. Asking changes no saved state."""
    found = {}
    if hunting(policy, snapshot):
        found['quality'] = quality(policy, snapshot, current_time)
    found['train'] = trainee(policy, snapshot)
    from . import marathon
    if marathon.eligible(policy, snapshot, state(policy)['finished']):
        found['marathon'] = marathon.candidate(snapshot)
    if shiny_search and hunting(policy, snapshot):
        found['shiny'] = shiny(policy, snapshot, current_time)
    return {kind: activity for kind, activity in found.items() if activity}


def choose(policy, snapshot, mem, current_time):
    """The activity the arbiter picks, or a League run once it has nothing."""
    found = offers(policy, snapshot, current_time)
    options = [candidate(policy, snapshot, activity) for activity in found.values()]
    pick = arbiter.choose(options, snapshot)
    shadow = getattr(policy, 'shadow', None)
    if shadow is not None and pick is not None:
        # The arbiter decides here, so this point always agrees, as Gen I's collection point does.
        shadow.compare('postgame', lambda: options, pick.key)
    if pick is not None:
        activity = found[pick.key]
        if activity['kind'] == 'shiny':
            data = state(policy)
            data['shiny_maps'] = (data['shiny_maps'] + [activity['row']['map']])[-3:]
        return activity
    # A League run is the fallback once nothing else is left. In the old rotation it took about one
    # turn in eleven but ran far longer than a hunt, so Gold spent 28% of its frames on rematches.
    from .collection import postgame_league
    if not any(mon.egg for mon in snapshot.party) and postgame_league(policy, snapshot, mem, current_time):
        return {'kind': 'league'}
    return None


def outranked(policy, snapshot, activity, current_time):
    """Whether another offer outranks the shiny search in progress, asked once after each of its battles.

    A shiny search has no end of its own short of a shiny, so this is what hands the turn back.
    """
    if activity['kind'] != 'shiny' or activity.get('in_battle') or snapshot.in_battle:
        return False
    met = activity.get('encounters', 0)
    if met <= activity.get('asked', 0):
        return False
    activity['asked'] = met
    found = offers(policy, snapshot, current_time, shiny_search=False)
    options = [candidate(policy, snapshot, other) for other in found.values()] + [candidate(policy, snapshot, activity)]
    pick = arbiter.choose(options, snapshot)
    return pick is not None and pick.key != 'shiny'


# Estimates in decisions, the unit of the postgame's own search costs: ten levels of training, from a
# Silver Charmander that took about 3400 decisions per ten levels.
TRAIN_DECISIONS = 3400


def candidate(policy, snapshot, activity):
    """The arbiter's candidate for a postgame activity, in decisions.

    A better-DV hunt is worth each catch's expected drop in the best DV tail, for the catches it takes
    to find one better copy, priced from the rate on site after the effort spent there. Training is
    worth its share of the level 100 credit. A race and a shiny search are worth SMALL, and their tiers
    rank them.
    """
    kind = activity['kind']
    if kind == 'quality':
        species = activity['species']
        mon = max((mon for mon in held(snapshot) if mon.species == species), key=lambda mon: potential(policy.data, mon))
        odds = tail(mon)
        needed = 1 / max(odds, 1e-6)
        decisions, catches = effort(policy, species)
        per_catch = (search_expected(activity['row'].get('chance', 10)) + decisions) / (1 + catches)
        on_site = search_expected(activity['row'].get('chance', 10))
        travel = max(0, (activity.get('expected') or on_site) - on_site)
        return Candidate('quality', HUNT_TIER, catch_value(odds) * needed, travel + per_catch * needed,
                         goal='postgame quality')
    if kind == 'train':
        level = max((mon.level for mon in held(snapshot) if ident(mon) == activity['identity']), default=0)
        steps = max(1, activity['level_goal'] - level)
        return Candidate('train', Tier.UPGRADE, values.level_step(level, activity['level_goal']),
                         TRAIN_DECISIONS * steps / 10, goal='postgame train')
    if kind == 'marathon':
        from ..planning.cost import FRAMES_PER_BATTLE
        from ..policies.marathon import BUDGET
        return Candidate('marathon', Tier.RACE, values.SMALL, BUDGET // (FRAMES_PER_BATTLE // DECISIONS_PER_BATTLE),
                         goal='postgame marathon')
    return Candidate('shiny', Tier.FILLER, values.SMALL, activity.get('expected') or search_expected(100, odds=1 / SHINY_ODDS),
                     goal='postgame shiny')


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
    """The searchable row with a route there that is expected to take the fewest decisions, travel
    included, as a target, or None."""
    from .collection import encounter_points
    groups = {}
    for row in rows:
        key = (row['map'], row['method'], row['time'] == 'rare trees')
        groups.setdefault(key, {**row, 'chance': 0})['chance'] += row['chance']
    ranked = []
    for key, row in groups.items():
        route = policy.nav.route(snapshot.map, key[0])
        if route is not None:
            ranked.append((search_expected(row['chance'], len(route)), key, row))
    for _, (mid, method, rare), row in sorted(ranked, key=lambda entry: entry[0])[:4]:
        points = encounter_points(policy, snapshot, mid, method, rare=rare)
        if points and policy.nav.regions.route(snapshot, mid, [point[:2] for point in points], cut=True, surf=True):
            return row
    return None


def quality(policy, snapshot, current_time):
    """A better-DV hunt for the owned species whose next catch earns the most per decision.

    A species whose next catch earns less than WORTH is left out.
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
        rate = max(catch_rate(odds, row, spent) for row in rows[species])
        candidates.append((-rate, species, odds, spent))
    for _, species, odds, spent in sorted(candidates)[:6]:
        row = reachable(policy, snapshot, rows[species])
        if row and worth_hunting(odds, [row], spent):
            seen = [ident(mon) for mon in held(snapshot) if mon.species == species]
            nav = getattr(policy, 'nav', None)
            route = nav.route(snapshot.map, row['map']) if nav is not None else None
            expected = search_expected(row.get('chance', 10), len(route) if route is not None else 0)
            return {'kind': 'quality', 'species': species, 'row': dict(row, started=policy.decisions),
                    'started': policy.decisions, 'seen': seen, 'caught': 0, 'expected': expected,
                    'tail': best_tail(snapshot, species)}
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
    for _, _, maps, mid in sorted(ranked)[:4]:
        points = encounter_points(policy, snapshot, mid, 'grass')
        if points and policy.nav.regions.route(snapshot, mid, [point[:2] for point in points], cut=True, surf=True):
            # Asking changes no saved state. The map counts as searched once the arbiter picks it.
            row = {'map': mid, 'method': 'grass', 'time': 'any', 'species': None,
                   'chance': 100, 'started': policy.decisions}
            return {'kind': 'shiny', 'row': row, 'started': policy.decisions, 'maps': maps,
                    'expected': search_expected(100, maps, odds=1 / SHINY_ODDS),
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
