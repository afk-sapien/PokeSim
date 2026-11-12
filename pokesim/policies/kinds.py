"""The rules of each Gen I goal kind: its key, its goal now, when it is done, its budget and its label.

A kind is a project's method. Each one has a rules class here, and ``rules(method)`` finds it. The
flags that change a method's meaning (``repeat``, ``dv_hunt``, ``legendary_return``, ``event_return``,
``upgrade_evolution``, ``scoped_partner``) are params of the kind, read by its rules.

``run`` names the fields a kind writes once its goal is under way. Every other field is a param, and
GoalRun (planning/goals.py) refuses a write to one. The design is in docs/design/typed-goals.md.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from ..planning.goals import Abandon, Rules
from ..planning.stance import HUNT, TRAIN
from ..strategy_data import ITEMS, MAPS, WORLD, event_set
from . import collection as c
from . import marathon, training
from .move_development import evolution_wait, move_name
from .progression import Goal, at, object_goal

# Run fields every kind may write: what it gained, its last progress mark, a support trip under way,
# the supplies it prepared and the closest it came to its target.
BASE_RUN = frozenset({'gains', 'progress_mark', 'support_trip', 'supplies_prepared', 'closest_distance'})
# The params the goal catalogue lists, each (name, type, about). A species param is a Pokédex number.
SPECIES = ('species', 'species', 'the Pokémon to get')
MAP = ('map', 'map', 'the map it is on')
ITEM = ('item', 'item', 'the item to get')
PARENT = ('parent', 'species', 'the held Pokémon it works with')


@dataclass
class View:
    """What a kind's rules read: the collection, the snapshot ``s``, the trainee's party index as the
    step found it, whether the race ended this step, and the League counts a rematch adds to."""
    collection: object
    s: object
    trainee: int | None = None
    race_finished: bool = False
    appearances: dict | None = None


class Kind(Rules):
    """A kind's rules. A method with no class of its own, as an older save or a test may hold, takes these."""
    run = BASE_RUN
    # The director's category for its outcome counts. A legendary project is 'legendary' whatever its kind.
    category = 'collection'
    # Frames the kind's own clock starts with (training's session, the race), or None for a kind whose
    # budget the monitor keeps.
    clock = None
    # The kind catches wild Pokémon over and over, so its encounters feed the hunt counters.
    wild = False
    # A repeat of the kind brings its own balls, which the Safari Zone gives instead.
    own_balls = False
    # Plain words for the kind and its params, for the goal catalogue.
    about = 'a collection goal'
    params = ()

    # A pickled goal finds its kind's one rules object again by name.
    def __reduce__(self):
        return rules, (self.kind,)

    @property
    def own_clock(self):
        """Whether the kind keeps its own clock, so it has no budget on the monitor and runs on while
        another goal's visit suspends it."""
        return self.clock is not None

    def key(self, p):
        """The monitor key of the project ``p``, the offers draw's dict."""
        return str(p.get('species', 0)) + ':' + p['method'] + ':' + str(p.get('map', 0)) + ':' + str(p.get('fragment', ''))

    def battle_progress(self, p):
        """Whether a battle that ends is progress for ``p``, as for a hunt."""
        return False

    def target(self, view, p):
        """The goal at ``p``'s source, once the party is ready for it."""
        return None

    def step(self, view, p):
        """``p``'s goal now: getting the party ready, or the goal at its source."""
        return self.target(view, p)

    def owned(self, view, run):
        """Whether the run has its species or item, or its repeat or return is done."""
        s = view.s
        target, item = run.get('species'), run.get('item')
        finished = (target and c.dex(target) in s.owned) or (not target and item and any(i == ITEMS[item] for i, q in s.items if q))
        if run.get('repeat'):
            caught = max(0, c.held_count(s, target) - run['initial_count'])
            run.setdefault('gains', {})['catches'] = max(run.get('gains', {}).get('catches', 0), caught)
            finished = caught >= run.get('catch_goal', 1)
        if run.get('event_return'):
            finished = run['event_return'] not in getattr(view.collection, 'returned_events', {})
        return finished

    def returned(self, view, run, finished):
        """``finished``, unless a returned legendary or an evolution that upgrades a held copy decides it."""
        target = run.get('species')
        if run.get('legendary_return'):
            finished = c.dex(target) not in getattr(view.collection, 'returned_legendaries', ())
        if run.get('upgrade_evolution'):
            index = view.collection.trainee(view.s, run)
            finished = index is not None and view.s.party[index].species == target
        return finished

    def finished(self, view, run):
        """Whether the run is done, or an Abandon when it cannot go on."""
        return self.returned(view, run, self.owned(view, run))

    def budget(self, p):
        """Frames ``p`` may spend without progress before it stands down, or None for a kind with its own clock."""
        return None if self.own_clock else 3 * c.expected_frames(p)

    def label(self, run):
        """The run's name when it ends, in the plan history."""
        target, item = run.get('species'), run.get('item')
        return c.name(target) if target else item.replace('_', ' ').title() if item else run['method'].title()

    def values(self, p):
        """The catalogue's params of the project ``p``, with each species as its Pokédex number."""
        found = {}
        for name, type_, _ in self.params:
            value = p.get(name)
            found[name] = c.dex(value) if type_ == 'species' and value is not None else value
        return found


