"""Bounded collecting expeditions and evolution projects for a continuing adventure."""
import time
from collections import Counter
from dataclasses import asdict
from ..duplicates import quality
from pokecore.identity import same
from .move_development import evolution_wait, move_name
from ..pokemon import experience_at_level
from ..investment import automatic_trade_protected,training_investment, potential_power, assessment, SEARCH_BUDGET
from functools import lru_cache
from ..game_data import current_variant, load

from .progression import GRASS_TILES, Goal, object_goal, at

YELLOW = current_variant() == 'yellow'
# Yellow's Pikachu refuses the Thunder Stone, and the game treats every Pikachu
# the player caught as its partner, so Raichu only arrives through a link trade.
REFUSES_EVOLUTION = {25} if YELLOW else set()
from .navigation import DIRS
from .director import AdventureDirector, category, new_entry
from ..planning import values
from ..planning.arbiter import Candidate, Tier
from ..planning import cost
from ..planning.cost import FRAMES_PER_TILE
from ..planning.shadow import Shadow
from ..planning.conditions import Can, Count, Item, Requirements, feasible
from ..planning.ledger import MONEY, Need
from ..planning.monitor import CONTINUE, SPENT, STOOD_DOWN, ProgressEvent
from . import training, marathon, league_rotation
from ..shiny import is_shiny
from ..milestones import is_perfect, level_credit
from ..strategy_data import ITEMS, MAPS, MOVES, SPECIES, WORLD, EVENTS, event_set, object_hidden
from ..ram import MAP_NAMES

DATA = load('collection.json')
EVOS = {int(sid): rows for sid, rows in DATA['evolutions'].items()}
# Frames out of battle a project other than training may go without an encounter, a training gain,
# a new map or another sign of progress before it stands down. Two minutes of play.
IDLE_BUDGET = 7200
# Frames a project that meets no wild Pokémon is expected to take once there, by kind. A catch is
# priced from the cartridge's encounter odds in planning/cost.py instead. A project stands down once
# it spent three times its expected frames, travel included, without progress. Training keeps its own
# clock and a marathon its race clock.
EXPECTED_FRAMES = {'rematch': 100000, 'special': 60000, 'evolve': 60000, 'other': 12000}
# Frames a training step is expected to take per point of experience, heals included. A flat price per
# level made a level 50 Dragonair's step look as cheap as a level 25 partner's, though it needs four
# times the experience, and Red's heal share rose from 1% to 9% while it trained on Route 23. Postgame
# training on three Red and three Yellow saves took about 36000 frames for a level near 50.
FRAMES_PER_EXPERIENCE = 5
# The tier of a hunt for another copy of a registered species, a quality or a plain repeat, so a family
# still short of its level 100 credit trains first. At the approved weights a quality catch earns about
# ten times what a training step earns per frame, and Red's training share fell from 57% to 2% while its
# hunts walked to marts and PCs. The trade-off is set out in docs/design/planner-systems.md.
HUNT_TIER = Tier.FILLER
# Fewest uses a trainee's attacking moves must hold between heals. A Red Chansey whose only attack was
# Double Slap, 10 uses, trained for 600000 frames and walked to the Pokémon Center a hundred times.
TRAINING_PP = 20


def budgeted(project):
    return project['method'] not in ('train', 'marathon')


def kind_frames(project, wild=None):
    """What a project is expected to take once there. ``wild`` is the cartridge's WildOdds, or None to
    price a catch with the unpriced estimate."""
    method = project['method']
    if method in REPEATABLE and project.get('map') is not None:
        return cost.catch_frames(wild, method, project['map'], project['species'],
                                 needed=project.get('catch_goal', 1), rod=project.get('rod'))
    if method == 'rematch':
        return EXPECTED_FRAMES['rematch']
    if legendary_project(project) or project.get('event_return') or method in ('trade', 'fossil'):
        return EXPECTED_FRAMES['special']
    if method == 'evolve':
        return EXPECTED_FRAMES['evolve']
    return EXPECTED_FRAMES['other']


def expected_frames(project):
    """The frames expected to ``project``'s first catch or its end, travel included, kept when it was
    chosen. A project from an older save, chosen before they were kept, is priced again without the walk."""
    if project.get('expected_frames') is not None:
        return project['expected_frames']
    return kind_frames({**project, 'catch_goal': 1})


def shadow_kind(project):
    """The kind of a project for the audit's share by chosen kind."""
    kind = category(project)
    if kind == 'collection':
        return 'collection quality' if project.get('dv_hunt') else 'collection repeat' if (
            project.get('repeat') and not project.get('needed_capture')) else 'collection new entry'
    return kind


def can_train(mon):
    """True unless ``mon``'s attacking moves hold fewer than TRAINING_PP uses between heals. A row
    without its moves, from an older snapshot, is not judged."""
    moves = mon.get('moves')
    if moves is None:
        return True
    return sum(MOVES.get(move, {}).get('pp', 0) for move in moves if MOVES.get(move, {}).get('power')) >= TRAINING_PP


def training_frames(project):
    """The frames ``project``'s training step is expected to take, from the experience its trainee's
    growth rate needs between the two levels."""
    growth = SPECIES.get(project.get('parent'), {}).get('growth')
    needed = (experience_at_level(project['target_level'], growth)
              - experience_at_level(project['initial_level'], growth))
    return max(0, needed) * FRAMES_PER_EXPERIENCE


def candidate(project, travel, tails, short, owned, wild=None):
    """The arbiter's candidate for a project.

    Values come from planning/values.py. Expected frames are the walk to the project at the shared
    tile estimate in planning/cost.py, plus a catch priced from ``wild``, the cartridge's own encounter
    odds, or the per-kind EXPECTED_FRAMES, the training step at FRAMES_PER_EXPERIENCE or the race clock. A
    quality hunt is worth each catch's expected drop in the species' best DV tail, once per catch. A
    hunt for another copy of a registered species sits in HUNT_TIER, below training for a credit.
    """
    method, sid = project['method'], project.get('species')
    tier = Tier.PROGRESS
    if method == 'rematch':
        tier = Tier.UPKEEP if short else Tier.FILLER
        value = values.rematch(short)
    elif method in ('marathon', 'explore', 'trainer'):
        tier, value = Tier.FILLER, values.SMALL
    elif method == 'train' and project.get('mastery_needed'):
        value = values.level_step(project['initial_level'], project['target_level'])
    elif method == 'train':
        # A family with its level 100 credit gains nothing the Pokédex counts, so its training is filler.
        tier, value = Tier.FILLER, values.SMALL
    elif legendary_project(project):
        # A returned legendary the Pokédex already has is a repeat, not an entry.
        value = values.NEW_ENTRY if dex(sid) not in owned else values.SMALL
    elif new_entry(project) or project.get('needed_capture') or method in ('rod', 'amber', 'return_fossil'):
        # A rod or the Old Amber opens new entries, and a needed repeat is another adventure's entry.
        value = values.NEW_ENTRY
    elif project.get('dv_hunt') and tails.get(sid) is not None:
        tier, value = HUNT_TIER, values.quality_catch(tails[sid] / 100) * project.get('catch_goal', 1)
    else:
        tier, value = (HUNT_TIER if project.get('repeat') else tier), values.SMALL
    if method == 'train':
        frames = training_frames(project)
    elif method == 'marathon':
        frames = marathon.BUDGET
    else:
        frames = kind_frames(project, wild)
    frames += (travel or 0) * FRAMES_PER_TILE
    return Candidate(project.get('key', method), tier, value, frames, goal=shadow_kind(project))


def project_budget(project):
    return 3 * expected_frames(project)


def budget_key(project):
    """The monitor key of a project's budget, apart from its idle count under the project key."""
    return 'budget:' + project.get('key', project['method'])


CENTERS = tuple((m, 13, 4) for m, w in WORLD.items() if 'Pokecenter' in w['name'] and w['width'] == 14)
CENTERS += ((MAPS['INDIGO_PLATEAU_LOBBY'], 15, 8),)
LEAGUE = {MAPS[n] for n in ('LORELEIS_ROOM','BRUNOS_ROOM','AGATHAS_ROOM','LANCES_ROOM','CHAMPIONS_ROOM','HALL_OF_FAME')}
REPEATABLE = {'grass', 'surf', 'fish', 'safari'}
# Goals the adventure runs for a project while the project stays chosen: a heal after its battles,
# supplies for its catches, a box with room for them, or a reserve swapped in at the Center on the way.
SUPPORT_TRIPS = ('heal', 'restock', 'party_box', 'party_upgrade')


def place(map_id):
    """The map as the player reads it, e.g. Seafoam Islands B3F, not SeafoamIslandsB3F."""
    return MAP_NAMES.get(map_id) or WORLD[map_id]['name']


def held_count(snapshot, species):
    stored = snapshot.stored_pokemon
    boxed = [(sid, level) for box, sid, level, nick in stored] if stored else snapshot.boxed_pokemon
    return sum(mon.species == species for mon in snapshot.party) + sum(sid == species for sid, level in boxed)


GIFT_METHODS = {'gift', 'fossil'}


@lru_cache(maxsize=None)
def gift_species(version):
    """Species this version gives only as a gift or fossil, with the forms they evolve into.

    A species with no source of its own counts by the first of its ancestors that has one, so
    Eevee's evolutions and the fossil lines count with Eevee and the fossils.
    """
    from ..milestones import ancestors
    rows = {int(k): v for k, v in DATA['versions'].get(version, {}).items()}

    def origin(sid):
        if rows.get(sid):
            return sid
        return next((parent for parent in sorted(ancestors(sid) - {sid}) if rows.get(parent)), None)

    return frozenset(sid for sid in SPECIES if (root := origin(sid)) is not None
                     and {source['method'] for source in rows[root]} <= GIFT_METHODS)


# Porygon's Game Corner price. Blue sells it cheaper, Red and Yellow ask 9999 coins.
PORYGON_COINS = {'red': 9999, 'blue': 6500, 'yellow': 9999}
SNORLAX = next(sid for sid, row in SPECIES.items() if row['dex'] == 143)
# The Route 12 Snorlax, woken with the Poké Flute. Walking reopens it after the first battle.
SNORLAX_SOURCE = {'map': MAPS['ROUTE_12'], 'method': 'static', 'fragment': 'SNORLAX',
                  'flag': 'EVENT_BEAT_ROUTE12_SNORLAX'}


def snorlax_project(project):
    return bool(project and project.get('method') == 'static' and project.get('fragment') == 'SNORLAX')


def legendary_project(project):
    return bool(project and project.get('method') == 'static'
                and (SPECIES.get(project.get('species'), {}).get('dex') in (144, 145, 146, 150)
                     or project.get('fragment') in ('ARTICUNO', 'ZAPDOS', 'MOLTRES', 'MEWTWO')))


RODS = {'OLD_ROD': 'VERMILION_OLD_ROD_HOUSE', 'GOOD_ROD': 'FUCHSIA_GOOD_ROD_HOUSE', 'SUPER_ROD': 'ROUTE_12_SUPER_ROD_HOUSE'}
TRADE_NPCS = {'ROUTE_2_TRADE_HOUSE':'GAMEBOY_KID', 'VERMILION_TRADE_HOUSE':'LITTLE_GIRL',
              'ROUTE_18_GATE_2F':'YOUNGSTER', 'CERULEAN_TRADE_HOUSE':'GAMBLER'}


# Grass tile per tileset, from data/tilesets/tileset_headers.asm. A tileset with no grass tile
# (CAVERN and the interiors, -1 upstream) has encounters on any walkable floor tile instead, which
# is the fallback in tiles(). Leaving PLATEAU out of this meant Route 23 offered 981 encounter
# tiles instead of its 44, so the run walked to a tile that could never produce a battle.


def name(sid):
    return SPECIES.get(sid, {}).get('name', 'Unknown').replace('_', ' ').title()


def dex(sid):
    return SPECIES.get(sid, {}).get('dex', 0)


def storage_exchange_possible(s):
    """Taking a Pokemon out needs a free party slot, or somewhere to deposit a reserve first."""
    return len(s.party) < 6 or not s.box_full or s.next_free_box is not None


CATCH_MODES = ('grass', 'surf', 'fish', 'safari', 'static')
ANY_BALL = Count(tuple(ITEMS[n] for n in ('POKE_BALL', 'GREAT_BALL', 'ULTRA_BALL', 'MASTER_BALL')))
# A repeat hunt for an owned species throws more than one ball, and the Master Ball is never one of them.
HUNT_BALLS = Count(tuple(ITEMS[n] for n in ('POKE_BALL', 'GREAT_BALL', 'ULTRA_BALL')), 5)
SAFARI_ENTRY = Need(money=800)


class CollectionWorld:
    """What a collection source asks of a Red, Blue or Yellow snapshot and the route planner."""

    def __init__(self, snapshot, nav):
        self.snapshot = snapshot
        self.nav = nav
        self.counts = dict(snapshot.items)

    def has_item(self, item):
        return bool(self.counts.get(item))

    def item_count(self, item):
        return self.counts.get(item, 0)

    def has_badge(self, badge):
        return bool(self.snapshot.badges & badge)

    def event(self, flag):
        return event_set(self.snapshot.event_flags, flag)

    def reachable(self, place):
        return True

    def can(self, action):
        if action == 'catch':
            return self.snapshot.can_catch
        if action == 'surf':
            return self.nav.can_surf
        if action == 'take':
            return storage_exchange_possible(self.snapshot)
        raise ValueError(f'unknown action {action}')


def source_requires(source, owned):
    """What a collection source needs before it is a candidate: room and a ball to catch, Surf for the
    water, the rod for fishing, the Safari fee, room to take a gift or fossil, and five balls for a
    repeat hunt of a species already owned."""
    mode = source['method']
    conditions = ()
    if mode in CATCH_MODES:
        conditions += (Can('catch'), ANY_BALL)
    if mode == 'surf':
        conditions += (Can('surf'),)
    if mode == 'fish':
        conditions += (Item(ITEMS[source['rod']]),)
    if mode in ('gift', 'fossil'):
        conditions += (Can('take'),)
    if mode in REPEATABLE and mode != 'safari' and owned:
        conditions += (HUNT_BALLS,)
    return Requirements(conditions, SAFARI_ENTRY if mode == 'safari' else Need())


def partner_exchange_possible(s):
    """A stored partner joins a full party only when some reserve may be deposited for it.

    Field-move holders, Yellow's Pikachu and the strongest battler stay. Without that check a full
    party of them reopened the PC to withdraw a partner it could never make room for.
    """
    from .team import reserve_to_deposit
    return storage_exchange_possible(s) and (len(s.party) < 6 or reserve_to_deposit(s) is not None)


def champion(s):
    return s.hall_of_fame_count > 0 or event_set(s.event_flags, 'EVENT_BEAT_CHAMPION_RIVAL') or s.map == MAPS['HALL_OF_FAME']


def tiles(source):
    w = WORLD[source['map']]
    mode = source['method']
    if mode == 'fish':
        points = []
        for y, row in enumerate(w['tiles']):
            for x, tile in enumerate(row):
                if tile not in w['passable'] or tile in (0x14,0x32,0x48):
                    continue
                for direction, (dx,dy) in DIRS.items():
                    if 0 <= y+dy < w['height'] and 0 <= x+dx < w['width'] and w['tiles'][y+dy][x+dx] in (0x14,0x32,0x48):
                        points.append((source['map'], x, y, direction))
        return tuple(points)
    water = (0x14,0x32,0x48)
    grass = GRASS_TILES.get(w['tileset'])
    return tuple((source['map'],x,y,None) for y,row in enumerate(w['tiles']) for x,tile in enumerate(row)
                 if (tile in water if mode == 'surf'
                     else tile == grass if grass is not None
                     else tile in w['passable'] and tile not in water)
                 and not any(warp[:2] == [x,y] for warp in w['warps']))


@lru_cache(maxsize=200)
def training_targets(version, level):
    sources = [source for rows in DATA['versions'].get(version, {}).values() for source in rows
               if source['method'] == 'grass' and source['level'] <= max(3, level - 3)
               and not WORLD[source['map']]['symbol'].startswith('CERULEAN_CAVE')]
    best = max((source['level'] for source in sources), default=0)
    maps = tuple(sorted({source['map'] for source in sources if source['level'] >= max(2, best - 8)}))
    return _training_map_targets(maps)


@lru_cache(maxsize=200)
def evolution_training_targets(version, level):
    maps = tuple(source['map'] for rows in DATA['versions'].get(version, {}).values()
                 for source in rows if source['method'] == 'grass'
                 and max(2, level - 12) <= source['level'] <= max(3, level - 3)
                 and not WORLD[source['map']]['symbol'].startswith('CERULEAN_CAVE'))
    return _evolution_training_map_targets(maps)


@lru_cache(maxsize=200)
def _evolution_training_map_targets(maps):
    # Keep the original destination order, including its routing tie breaks.
    return tuple(set(target for map_id in maps for target in _training_tiles(map_id)))


@lru_cache(maxsize=256)
def _training_tiles(map_id):
    return tuple(target[:3] for target in tiles({'map': map_id, 'method': 'grass'}))


@lru_cache(maxsize=200)
def _training_map_targets(maps):
    # Levels often choose the same maps. Share both their tuple and tile coordinates.
    return tuple(sorted({target for map_id in maps for target in _training_tiles(map_id)}))



def training_family(sid):
    family = {sid}
    for _ in range(2):
        family.update(evo['species'] for parent in tuple(family) for evo in EVOS.get(parent, [])
                      if evo['method'] == 'level')
    return sorted(family)