class Hunt(Kind):
    """Wild encounters on a map, until the catch."""
    wild = True
    own_balls = True
    params = (SPECIES, MAP)

    def battle_progress(self, p):
        return True

    def target(self, view, p):
        sid = p.get('species')
        points = c.tiles(p)
        purpose = ('a partner another adventure needs' if view.collection.demand().get(c.dex(sid), 0)
                   else 'more chances to find high DV partners' if p.get('dv_hunt')
                   else 'another partner for the collection' if p.get('repeat') else 'a missing Pokédex entry')
        # Every hunt runs from the battles it cannot catch from (planner design S5): Pokédex, partner,
        # repeat and high DV searches alike.
        return Goal('collect_hunt', 'Find ' + c.name(sid), f'Search {c.place(p["map"])} for {purpose}',
                    tuple(t[:3] for t in points), approaches=tuple(t for t in points if t[3]), kind=HUNT)


class Grass(Hunt):
    kind = 'grass'
    about = 'catch a wild Pokémon in the grass'


class Surf(Hunt):
    kind = 'surf'
    about = 'catch a wild Pokémon on the water'


class Fish(Hunt):
    kind = 'fish'
    about = 'catch a Pokémon with a fishing rod'


class Safari(Hunt):
    kind = 'safari'
    own_balls = False
    about = 'catch a Pokémon in the Safari Zone'


class Source(Kind):
    """A Pokémon a person, a ball on the floor or the lab hands over in one room."""
    # The kind puts the Pokémon in the party, so a full party first stores a reserve.
    received = False
    params = (SPECIES, MAP)

    def fragment(self, view, p, room):
        return p['fragment']

    def wait(self, view, p):
        """A goal that comes before the source, or None."""
        return None

    def step(self, view, p):
        s = view.s
        if self.received and len(s.party) >= 6:
            # A party of field-move holders, Yellow's Pikachu and the strongest battler has nothing to
            # deposit. Offering the gift anyway parked the adventure at a PC until the project timed out.
            if not c.partner_exchange_possible(s):
                return None
            return Goal('party_collection_space', 'Make room for a gift', 'Store a reserve before receiving a Pokémon',
                        c.CENTERS, 'up', True)
        return self.target(view, p)

    def target(self, view, p):
        room = WORLD[p['map']]['symbol']
        fragment = self.fragment(view, p, room)
        first = self.wait(view, p)
        if first is not None:
            return first
        goal = object_goal('collect_' + self.kind, 'Collect ' + c.name(p.get('species')),
                           'Visit a remaining source for the Pokédex', room, fragment)
        # A legendary expedition is a hunt for its legendary, so it runs from every other battle.
        return replace(goal, kind=HUNT) if c.legendary_project(p) else goal

    def held(self, view, run, finished):
        """``finished``, or an Abandon once the source closed with no new copy held."""
        s, target = view.s, run.get('species')
        if c.legendary_project(run) or not target:
            return finished
        held = run.setdefault('initial_held', run.get('initial_count', c.held_count(s, target)))
        if not finished and not s.in_battle and not view.collection.available(s, run):
            if c.held_count(s, target) <= held:
                # The source left the room or the game closed it, for example the other Fighting
                # Dojo ball was taken. Waiting on it could only end in a stand-down two minutes later.
                return Abandon(f'{c.name(target)} is no longer offered here')
            finished = True
        return finished