class Collection:
    def __init__(self):
        self.version = 'red'
        self.project = None
        self.remaining = 0
        self.elapsed = 0
        self.last_frame = None
        # The cartridge's encounter odds, which the host attaches once per adventure. None prices
        # every catch with the unpriced estimate.
        self.wild = None
        # What the game looked like when the last plan found nothing to do. The plan is not drawn
        # again until something in it changes.
        self.idle_token = None
        self.report = {}
        self.report_key = None
        self.eevee_choice = 134
        self.dojo_choice = 106
        self.trade_preferences = lambda: {}
        self.history = []
        self.completed_champion = False
        self.league_appearances = {}
        self.project_maps = []
        self.project_flags = []
        self.progress_token = None
        self.was_in_battle = False
        self.director = AdventureDirector()
        self.milestones = {}
        self.last_repeat = {}
        self.last_hunt = {}
        self.quality_searches = {}
        self.peer_demand = {}
        self.demand_until = 0
        self.next_marathon = 0
        self.marathon_records = {}
        self.activity_events = []
        self.marathon_previous = None
        # The arbiter's picks beside the director's, for the log and the replay audit. Never saved.
        self.shadow = Shadow()

    def demand(self):
        return self.peer_demand if time.monotonic() < self.demand_until else {}

    def set_demand(self, requests):
        self.peer_demand = dict(requests)
        self.demand_until = time.monotonic() + 180

    def repeat_target(self, species, map_id=None):
        if dex(species) in getattr(self, 'returned_legendaries', ()):
            return species
        project = self.project or {}
        if project.get('dv_hunt') and map_id == project.get('map'):
            return species
        return project.get('species') if project.get('repeat') else None

    def state_dict(self):
        return {**{k:getattr(self,k) for k in ('project','remaining','elapsed','eevee_choice','dojo_choice','history','completed_champion','league_appearances','project_maps','project_flags','last_repeat','last_hunt','quality_searches','next_marathon','marathon_records','activity_events')},
                'director': self.director.state_dict()}

    @property
    def project_key(self):
        return self.project.get('key', self.project['method']) if self.project else None

    @property
    def remaining(self):
        """Frames left in the project's budget. Training and a marathon keep their own clock here."""
        project = self.project
        if project and budgeted(project):
            return project_budget(project) - self.director.monitor.spent(budget_key(project))
        return self._remaining

    @remaining.setter
    def remaining(self, frames):
        project = self.project
        if not (project and budgeted(project)):
            self._remaining = frames
            return
        spent = self.director.monitor._table(SPENT)
        used = project_budget(project) - frames
        if used > 0:
            spent[budget_key(project)] = used
        else:
            spent.pop(budget_key(project), None)

    @property
    def idle_frames(self):
        """Frames the current project has gone without progress, as the director's monitor counts them."""
        key = self.project_key
        return self.director.monitor.spent(key) if key is not None else 0

    @idle_frames.setter
    def idle_frames(self, frames):
        key = self.project_key
        if key is None:
            return
        spent = self.director.monitor._table(SPENT)
        if frames:
            spent[key] = frames
        else:
            spent.pop(key, None)

    def load(self, data):
        self.next_marathon = data.get('next_marathon', 0)
        self.marathon_records = data.get('marathon_records', {})
        self.activity_events = data.get('activity_events', [])
        for key in self.state_dict():
            if key in data and key != 'director':
                setattr(self,key,data[key])
        self.director.load(data.get('director', {}))
        # Older saves kept the retry times and the idle count beside the director.
        for key, deadline in (data.get('attempts') or {}).items():
            self.director.resume(key, deadline, self.elapsed)
        if 'idle_frames' in data and 'progress' not in data.get('director', {}):
            self.idle_frames = data['idle_frames']
        if self.project and budgeted(self.project) and 'remaining' in data:
            # An older save kept the budget beside the director. A newer one agrees with the monitor.
            self.remaining = data['remaining']
        self.marathon_previous = None
        if self.eevee_choice not in (134, 135, 136):
            self.eevee_choice = 134
        if self.dojo_choice not in (106, 107):
            self.dojo_choice = 106
        if 'dojo_choice' not in data and self.project and self.project.get('method') == 'gift':
            chosen = dex(self.project.get('species'))
            if chosen in (106, 107):
                self.dojo_choice = chosen
        if self.project and self.project['method'] == 'train' and 'training_session' not in self.project:
            self.remaining = max(self.remaining, training.TRAINING_BUDGET)
            training.session(self.project)
        self.last_frame = None
        self.report_key = None
        self.progress_token = None
        self.was_in_battle = False
        self.idle_token = None

    def abandon(self, reason):
        if not self.project:
            return False
        project = self.project
        self.record_quality_search()
        self.finish_marathon(False)
        label = name(project['species']) if project.get('species') else project['method'].title()
        progressed = bool(project.get('gains', {}).get('experience', 0) or project.get('gains', {}).get('catches', 0))
        self.director.finish(project, self.elapsed, False, reason, progressed)
        self.history = (self.history + [f'Changed plan: {label}. {reason}'])[-6:]
        self.project = None
        self.remaining = 0
        self.idle_token = None
        self.idle_frames = 0
        self.project_maps = []
        self.project_flags = []
        self.progress_token = None
        return True

    def finish_marathon(self, finished):
        project = self.project
        if not project or project['method'] != 'marathon':
            return
        previous_best = self.marathon_records.get('best_frames')
        new_best = finished and (previous_best is None or project['race_frames'] < previous_best)
        self.marathon_records['last'] = {
            'finished': finished, 'frames': project['race_frames'], 'personal_best': new_best, **project['gains']}
        if finished:
            self.marathon_records['completed'] = self.marathon_records.get('completed', 0) + 1
            self.marathon_records['best_frames'] = min(
                self.marathon_records.get('best_frames', project['race_frames']), project['race_frames'])
        report = marathon.report(project, finished)
        if new_best:
            report += ' First personal best!' if previous_best is None else (
                f' New personal best, {marathon.duration(previous_best - project["race_frames"])} faster!')
        self.activity_events.append({
            'type': 'marathon', 'title': 'Kanto Marathon finished!' if finished else 'Kanto Marathon called off',
            'body': report, 'priority': 2, 'tags': 'runner'})
        self.next_marathon = self.elapsed + marathon.INTERVAL
        self.marathon_previous = None

    def take_activity_events(self):
        from ..events import Event
        events = [Event(**row) for row in self.activity_events]
        self.activity_events = []
        return events

    def spend_budget(self, project, s, delta, new_flags):
        """Count ``delta`` frames against the project's budget.

        A new Pokédex entry, a catch, trainee experience or a new event flag is progress and gives the
        project its whole budget again. The count is kept with the save, so a restart or a project
        that idled out and comes back later does not start over.
        """
        gains = project.get('gains', {})
        mark = [len(s.owned), gains.get('catches', 0), gains.get('experience', 0)]
        seen = project.setdefault('progress_mark', mark)
        events = tuple(ProgressEvent(kind) for kind, now, before in zip(('dex', 'catch', 'experience'), mark, seen)
                       if now > before)
        if new_flags:
            events += (ProgressEvent('flag'),)
        project['progress_mark'] = mark
        key, budget = budget_key(project), project_budget(project)
        self.director.monitor.start(key, budget=budget)
        self.director.monitor.observe(key, delta, events)

    def record_quality_search(self):
        project = self.project or {}
        if project.get('dv_hunt') and project.get('species'):
            key = str(project['species'])
            self.quality_searches[key] = min(SEARCH_BUDGET, self.quality_searches.get(key, 0) + 1)

    @staticmethod
    def support_trip(project, s, support, delta):
        """Whether this frame is part of a support trip the project started, or of the walk back from one.

        A heal after the project's battles, supplies for its catches and a box with room for them are
        the project's own errands, so they are not time it idled. The walk back ends on the map the
        trip left from. A walk back longer than the trip, or than two minutes when the trip was shorter,
        counts again from there. A restock in Saffron for a hunt in Mt. Moon walked back for over two
        minutes, and the hunt stood down on Route 4 before it reached the cave.
        """
        trip = project.get('support_trip')
        if support:
            if trip is None:
                trip = project['support_trip'] = {'map': s.map, 'frames': 0, 'return': 0}
            trip['frames'] += trip['return'] + delta
            trip['return'] = 0
            return True
        if trip is None:
            return False
        if s.map == trip['map'] or trip['return'] >= max(IDLE_BUDGET, trip['frames']):
            project.pop('support_trip')
            return False
        trip['return'] += 0 if s.in_battle else delta
        return True

    def observe(self,s, suspended=False, training_ready=True, training_active=None, overworld=True, support=False):
        delta = max(0,min(120,s.frame - self.last_frame)) if self.last_frame is not None else 0
        self.last_frame = s.frame
        self.elapsed += delta
        self.completed_champion |= champion(s)
        for chosen, flag in ((106, 'EVENT_GOT_HITMONLEE'), (107, 'EVENT_GOT_HITMONCHAN')):
            if event_set(s.event_flags, flag):
                self.dojo_choice = chosen
        self.director.forget_expired(self.elapsed)
        idle = CONTINUE
        if self.project and (not suspended or self.project['method'] in ('train', 'marathon')):
            project = self.project
            training_reason = None
            marathon_finished = False
            # Frames that count against the project's idle time and budget. A support trip's frames do
            # not. A Yellow hunt on Route 21 ran out of its expedition budget after three box changes.
            away = self.support_trip(project, s, support, delta)
            spent = 0 if away else delta
            if project['method'] == 'marathon':
                before = project['checkpoint']
                progressed, marathon_finished = marathon.observe(
                    project, s, delta, self.marathon_previous, overworld)
                self.marathon_previous = s if s.valid else None
                if progressed:
                    self.idle_frames = 0
                if before == 0 and project['checkpoint'] == 1:
                    self.activity_events.append({
                        'type': 'marathon', 'title': 'The Kanto Marathon is on!',
                        'body': 'Pallet Town to Celadon and back, with 11 checkpoints. '
                                'Wild Pokémon have not agreed to stay off the course.',
                        'priority': 2, 'tags': 'runner'})
            if project['method'] == 'marathon':
                self.remaining -= delta
            if len(self.project_flags) != len(s.event_flags):
                self.project_flags = list(s.event_flags)
            new_flags = any(now & ~before for now, before in zip(s.event_flags, self.project_flags))
            self.project_flags = [now | before for now, before in zip(s.event_flags, self.project_flags)]
            token = (s.owned, s.badges, s.items, s.coins,
                     tuple(sorted((p.species, p.level, p.experience) for p in s.party)))
            if project['method'] == 'train':
                gained = arrived = False
                previous_gain = project.get('gains', {}).get('experience', 0)
                trainee = self.trainee(s, project) if training_ready else None
                if trainee is not None:
                    mon = s.party[trainee]
                    project['parent'] = mon.species
                    # Reaching the party is a one-time preparation milestone. Keep it
                    # in the project so menu transitions and reloads cannot repeat it.
                    arrived = 'initial_experience' not in project
                    baseline = project.setdefault('initial_experience', mon.experience)
                    gains = project.setdefault('gains', {})
                    gains['experience'] = max(gains.get('experience', 0), mon.experience - baseline)
                    gains['levels'] = max(gains.get('levels', 0), mon.level - project['initial_level'])
                    gained = gains['experience'] > previous_gain
                    token = (mon.species, mon.level, mon.experience)
                else:
                    token = None
            elif project['method'] == 'evolve':
                # Experience toward a level evolution is progress. Without it a Dragonair that gained
                # levels all turn was deferred as a failure, and each failure doubled its wait.
                trainee = self.trainee(s, project)
                if trainee is not None:
                    mon = s.party[trainee]
                    baseline = project.setdefault('initial_experience', mon.experience)
                    gains = project.setdefault('gains', {})
                    gains['experience'] = max(gains.get('experience', 0), mon.experience - baseline)
            if project['method'] == 'train':
                active = (trainee is not None and not suspended
                          and (training_active if training_active is not None else training_ready))
                self.remaining, training_reason = training.observe(
                    project, spent, self.remaining, active, gained, arrived)
                clock = project['training_session']
                self.idle_frames = clock['active_idle'] if active else clock['preparation_idle']
            else:
                # First visits and completed battles count toward an expedition. Walking between
                # familiar maps, rearranging menus, and taking damage do not extend its deadline.
                # Time spent in a battle is not time lost wandering. A rematch that crossed Diglett's
                # Cave without Repels met a wild Pokémon every few steps, and those battles alone used up
                # the two minutes, so the League loop was given up before it left the cave.
                # A marathon is still observed while another goal's visit suspends it, so its race clock
                # runs on. That visit is not idle time for the marathon. A release visit of over two
                # minutes deferred it once the PC list could reach every slot.
                # A map first reached on a support trip is not a new route for the project either.
                moved = ((token is not None and self.progress_token is not None and token != self.progress_token)
                         or new_flags or s.map not in self.project_maps and not away
                         or (self.project['method'] in ('grass', 'surf', 'fish', 'safari', 'trade') or legendary_project(self.project))
                         and self.was_in_battle and not s.in_battle)
                self.director.monitor.start(self.project_key, budget=IDLE_BUDGET)
                idle = self.director.monitor.observe(self.project_key, 0 if s.in_battle or suspended else spent,
                                                     (ProgressEvent('project'),) if moved else ())
                if s.map not in self.project_maps:
                    self.project_maps.append(s.map)
                self.progress_token = token
                self.was_in_battle = bool(s.in_battle)
            target = self.project.get('species')
            if (legendary_project(project) and not s.in_battle
                    and (dex(target) not in s.owned or project.get('legendary_return')
                         and dex(target) in getattr(self, 'returned_legendaries', ()))
                    and project.get('flag') and event_set(s.event_flags, project['flag'])):
                self.abandon('Legendary encounter ended without a catch')
                return
            item = self.project.get('item')
            finished = (target and dex(target) in s.owned) or (not target and item and any(i==ITEMS[item] for i,q in s.items if q))
            if project.get('repeat'):
                caught = max(0, held_count(s, target) - project['initial_count'])
                project.setdefault('gains', {})['catches'] = max(project.get('gains', {}).get('catches', 0), caught)
                finished = caught >= project.get('catch_goal', 1)
            if project.get('event_return'):
                finished = project['event_return'] not in getattr(self, 'returned_events', {})
            if (snorlax_project(project) and not s.in_battle and project.get('flag')
                    and event_set(s.event_flags, project['flag'])):
                # The walking return closes once Route 12 is behind, so judge the battle here.
                finished = (max(0, held_count(s, target) - project['initial_count']) >= 1 if project.get('repeat')
                            else dex(target) in s.owned)
                if not finished:
                    self.abandon('Snorlax battle ended without a catch')
                    return
            if project.get('legendary_return'):
                finished = dex(target) not in getattr(self, 'returned_legendaries', ())
            if project.get('upgrade_evolution'):
                index = self.trainee(s, project)
                finished = index is not None and s.party[index].species == target
            if project['method'] == 'gift' and dex(target) in (106, 107):
                finished = event_set(s.event_flags, project['flag'])
            if project['method'] in ('gift', 'static') and not legendary_project(project) and target:
                held = project.setdefault('initial_held', project.get('initial_count', held_count(s, target)))
                if not finished and not s.in_battle and not self.available(s, project):
                    if held_count(s, target) <= held:
                        # The source left the room or the game closed it, for example the other Fighting
                        # Dojo ball was taken. Waiting on it could only end in a stand-down two minutes later.
                        self.abandon(f'{name(target)} is no longer offered here')
                        return
                    finished = True
            if self.project['method']=='fossil' and self.project.get('initial_owned'):
                finished = finished or bool(s.owned - set(self.project['initial_owned']))
            if self.project['method']=='trainer':
                finished = event_set(s.event_flags,self.project['flag'])
            if self.project['method']=='explore':
                finished = (s.map,s.x,s.y) == tuple(self.project['target'])
            if self.project['method']=='rematch':
                finished = s.hall_of_fame_count > self.project['hof_count'] or s.map == MAPS['HALL_OF_FAME']
            if project['method'] == 'marathon':
                finished = marathon_finished
            if project['method'] == 'train':
                finished = trainee is not None and s.party[trainee].level >= project['target_level']
            if training_reason and not s.in_battle and not finished:
                self.abandon(training_reason)
                return
            if budgeted(project):
                self.spend_budget(project, s, spent, new_flags)
            if finished or (self.remaining <= 0 and (project['method'] != 'train' or not s.in_battle)):
                # A project done or out of budget starts its next turn with the whole budget.
                self.director.monitor._table(SPENT).pop(budget_key(project), None)
                self.record_quality_search()
                self.finish_marathon(bool(finished))
                if finished and project.get('repeat'):
                    self.last_repeat[str(target)] = self.elapsed
                label = name(target) if target else item.replace('_',' ').title() if item else self.project['method'].title()
                if project['method'] == 'train':
                    label = f'{name(project["parent"])} toward level {project["target_level"]}'
                self.history = (self.history + [f'{"Completed" if finished else "Will revisit"}: {label}'])[-6:]
                progressed = bool(project.get('gains', {}).get('experience', 0) or project.get('gains', {}).get('catches', 0))
                self.director.finish(project, self.elapsed, bool(finished),
                                     'Target reached' if finished else 'Expedition time budget reached', progressed)
                self.project = None
            elif idle.stand_down and not s.in_battle:
                self.abandon('No encounter, training gain, or new route in two minutes')
        key = (s.owned, s.items, s.stored_pokemon, tuple((p.species,p.level) for p in s.party), s.event_flags, s.hidden_objects, self.completed_champion, self.version)
        if key != self.report_key:
            self.report_key = key
            self.report = self.describe(s)

    def gift_species(self):
        return gift_species(self.version)

    def sources(self):
        rows = {int(k):v for k,v in DATA['versions'].get(self.version, {}).items()}
        rows[SNORLAX] = [*rows.get(SNORLAX, ()), SNORLAX_SOURCE]
        return rows

    def returned_event(self, sid, source):
        for key, event in getattr(self, 'returned_events', {}).items():
            if key != 'fossil' and event['dex'] == dex(sid) and event['room'] == source['map']:
                return key
        return None

    def available(self,s,source):
        legendary = {'ARTICUNO': 144, 'ZAPDOS': 145, 'MOLTRES': 146, 'MEWTWO': 150}
        if legendary.get(source.get('fragment')) in getattr(self, 'closed_legendaries', ()):
            return False
        mode = source['method']
        bag = dict(s.items)
        if source.get('fragment') == 'ARTICUNO' and not any(70 in p.moves for p in s.party):
            return False
        if source.get('flag') in EVENTS and event_set(s.event_flags, source['flag']):
            return False
        if snorlax_project(source) and not (self.completed_champion and dict(s.items).get(ITEMS['POKE_FLUTE'])):
            # Before the League the story wakes Snorlax. Without the flute it cannot wake.
            return False
        if mode in ('gift','static'):
            objects = WORLD[source['map']]['objects']
            index = next((i for i,o in enumerate(objects) if source.get('fragment','') in o[4]),None)
            if index is not None:
                try:
                    if object_hidden(s,source['map'],index):
                        return False
                except ValueError:
                    pass
        # Yellow gives Bulbasaur to a trainer whose Pikachu is happy, and Squirtle after the Thunder Badge.
        if YELLOW and source.get('fragment') == 'MELANIE' and getattr(s, 'pikachu_happiness', 0) < 147:
            return False
        if YELLOW and source.get('fragment') == 'OFFICER_JENNY' and not s.badges & 4:
            return False
        if source['map'] in {MAPS['CERULEAN_CAVE_1F'], MAPS['CERULEAN_CAVE_2F'], MAPS['CERULEAN_CAVE_B1F']} and not self.completed_champion:
            return False
        if source.get('fragment') in ('HITMONLEE','HITMONCHAN'):
            return not any(event_set(s.event_flags,f) for f in ('EVENT_GOT_HITMONLEE','EVENT_GOT_HITMONCHAN'))
        if mode == 'fossil':
            return bool(bag.get(ITEMS[source['item']]) or event_set(s.event_flags,'EVENT_GAVE_FOSSIL_TO_LAB'))
        return True

    def describe(self,s):
        sources = self.sources()
        held = {p.species for p in s.party} | {sid for box,sid,level,nick in s.stored_pokemon}
        reachable = {sid for sid,rows in sources.items() if any(self.available(s,r) and r['method'] not in ('trade',) for r in rows)} | held
        # The unavailable starter families have no wild source in Red or Blue.
        for _ in range(4):
            for sid in tuple(reachable):
                if dex(sid) in REFUSES_EVOLUTION:
                    continue
                reachable.update(e['species'] for e in EVOS.get(sid,[]) if e['method'] != 'trade')
            for sid,rows in sources.items():
                if any(r['method']=='trade' and r['give'] in reachable for r in rows):
                    reachable.add(sid)
        entries = []
        for sid,mon in sorted(SPECIES.items(),key=lambda pair:pair[1]['dex']):
            d = mon['dex']
            parents = [(p,e) for p,rows in EVOS.items() for e in rows if e['species']==sid]
            if d in s.owned:
                status,reason = 'caught','Registered in the Pokédex'
            elif any(e['method']=='trade' for p,e in parents) and sid not in sources:
                status,reason = 'external','Requires a link trade'
            elif sid in reachable:
                status,reason = 'available','Available through encounters, gifts, trades, or evolution'
                if parents and not sources.get(sid):
                    reason = 'Evolve ' + name(parents[0][0])
            else:
                status,reason = 'unavailable','Requires another version, an unchosen gift, or a different acquisition method'
            if d == 151 and d not in s.owned:
                status,reason = 'external','Event Pokémon, not a normal encounter'
            if d == 137 and d not in s.owned:
                status,reason = 'available','Save coins for the Game Corner prize'
            if d in (134,135,136) and d not in s.owned and not any(dex(p)==133 for p in held) and any(i in s.owned for i in (134,135,136)):
                status,reason = 'unavailable','Requires another Eevee after the evolution choice'
            if status != 'caught' and d == 26 and YELLOW:
                status,reason = 'external','Pikachu refuses to evolve in Yellow. Raichu requires a link trade'
            if status != 'caught' and d in range(1,10) and not YELLOW:
                family = (d-1)//3
                if not any(i in s.owned for i in range(family*3+1,family*3+4)):
                    status,reason = 'external','Requires another starter through trading'
            rows = sources.get(sid,[])
            if status == 'unavailable' and any(r['method']=='static' for r in rows):
                reason = 'Encounter already resolved, or area not unlocked yet'
                if d in (144, 145, 146, 150) and any(
                        r.get('flag') and event_set(s.event_flags, r['flag']) for r in rows):
                    reason = 'Missed legendary encounter. Leave the area and prepare for its return'
                if d == 143 and event_set(s.event_flags, SNORLAX_SOURCE['flag']):
                    reason = 'Snorlax woke up and left. Walking brings it back to Route 12'
            entries.append({'dex':d,'name':name(sid),'species':sid,'status':status,'reason':reason,
                            'methods':sorted({r['method'] for r in rows})})
        evos = []
        for p in s.party:
            for e in EVOS.get(p.species,[]):
                if dex(e['species']) not in s.owned:
                    evos.append({'from':p.nick or name(p.species),'to':name(e['species']), 'method':e['method'],
                                 'requirement':e['requirement'],'level':p.level})
        return {'phase':'Pokédex expeditions' if self.completed_champion else 'Adventure in progress',
                'caught':len(s.owned),'available':sum(e['status']=='available' for e in entries),
                'entries':entries,'evolutions':evos[:6], 'version':self.version}

    def details(self):
        return {**self.report,'hunt':self.project,'remaining_seconds':max(0,self.remaining//60),
                'history':self.history, 'director': self.director.state_dict(),
                'peer_requests': self.demand(),
                'training': training.details(self.project, self.remaining),
                'marathon': marathon.details(self.marathon_records, self.project),
                'reason':'Collect, evolve, train, and explore in bounded projects. Repeated failures wait longer before retrying.'}

    def marathon_due(self, s, nav):
        return (self.elapsed >= self.next_marathon and s.saffron_open and nav.can_cut
                and sum(self.director.completed.values()) >= 4)

    def plan_token(self, s):
        """What the plan reads that can turn up a new project: the Pokédex, the bag, the boxes, the
        party, the event flags, the map, the projects still standing down, the marathon's turn, the
        purse and the other adventures' requests."""
        from .ledger import funds_short
        stood = self.director.monitor._table(STOOD_DOWN)
        return (s.owned, s.items, s.stored_pokemon, tuple((p.species, p.level) for p in s.party), s.event_flags,
                s.map, frozenset(key for key in stood if self.director.waiting(key, self.elapsed)),
                self.elapsed >= self.next_marathon, funds_short(s), tuple(sorted(self.demand().items())))

    def choose(self,s,nav,rng,main):
        from ..trade.preferences import identity
        if s.map in LEAGUE or not s.party or not s.owned or not event_set(s.event_flags,'EVENT_GOT_POKEDEX') or main.key.startswith(('heal','party_','teach_','restock')):
            return None
        if not self.completed_champion:
            # The story comes first until the Champion is beaten. Seed 37 after Brock spent 244 of 300
            # game minutes training partners toward evolutions and 16 more hunting grass beside Mt. Moon,
            # and never reached Misty. Catches and training the story needs come from story_goal: an HM
            # partner through teaching_goal and gym or League preparation through gym_goal. Wild
            # battles on the way still catch missing species.
            self.abandon('The story comes before side projects until the Champion is beaten')
            return None
        if self.project:
            return self.goal(s)
        token = self.plan_token(s)
        if token == self.idle_token:
            return None
        bag = dict(s.items)
        held = [(p.species,p.level,None) for p in s.party] + [(sid,level,box) for box,sid,level,nick in s.stored_pokemon]
        candidates = []
        travel = {}
        def add(project):
            key = str(project.get('species',0)) + ':' + project['method'] + ':' + str(project.get('map',0)) + ':' + str(project.get('fragment',''))
            if legendary_project(project):
                key = f'legendary:{project["species"]}:{project["map"]}'
            if project['method'] == 'evolve' and project.get('trainee_key'):
                key += ':' + project['trainee_key']
            if project['method'] == 'train':
                key = f'train:{project.get("trainee_key") or project["parent"]}:{project["target_level"]}'
                if project.get('scoped_partner'):
                    key += ':' + str(project['parent']) + ':' + project.get('trainee_nick', '')
            if not self.director.waiting(key, self.elapsed):
                goal = self.goal(s, project)
                distance = distance_to(goal.targets) if goal and goal.targets else None
                if distance is not None:
                    if project['method'] == 'train':
                        work_distance = distance_to(training_targets(self.version, project['initial_level']))
                        if work_distance is None:
                            return
                        preparation = distance + 80 if project.get('box') is not None else 0
                        project['travel_distance'] = work_distance + preparation
                    travel[key] = project.get('travel_distance', distance)
                    candidates.append({**project,'key':key})
        sources = self.sources()
        held_individuals = [asdict(mon) for mon in s.party] + s.storage_entries()
        best_tails = {}
        for mon in held_individuals:
            tail = assessment(mon)['dv_top_percent']
            if tail is not None:
                best_tails[mon['species']] = min(best_tails.get(mon['species'], 100), tail)
        searched = set()
        world = CollectionWorld(s, nav)
        from .ledger import ledger
        books = ledger()
        books.snapshot(s, kinds=(MONEY,))
        distance_to = nav.distance_lookup((s.map, s.x, s.y), s.frame)
        plateau_maps = {MAPS[n] for n in ('INDIGO_PLATEAU', 'INDIGO_PLATEAU_LOBBY',
                        'ROUTE_23', 'VICTORY_ROAD_1F', 'VICTORY_ROAD_2F', 'VICTORY_ROAD_3F')}
        if (s.map in plateau_maps
                and any(70 in mon.moves for mon in s.party)
                and distance_to(((MAPS['ROUTE_23'], 8, 138),)) is None):
            # At a project boundary, reopen the route instead of endlessly selecting
            # only the few species reachable from the League side of Victory Road.
            north = (s.map in (MAPS['INDIGO_PLATEAU'], MAPS['INDIGO_PLATEAU_LOBBY'])
                     or s.map == MAPS['ROUTE_23'] and s.y < 40
                     or s.map in (MAPS['VICTORY_ROAD_2F'], MAPS['VICTORY_ROAD_3F']) and s.x >= 24 and s.y >= 7)
            target = ((MAPS['VICTORY_ROAD_3F'], 27, 15) if north else (MAPS['ROUTE_23'], 8, 138))
            return Goal('collect_passage', 'Return to Kanto for more hunting grounds',
                        'Open the Victory Road passage before selecting another expedition', (target,))
        for sid,rows in sources.items():
            if dex(sid) in s.owned:
                rows = [source for source in rows if source['method'] in REPEATABLE
                        or self.returned_event(sid, source)
                        or source['method'] == 'fossil' and self.available(s, source)
                        or legendary_project(source) and dex(sid) in getattr(self, 'returned_legendaries', ())
                        or source['method'] == 'gift'
                        and dex(sid) in (106, 107) and dex(sid) == self.dojo_choice]
            for source in rows:
                if not self.available(s,source):
                    continue
                mode = source['method']
                if not feasible(source_requires(source, dex(sid) in s.owned), world, books, key='collection'):
                    continue
                selected_dojo = getattr(self, 'returned_events', {}).get('dojo', {}).get('dex', self.dojo_choice)
                if mode == 'gift' and dex(sid) in (106, 107) and dex(sid) != selected_dojo:
                    continue
                offered = self.trade_candidate(s, source) if mode == 'trade' else None
                if mode == 'trade' and offered is None:
                    continue
                if mode == 'grass' and source.get('level',100) > max(p.level for p in s.party)+3:
                    continue
                search_key = (sid,source['map'],mode,source.get('rod'))
                if search_key in searched:
                    continue
                searched.add(search_key)
                project = dict(source,species=sid)
                event_key = self.returned_event(sid, source)
                if event_key:
                    project.update(event_return=event_key, repeat=True, initial_count=held_count(s, sid), catch_goal=1,
                                   needed_capture=dex(sid) not in s.owned)
                elif mode == 'fossil' and dex(sid) in s.owned:
                    project.update(repeat=True, initial_count=held_count(s, sid), catch_goal=1)
                if mode in REPEATABLE:
                    project['needed_capture'] = (dex(sid) not in s.owned
                                                 or held_count(s, sid) < self.demand().get(dex(sid), 0))
                if mode in REPEATABLE and dex(sid) in s.owned:
                    project.update(repeat=True, initial_count=held_count(s, sid),
                                   catch_goal=1 if project['needed_capture'] else 3,
                                   dv_hunt=not project['needed_capture'],
                                   last_hunt=self.last_hunt.get(str(sid), -1))
                if offered is not None:
                    project.update(parent=source['give'], box=offered.get('box'),
                                   give_key=identity(offered))
                if legendary_project(project):
                    project['legendary'] = True
                    if dex(sid) in getattr(self, 'returned_legendaries', ()):
                        project.update(legendary_return=True, repeat=True, initial_count=held_count(s, sid), catch_goal=1,
                                       needed_capture=dex(sid) not in s.owned)
                goal = self.project_goal(s,project)
                if not goal or not goal.targets:
                    continue
                distance = distance_to(goal.targets)
                if distance is None:
                    continue
                add(project)
        individuals = [dict(asdict(mon), box=None) for mon in s.party] + s.storage_entries()
        preferences = self.trade_preferences()
        best_potential = {}
        for mon in individuals:
            best_potential[mon['species']] = max(best_potential.get(mon['species'], -1), potential_power(mon) or -1)
        for sid in dict.fromkeys(mon['species'] for mon in individuals):
            copies = [mon for mon in individuals if mon['species'] == sid
                      and preferences.get(identity(mon), {}).get('state') != 'offered']
            if not copies:
                continue
            mon = max(copies, key=quality)
            level, box, key = mon['level'], mon.get('box'), identity(mon)
            if held_count(s, sid) <= self.demand().get(dex(sid), 0):
                continue
            for evo in EVOS.get(sid, []):
                if evo['method'] == 'trade' or dex(sid) in REFUSES_EVOLUTION:
                    continue
                registered = dex(evo['species']) in s.owned
                evolved = dict(mon, species=evo['species'])
                upgrade = (key and potential_power(evolved) is not None
                           and potential_power(evolved) > best_potential.get(evo['species'], -1)
                           and training_investment(evolved, individuals)['eligible'])
                if registered and not upgrade:
                    continue
                if (dex(sid) == 133 and self.eevee_choice not in s.owned
                        and dex(evo['species']) != self.eevee_choice):
                    continue
                if evo['method'] == 'item' and not bag.get(ITEMS[evo['requirement']]) and evo['requirement'] == 'MOON_STONE':
                    continue
                if evo['method'] == 'level' and level >= 100:
                    continue
                if box is not None and not partner_exchange_possible(s):
                    continue
                project = {'species': evo['species'], 'parent': sid, 'method': 'evolve',
                           'evolution': evo, 'box': box, 'trainee_key': key,
                           'family': [sid, evo['species']], 'trainee_nick': mon.get('nick', ''),
                           'scoped_partner': True, 'upgrade_evolution': bool(registered),
                           'perfect_partner': is_perfect(mon)}
                if key and len(self.partner_matches(s, project)) != 1:
                    continue
                add(project)
        huntable = {p['species'] for p in candidates if p.get('dv_hunt')}
        counts = Counter(sid for sid, level, box in held)
        individuals = [dict(asdict(mon), box=None) for mon in s.party] + s.storage_entries()
        preferences = self.trade_preferences()
        # A stronger stored copy that cannot be withdrawn must not keep the party copy from training.
        exchange = partner_exchange_possible(s)
        reachable_best = {}
        for mon in individuals:
            if exchange or mon['box'] is None:
                reachable_best[mon['species']] = max(reachable_best.get(mon['species'], -1), potential_power(mon) or -1)
        for mon in individuals:
            sid, level, box = mon['species'], mon['level'], mon.get('box')
            family = training_family(sid)
            key = identity(mon)
            if counts[sid] <= self.demand().get(dex(sid), 0):
                continue
            if (potential_power(mon) or -1) < reachable_best.get(sid, -1):
                continue
            if level >= 100 or preferences.get(key, {}).get('state') == 'offered':
                continue
            reference = {'trainee_key': key, 'family': family, 'trainee_nick': mon.get('nick', ''), 'scoped_partner': True}
            if (key and len(self.partner_matches(s, reference)) != 1
                    or not key and sum(counts[relative] for relative in family) != 1):
                continue
            if box is not None and not partner_exchange_possible(s):
                continue
            if not can_train(mon):
                continue
            # Prefer missing evolutions before a general level milestone for this partner. A stone
            # counts too: a Weepinbell was being trained to level 100 with Victreebel unregistered.
            if any(evo['method'] != 'trade' and dex(evo['species']) not in s.owned for evo in EVOS.get(sid, [])):
                continue
            investment = training_investment(mon, individuals, hunt_available=sid in huntable,
                                             searches=self.quality_searches.get(str(sid), 0))
            if not investment['eligible']:
                continue
            # Aim for the next ten rather than the whole climb. Training to 100 in one project
            # held a partner for hundreds of game hours while trades and unregistered species
            # waited; a ten level step finishes, hands the turn back, and resumes later.
            add({**reference, 'method': 'train', 'parent': sid, 'family': family,
                 'trainee_key': key, 'box': box, 'initial_level': level,
                 'target_level': min(100, level - level % 10 + 10),
                 'investment_priority': investment['priority'],
                 'investment_reason': investment['reason'],
                 'perfect_partner': is_perfect(mon),
                 'mastery_needed': any(level_credit(relative) - set(self.milestones.get('level_100', ())) for relative in family)})
        if self.marathon_due(s, nav):
            add(marathon.candidate())
        from .ledger import funds_short
        short = funds_short(s)
        add({'method':'rematch','hof_count':s.hall_of_fame_count})
        porygon = next(sid for sid,mon in SPECIES.items() if mon['dex']==137)
        if 137 not in s.owned and (s.money >= 20000 or s.coins >= PORYGON_COINS.get(self.version, 9999)):
            add({'method':'prize','species':porygon,'map':MAPS['GAME_CORNER_PRIZE_ROOM']})
        for trainer in DATA.get('trainers',[]):
            if trainer['map'] in LEAGUE or event_set(s.event_flags,trainer['flag']):
                continue
            if trainer['map'] == s.map:
                add(dict(trainer,method='trainer'))
        unseen = []
        visited = {m for m,x,y in nav.visits}
        for m,w in WORLD.items():
            if m in visited or m in LEAGUE or m==s.map or not w['warps']:
                continue
            warp = w['warps'][0]
            target = (m,warp[0],max(0,warp[1]-1))
            unseen.append((m,target))
        rng.shuffle(unseen)
        for m,target in unseen[:8]:
            if distance_to((target,)) is not None:
                add({'method':'explore','map':m,'target':target})
                break
        for rod,room in RODS.items():
            if not bag.get(ITEMS[rod]):
                add({'method':'rod','item':rod,'map':MAPS[room],'room':room})
        if not bag.get(ITEMS['OLD_AMBER']) and 142 not in s.owned:
            if not event_set(s.event_flags,'EVENT_GOT_OLD_AMBER'):
                add({'method':'amber','item':'OLD_AMBER','map':MAPS['MUSEUM_1F']})
        fossil = getattr(self, 'returned_events', {}).get('fossil')
        if fossil and not bag.get(ITEMS[fossil['item']]):
            add({'method': 'return_fossil', 'map': fossil['room'], 'item': fossil['item'],
                 'event_return': 'fossil'})
        projects = {project['key']: project for project in candidates}
        options = [candidate(project, travel.get(project['key']), best_tails, short, s.owned, self.wild)
                   for project in candidates]
        self.project = self.director.select(options, projects)
        if self.project is None:
            # Nothing to do until the game changes, so the plan is not drawn again until then.
            self.idle_token = token
            return None
        # A catch is progress that gives the budget back, so a hunt's budget covers its first catch.
        self.project['expected_frames'] = ((travel.get(self.project['key']) or 0) * FRAMES_PER_TILE
                                           + kind_frames({**self.project, 'catch_goal': 1}, self.wild))
        shadow = getattr(self, 'shadow', None)
        if shadow is not None:
            # The arbiter decides here, so this point always agrees. The overworld chain around it
            # still reuses these candidates for its own comparison.
            shadow.changed('collection', self.project['key'])
            shadow.compare('collection', lambda: options, self.project['key'])
        if self.project['method'] == 'rematch':
            self.prepare_league_rotation(s)
        if self.project['method'] == 'marathon':
            self.next_marathon = self.elapsed + marathon.INTERVAL
            self.marathon_previous = None
        if self.project.get('dv_hunt'):
            self.last_hunt[str(self.project['species'])] = self.elapsed
        self.project['initial_owned'] = list(s.owned)
        self.idle_frames = 0
        self.project_maps = [s.map]
        self.project_flags = list(s.event_flags)
        self.progress_token = None
        # Any other project's budget lives on the monitor and keeps what it spent before.
        if not budgeted(self.project):
            self.remaining = training.TRAINING_BUDGET if self.project['method'] == 'train' else marathon.BUDGET
        nav.path.clear()
        return self.goal(s)

    def project_goal(self,s,p):
        mode=p['method']
        if mode == 'return_fossil':
            room = WORLD[p['map']]['symbol']
            fragment = 'SCIENTIST2' if p['item'] == 'OLD_AMBER' else p['item']
            return object_goal('collect_pickup', 'Collect another fossil', 'Bring it to the Cinnabar lab', room, fragment)
        if mode == 'marathon':
            return marathon.goal(p)
        sid=p.get('species')
        if mode in ('grass','surf','fish','safari'):
            points=tiles(p)
            purpose = ('a partner another adventure needs' if self.demand().get(dex(sid), 0)
                       else 'more chances to find high DV partners' if p.get('dv_hunt') else 'another partner for the collection' if p.get('repeat') else 'a missing Pokédex entry')
            return Goal('collect_hunt','Find '+name(sid),f'Search {place(p["map"])} for {purpose}',
                        tuple(t[:3] for t in points), approaches=tuple(t for t in points if t[3]))
        if mode in ('gift','static','trade','fossil'):
            if mode == 'static' and dex(sid) == 144 and not all(event_set(s.event_flags, flag) for flag in
                    ('EVENT_SEAFOAM4_BOULDER1_DOWN_HOLE', 'EVENT_SEAFOAM4_BOULDER2_DOWN_HOLE')):
                return at('collect_seafoam_current', 'Slow the current for Articuno',
                          'Push the Seafoam boulders into the holes before using Surf',
                          'SEAFOAM_ISLANDS_B3F', 6, 15)
            room=WORLD[p['map']]['symbol']
            fragment = p['fragment']
            if mode=='trade':
                fragment=fragment or TRADE_NPCS[room]
            if mode=='gift' and dex(sid) in (106,107) and not event_set(s.event_flags,'EVENT_BEAT_KARATE_MASTER'):
                fragment='KARATE_MASTER'
            if mode=='gift' and dex(sid)==133:
                fragment='EEVEE_POKEBALL'
            if mode=='fossil' and event_set(s.event_flags,'EVENT_LAB_STILL_REVIVING_FOSSIL'):
                return at('collect_fossil_walk','Give the fossil lab time','Step outside while the fossil is revived','CINNABAR_ISLAND',6,10)
            return object_goal('collect_'+mode,'Collect '+name(sid),'Visit a remaining source for the Pokédex',room,fragment)
        if mode=='rematch':
            if s.map != MAPS['INDIGO_PLATEAU_LOBBY']:
                # Money stops at 999,999, so at the cap a rematch earns experience only.
                purpose = 'Earn prize money and experience for collecting' if s.money < 999999 else 'Earn experience while nothing else is left'
                return at('collect_rematch','Return for a League rematch',purpose,'INDIGO_PLATEAU_LOBBY',8,10)
            return object_goal('league_lorelei','Begin a League rematch','Fund the next expeditions' if s.money < 999999 else 'Run the League again','LORELEIS_ROOM','LORELEI')
        if mode=='trainer':
            return object_goal('collect_trainer','Meet an unbeaten trainer','Explore and earn experience and supplies',WORLD[p['map']]['symbol'],p['fragment'])
        if mode=='explore':
            return Goal('collect_explore','Explore '+place(p['map']),'Visit an area that has not been explored',(tuple(p['target']),))
        if mode=='prize':
            if not dict(s.items).get(ITEMS['COIN_CASE']):
                return object_goal('collect_coins','Get the Coin Case','Prepare to exchange coins for Porygon','CELADON_DINER','FISHER')
            cost = PORYGON_COINS.get(self.version, 9999)
            if s.coins < cost:
                if s.money < 10000:
                    self.remaining=0
                    return None
                return at('collect_coins','Save coins for Porygon',f'{s.coins} of {cost} coins saved','GAME_CORNER',5,8,'up')
            return at('collect_prize','Collect Porygon','Exchange saved coins for a new Pokédex entry','GAME_CORNER_PRIZE_ROOM',4,3,'up')
        if mode=='rod':
            return object_goal('collect_rod','Obtain '+p['item'].replace('_',' ').title(),'Unlock more fishing encounters',p['room'],'FISHING_GURU')
        if mode=='amber':
            return object_goal('collect_amber','Collect Old Amber','Revive Aerodactyl at the Cinnabar lab','MUSEUM_1F','SCIENTIST2')
        return None

    _partner_cache = [None, ()]

    @staticmethod
    def partner_matches(s, project):
        """Every held copy of the project's trainee.

        Several planners ask on each step and the answer reads the whole PC, so it is kept until
        the party, the PC or the trainee changes. Callers get their own rows.
        """
        scoped = bool(project.get('scoped_partner'))
        key = (tuple(s.party), getattr(s, 'stored_details', None), getattr(s, 'stored_pokemon', None),
               project.get('trainee_key'), scoped, tuple(project['family']) if scoped else None,
               project.get('trainee_nick') if scoped else None)
        try:
            hash(key)
        except TypeError:
            return Collection._partner_matches(s, project)
        cache = Collection._partner_cache
        if cache[0] != key:
            cache[:] = [key, tuple(Collection._partner_matches(s, project))]
        return [dict(row) for row in cache[1]]

    @staticmethod
    def _partner_matches(s, project):
        from ..trade.preferences import identity
        key = project.get('trainee_key')
        rows = [dict(asdict(mon), party_index=i) for i, mon in enumerate(s.party)
                if same(identity(asdict(mon)), key)]
        rows += [mon for mon in s.storage_entries() if same(identity(mon), key)]
        if project.get('scoped_partner'):
            rows = [mon for mon in rows if mon['species'] in project['family']]
            nick = project.get('trainee_nick')
            default_names = {SPECIES[sid]['name'].upper() for sid in project['family']}
            if nick and nick.upper() not in default_names:
                rows = [mon for mon in rows if mon.get('nick') == nick]
        return rows

    @staticmethod
    def trainee(s, project):
        if project.get('trainee_key'):
            matches = Collection.partner_matches(s, project)
            return matches[0].get('party_index') if len(matches) == 1 else None
        family = project.get('family', [project.get('parent')])
        return next((i for i, mon in enumerate(s.party) if mon.species in family), None)

    def trade_deposit_target(self, s, project):
        """Keep battle strength, field moves, and reserved partners while making space."""
        from .team import potential, stays_in_party
        from ..trade.preferences import identity
        choices = self.trade_preferences()
        strongest = max(range(len(s.party)), key=lambda i: s.party[i].level, default=None)
        candidates = [i for i, mon in enumerate(s.party)
                      if i != strongest and mon.species != project['give'] and not stays_in_party(s, mon)
                      and choices.get(identity(asdict(mon)), {}).get('state') not in ('locked', 'offered')
                      and not any(move in (15, 19, 57, 70, 148)
                                  and not any(move in other.moves for j, other in enumerate(s.party) if j != i)
                                  for move in mon.moves)]
        return min(candidates, key=lambda i: s.party[i].level * 10 + potential(s.party[i].species)) if candidates else None

    def trade_candidate(self, s, project):
        """Choose a safe NPC exchange partner, including a reserve still in the PC."""
        from ..trade.preferences import identity
        preferences = self.trade_preferences()
        party = [dict(asdict(mon), party_index=i) for i, mon in enumerate(s.party)]
        rows = party + s.storage_entries()
        identities = Counter(identity(mon) for mon in rows)
        candidates = []
        for mon in rows:
            key = identity(mon)
            if (mon['species'] != project['give'] or is_perfect(mon) or is_shiny(mon)
                    or automatic_trade_protected(mon, rows)):
                continue
            if project.get('give_key') and not same(key, project['give_key']):
                continue
            if preferences.get(key, {}).get('state') in ('locked', 'offered'):
                continue
            if key and identities[key] != 1:
                continue
            index = mon.get('party_index')
            if mon['level'] >= max((p.level for p in s.party), default=0):
                continue
            if any(move in (15, 19, 57, 70, 148)
                   and not any(move in p.moves for i, p in enumerate(s.party) if i != index)
                   for move in mon.get('moves', ())):
                continue
            if index is None and (not storage_exchange_possible(s)
                                  or len(s.party) >= 6 and self.trade_deposit_target(s, project) is None):
                continue
            candidates.append(mon)
        return min(candidates, key=quality) if candidates else None

    def prepare_league_rotation(self, s):
        from ..trade.preferences import identity
        held = [asdict(mon) for mon in s.party] + s.storage_entries()
        keys = {identity(mon) for mon in held} - {None}
        appearances = {}
        for key, count in self.league_appearances.items():
            if key not in keys:
                # A count saved before trade keys named the evolution family follows its Pokémon
                # when exactly one held Pokémon has that trainer and those stats.
                matches = [held_key for held_key in keys if same(held_key, key)]
                key = matches[0] if len(matches) == 1 else None
            if key:
                appearances[key] = max(count, appearances.get(key, 0))
        self.league_appearances = appearances
        for mon in s.party:
            key = identity(asdict(mon))
            if key:
                self.league_appearances.setdefault(key, 1)
        if not storage_exchange_possible(s):
            return
        reserve = league_rotation.select_reserve(s, self.trade_preferences(), self.league_appearances)
        if reserve:
            self.project.update(parent=reserve['species'], trainee_key=identity(reserve),
                                trainee_nick=reserve['nick'], family=[reserve['species']],
                                scoped_partner=True, box=reserve['box'], league_rotation=True)

    def league_rotation_goal(self, s, project):
        from ..trade.preferences import identity
        if not project.get('league_rotation') or project.get('rotation_ready'):
            return None
        matches = self.partner_matches(s, project)
        if len(matches) != 1 or self.trade_preferences().get(project['trainee_key'], {}).get('state') in ('locked', 'offered'):
            project['rotation_ready'] = True
            return None
        partner = matches[0]
        if 'party_index' in partner:
            project['rotation_ready'] = True
            for mon in s.party:
                key = identity(asdict(mon))
                if key:
                    self.league_appearances[key] = self.league_appearances.get(key, 0) + 1
            return None
        if (not storage_exchange_possible(s) or len(s.party) >= 6
                and league_rotation.deposit_target(s, self.trade_preferences(), self.league_appearances) is None):
            project['rotation_ready'] = True
            return None
        project['box'] = partner['box']
        return Goal('party_league', 'Rotate the League team',
                    'Bring ' + (partner.get('nick') or name(partner['species'])) + ' out for the next rematch',
                    CENTERS, 'up', True)

    def goal(self,s,project=None):
        from ..trade.preferences import identity
        p=self.project if project is None else project
        if not p:
            return None
        if p['method'] == 'rematch' and s.map not in LEAGUE:
            rotation = self.league_rotation_goal(s, p)
            if rotation:
                return rotation
        if p['method'] == 'trade':
            partner = self.trade_candidate(s, p)
            if partner is None:
                return None
            p['parent'] = p['give']
            p['box'] = partner.get('box')
            p['give_key'] = identity(partner)
            if 'party_index' not in partner:
                return Goal('party_collection', 'Prepare an NPC trade',
                            'Retrieve ' + name(p['give']) + ' from storage for ' + name(p['species']),
                            CENTERS, 'up', True)
        if p['method'] in ('evolve', 'train'):
            if p.get('trainee_key') and len(self.partner_matches(s, p)) != 1:
                return None
            index = self.trainee(s, p)
            if index is None:
                if p.get('trainee_key'):
                    matches = [mon for mon in self.partner_matches(s, p) if 'party_index' not in mon]
                    if len(matches) != 1:
                        return None
                    p['box'] = matches[0]['box']
                if not partner_exchange_possible(s):
                    return None
                return Goal('party_collection','Withdraw a training partner','Keep the main battlers and bring a reserve out of storage',CENTERS,'up',True)
            if p['method'] == 'train':
                return Goal('collect_train', f'Train {s.party[index].nick or name(s.party[index].species)} to level {p["target_level"]}',
                            f'Level {s.party[index].level} of {p["target_level"]}. Stay with this partner while training is productive',
                            training_targets(self.version, s.party[index].level))
            evo=p['evolution']
            if evo['method']=='item':
                wait_for = evolution_wait(asdict(s.party[index]), evo)
                if wait_for:
                    level, move = wait_for
                    return Goal('collect_train', f'Learn {move_name(move)} before evolving',
                                f'Train {s.party[index].nick or name(p["parent"])} to level {level} before using a stone',
                                evolution_training_targets(self.version, s.party[index].level))
                if not dict(s.items).get(ITEMS[evo['requirement']]):
                    return at('collect_stone','Buy an evolution stone','Complete another Pokédex entry','CELADON_MART_4F',5,5,'down')
                return Goal('collect_evolve','Evolve '+name(p['parent']), 'Use '+evo['requirement'].replace('_',' ').title(),((s.map,s.x,s.y),))
            return Goal('collect_train','Train '+name(p['parent'])+' toward '+name(p['species']),
                        f'Work toward level {evo["requirement"]}, then resume other activities',
                        evolution_training_targets(self.version, s.party[index].level))
        if p['method'] in ('gift','fossil') and len(s.party)>=6:
            # A party of field-move holders, Yellow's Pikachu and the strongest battler has nothing to
            # deposit. Offering the gift anyway parked the adventure at a PC until the project timed out.
            if not partner_exchange_possible(s):
                return None
            return Goal('party_collection_space','Make room for a gift','Store a reserve before receiving a Pokémon',CENTERS,'up',True)
        return self.project_goal(s,p)