class Static(Source):
    """A Pokémon standing in the world, a legendary or Snorlax among them."""
    kind = 'static'
    run = BASE_RUN | {'initial_held'}
    about = 'battle and catch a Pokémon standing in the world'

    def key(self, p):
        if c.legendary_project(p):
            return f'legendary:{p["species"]}:{p["map"]}'
        return super().key(p)

    def battle_progress(self, p):
        return c.legendary_project(p)

    def target(self, view, p):
        s = view.s
        if c.dex(p.get('species')) == 144 and not all(event_set(s.event_flags, flag) for flag in
                ('EVENT_SEAFOAM4_BOULDER1_DOWN_HOLE', 'EVENT_SEAFOAM4_BOULDER2_DOWN_HOLE')):
            return replace(at('collect_seafoam_current', 'Slow the current for Articuno',
                              'Push the Seafoam boulders into the holes before using Surf',
                              'SEAFOAM_ISLANDS_B3F', 6, 15), kind=HUNT)
        return super().target(view, p)

    def finished(self, view, run):
        s, collection = view.s, view.collection
        target = run.get('species')
        if (c.legendary_project(run) and not s.in_battle
                and (c.dex(target) not in s.owned or run.get('legendary_return')
                     and c.dex(target) in getattr(collection, 'returned_legendaries', ()))
                and run.get('flag') and event_set(s.event_flags, run['flag'])):
            return Abandon('Legendary encounter ended without a catch')
        finished = self.owned(view, run)
        if (c.snorlax_project(run) and not s.in_battle and run.get('flag')
                and event_set(s.event_flags, run['flag'])):
            # The walking return closes once Route 12 is behind, so judge the battle here.
            finished = (max(0, c.held_count(s, target) - run['initial_count']) >= 1 if run.get('repeat')
                        else c.dex(target) in s.owned)
            if not finished:
                return Abandon('Snorlax battle ended without a catch')
        return self.held(view, run, self.returned(view, run, finished))


class Gift(Source):
    kind = 'gift'
    run = BASE_RUN | {'initial_held'}
    received = True
    about = 'receive a Pokémon someone gives away'

    def fragment(self, view, p, room):
        fragment, number = p['fragment'], c.dex(p.get('species'))
        if number in (106, 107) and not event_set(view.s.event_flags, 'EVENT_BEAT_KARATE_MASTER'):
            fragment = 'KARATE_MASTER'
        if number == 133:
            fragment = 'EEVEE_POKEBALL'
        return fragment

    def finished(self, view, run):
        finished = super().finished(view, run)
        if c.dex(run.get('species')) in (106, 107):
            finished = event_set(view.s.event_flags, run['flag'])
        return self.held(view, run, finished)


class Trade(Source):
    kind = 'trade'
    run = BASE_RUN | {'parent', 'box', 'give_key'}
    about = 'trade a held Pokémon to a person for theirs'

    def battle_progress(self, p):
        return True

    def fragment(self, view, p, room):
        return p['fragment'] or c.TRADE_NPCS[room]

    def step(self, view, p):
        from ..trade.preferences import identity
        partner = view.collection.trade_candidate(view.s, p)
        if partner is None:
            return None
        p['parent'] = p['give']
        p['box'] = partner.get('box')
        p['give_key'] = identity(partner)
        if 'party_index' not in partner:
            return Goal('party_collection', 'Prepare an NPC trade',
                        'Retrieve ' + c.name(p['give']) + ' from storage for ' + c.name(p['species']),
                        c.CENTERS, 'up', True)
        return self.target(view, p)


class Fossil(Source):
    kind = 'fossil'
    received = True
    about = 'revive a fossil at the Cinnabar lab'
    params = (SPECIES,)

    def wait(self, view, p):
        if event_set(view.s.event_flags, 'EVENT_LAB_STILL_REVIVING_FOSSIL'):
            return at('collect_fossil_walk', 'Give the fossil lab time', 'Step outside while the fossil is revived',
                      'CINNABAR_ISLAND', 6, 10)
        return None

    def finished(self, view, run):
        finished = super().finished(view, run)
        if run.get('initial_owned'):
            finished = finished or bool(view.s.owned - set(run['initial_owned']))
        return finished


class ReturnFossil(Kind):
    kind = 'return_fossil'
    about = 'pick up the fossil left behind again'
    params = (ITEM,)

    def target(self, view, p):
        room = WORLD[p['map']]['symbol']
        fragment = 'SCIENTIST2' if p['item'] == 'OLD_AMBER' else p['item']
        return object_goal('collect_pickup', 'Collect another fossil', 'Bring it to the Cinnabar lab', room, fragment)


class Marathon(Kind):
    kind = 'marathon'
    run = BASE_RUN | {'checkpoint', 'race_frames', 'healed_here'}
    category = 'recreation'
    clock = marathon.BUDGET
    about = 'run the sightseeing race around the region'

    def target(self, view, p):
        return marathon.goal(p)

    def finished(self, view, run):
        super().finished(view, run)
        return view.race_finished


class Rematch(Kind):
    kind = 'rematch'
    run = BASE_RUN | {'parent', 'trainee_key', 'trainee_nick', 'family', 'scoped_partner', 'box',
                      'league_rotation', 'rotation_ready'}
    category = 'supplies'
    about = 'battle the Elite Four and the Champion again'

    def step(self, view, p):
        if view.s.map not in c.LEAGUE:
            rotation = view.collection.league_rotation_goal(view.s, p, view.appearances)
            if rotation:
                return rotation
        return self.target(view, p)

    def target(self, view, p):
        s = view.s
        if s.map != MAPS['INDIGO_PLATEAU_LOBBY']:
            # Money stops at 999,999, so at the cap a rematch earns experience only.
            purpose = 'Earn prize money and experience for collecting' if s.money < 999999 else 'Earn experience while nothing else is left'
            return at('collect_rematch', 'Return for a League rematch', purpose, 'INDIGO_PLATEAU_LOBBY', 8, 10)
        # The title starts with "Challenge", so the boss check guards the walk into Lorelei's room and
        # the party heals at the Indigo Plateau Center first. Titled "Begin a League rematch", the check
        # first ran inside the League, where no nurse is in reach, and Red met the Elite Four again and
        # again with its level 100 fighters out of PP until a battle at Lance never ended.
        return object_goal('league_lorelei', 'Challenge Lorelei in a League rematch',
                           'Fund the next expeditions' if s.money < 999999 else 'Run the League again', 'LORELEIS_ROOM', 'LORELEI')

    def finished(self, view, run):
        super().finished(view, run)
        return view.s.hall_of_fame_count > run['hof_count'] or view.s.map == MAPS['HALL_OF_FAME']


class Trainer(Kind):
    kind = 'trainer'
    category = 'exploration'
    about = 'battle a trainer not yet beaten'
    params = (MAP,)

    def target(self, view, p):
        return object_goal('collect_trainer', 'Meet an unbeaten trainer', 'Explore and earn experience and supplies',
                           WORLD[p['map']]['symbol'], p['fragment'])

    def finished(self, view, run):
        super().finished(view, run)
        return event_set(view.s.event_flags, run['flag'])


class Explore(Kind):
    kind = 'explore'
    category = 'exploration'
    about = 'visit an area not yet explored'
    params = (MAP,)

    def target(self, view, p):
        return Goal('collect_explore', 'Explore ' + c.place(p['map']), 'Visit an area that has not been explored',
                    (tuple(p['target']),))

    def finished(self, view, run):
        super().finished(view, run)
        s = view.s
        return (s.map, s.x, s.y) == tuple(run['target'])


class Prize(Kind):
    kind = 'prize'
    about = 'exchange Game Corner coins for a Pokémon'
    params = (SPECIES,)

    def target(self, view, p):
        s, collection = view.s, view.collection
        if not dict(s.items).get(ITEMS['COIN_CASE']):
            return object_goal('collect_coins', 'Get the Coin Case', 'Prepare to exchange coins for Porygon', 'CELADON_DINER', 'FISHER')
        cost = c.PORYGON_COINS.get(collection.version, 9999)
        if s.coins < cost:
            if s.money < 10000:
                collection.remaining = 0
                return None
            return at('collect_coins', 'Save coins for Porygon', f'{s.coins} of {cost} coins saved', 'GAME_CORNER', 5, 8, 'up')
        return at('collect_prize', 'Collect Porygon', 'Exchange saved coins for a new Pokédex entry', 'GAME_CORNER_PRIZE_ROOM', 4, 3, 'up')


class Rod(Kind):
    kind = 'rod'
    category = 'supplies'
    about = 'get a fishing rod'
    params = (ITEM,)

    def target(self, view, p):
        return object_goal('collect_rod', 'Obtain ' + p['item'].replace('_', ' ').title(), 'Unlock more fishing encounters',
                           p['room'], 'FISHING_GURU')


class Amber(Kind):
    kind = 'amber'
    about = 'collect the Old Amber from the museum'
    params = (ITEM,)

    def target(self, view, p):
        return object_goal('collect_amber', 'Collect Old Amber', 'Revive Aerodactyl at the Cinnabar lab', 'MUSEUM_1F', 'SCIENTIST2')


class Partner(Kind):
    """A kind that works with one held Pokémon, the trainee, which may come out of a box first."""

    def step(self, view, p):
        collection, s = view.collection, view.s
        if p.get('trainee_key') and len(collection.partner_matches(s, p)) != 1:
            return None
        index = collection.trainee(s, p)
        if index is None:
            if p.get('trainee_key'):
                matches = [mon for mon in collection.partner_matches(s, p) if 'party_index' not in mon]
                if len(matches) != 1:
                    return None
                p['box'] = matches[0]['box']
            if not c.partner_exchange_possible(s):
                return None
            return Goal('party_collection', 'Withdraw a training partner',
                        'Keep the main battlers and bring a reserve out of storage', c.CENTERS, 'up', True)
        return self.work(view, p, index)

    def work(self, view, p, index):
        """The goal once the trainee is in the party at ``index``."""
        return None


class Evolve(Partner):
    kind = 'evolve'
    run = BASE_RUN | {'initial_experience', 'box'}
    category = 'evolution'
    about = 'evolve a held Pokémon'
    params = (SPECIES, PARENT)

    def key(self, p):
        key = super().key(p)
        if p.get('trainee_key'):
            key += ':' + p['trainee_key']
        return key

    def work(self, view, p, index):
        s, version = view.s, view.collection.version
        mon = s.party[index]
        evo = p['evolution']
        if evo['method'] == 'item':
            wait_for = evolution_wait(asdict(mon), evo)
            if wait_for:
                level, move = wait_for
                return Goal('collect_train', f'Learn {move_name(move)} before evolving',
                            f'Train {mon.nick or c.name(p["parent"])} to level {level} before using a stone',
                            c.evolution_training_targets(version, mon.level), kind=TRAIN)
            if not dict(s.items).get(ITEMS[evo['requirement']]):
                return at('collect_stone', 'Buy an evolution stone', 'Complete another Pokédex entry', 'CELADON_MART_4F', 5, 5, 'down')
            return Goal('collect_evolve', 'Evolve ' + c.name(p['parent']), 'Use ' + evo['requirement'].replace('_', ' ').title(),
                        ((s.map, s.x, s.y),))
        return Goal('collect_train', 'Train ' + c.name(p['parent']) + ' toward ' + c.name(p['species']),
                    f'Work toward level {evo["requirement"]}, then resume other activities',
                    c.evolution_training_targets(version, mon.level), kind=TRAIN)


class Train(Partner):
    kind = 'train'
    run = BASE_RUN | {'parent', 'initial_experience', 'training_session', 'box'}
    category = 'training'
    clock = training.TRAINING_BUDGET
    about = 'train a held Pokémon to a level'
    params = (PARENT, ('target_level', 'level', 'the level to reach'))

    def key(self, p):
        key = f'train:{p.get("trainee_key") or p["parent"]}:{p["target_level"]}'
        if p.get('scoped_partner'):
            key += ':' + str(p['parent']) + ':' + p.get('trainee_nick', '')
        return key

    def work(self, view, p, index):
        mon = view.s.party[index]
        return Goal('collect_train', f'Train {mon.nick or c.name(mon.species)} to level {p["target_level"]}',
                    f'Level {mon.level} of {p["target_level"]}. Stay with this partner while training is productive',
                    c.training_targets(view.collection.version, mon.level), kind=TRAIN)

    def finished(self, view, run):
        super().finished(view, run)
        return view.trainee is not None and view.s.party[view.trainee].level >= run['target_level']

    def label(self, run):
        return f'{c.name(run["parent"])} toward level {run["target_level"]}'


RULES = {rules.kind: rules for rules in (
    Grass(), Surf(), Fish(), Safari(), Static(), Gift(), Trade(), Fossil(), ReturnFossil(), Marathon(),
    Rematch(), Trainer(), Explore(), Prize(), Rod(), Amber(), Evolve(), Train())}
OTHER = Kind()


def rules(method):
    """The rules of the kind ``method``. A method with no rules of its own takes the plain Kind's."""
    return RULES.get(method, OTHER)
