"""Bounded collecting expeditions and evolution projects for a continuing adventure."""
import random
from collections import Counter
from dataclasses import asdict
from ..duplicates import quality
from pokecore.identity import same
from ..pokemon import experience_at_level
from ..investment import automatic_trade_protected, training_investment, potential_power, rarity, SEARCH_BUDGET
from functools import lru_cache, partial
from ..game_data import current_variant, load

from .progression import GRASS_TILES, Goal

YELLOW = current_variant() == 'yellow'
# Yellow's Pikachu refuses the Thunder Stone, and the game treats every Pikachu
# the player caught as its partner, so Raichu only arrives through a link trade.
REFUSES_EVOLUTION = {25} if YELLOW else set()
from .navigation import DIRS
from .director import AdventureDirector, category, new_entry
from ..planning import values
from ..planning import arbiter, catalogue, decide, pin
from ..planning.arbiter import NOT_HUNT, Candidate, Tier, hunt
from ..planning import cost
from ..planning.cost import FRAMES_PER_TILE
from ..planning.shadow import Shadow
from ..planning.conditions import Can, Count, Item, Requirements, feasible
from ..planning.ledger import MONEY, Need
from ..planning.monitor import CONTINUE, ProgressEvent
from ..planning.goals import Abandon, GoalRun
from . import kinds, training, marathon, league_rotation
from .. import progress_events
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
    """Whether the monitor keeps ``project``'s budget, as for every kind without its own clock."""
    return not kinds.rules(project['method']).own_clock


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


def improves(s, species, dvs, rated=None, watch=None):
    """True when the PC would keep a wild ``species`` with ``dvs`` (pcvalue.worth): a new entry, a
    shiny, a copy its evolution family or a plan needs, or a copy at least RARITY_STEP times rarer than
    every copy held, which the PC visit it brings would not release, nor a rarer copy for it. A held
    copy without DV data, as in a compact snapshot, is not counted. ``rated`` rates the PC with extra
    rows as the next release does (the policy's pc_rated). Without it the PC is rated without trade
    settings or plans. A copy kept for an improve reason is noted on ``watch``, the goal watch, so
    its catch writes an ``improve`` row. Before the Champion a copy only its family would keep is not
    caught (pcvalue.worth's story).

    This is the Gen I catch rule for an owned species. Every path that throws a ball at one asks it:
    an incidental catch, the Safari Zone, a DV hunt, a repeat project and a returned legendary. A
    missing entry, a shiny and a field-move carrier keep their own rules, and a missing entry is a
    keep here anyway."""
    from .. import pcvalue
    from .team import storage_headroom
    boxes = hasattr(s, 'box_counts')
    found = pcvalue.worth(_with_new(s, species, dvs, rated), missing=dex(species) not in s.owned,
                          headroom=storage_headroom(s) if boxes else None,
                          active_box=getattr(s, 'active_box', None), room=catch_room(s) if boxes else None,
                          story=not champion(s))
    if watch is not None:
        watch.expect(dex(species), dvs, found)
    return found.keep


def catch_room(s):
    """Free slots a catch may fill, across the party and every box (pcvalue.reserve_allows)."""
    from .team import storage_headroom
    return storage_headroom(s) + max(6 - len(s.party), 0)


def reserve_allows(s, species, dvs, rated=None):
    """Whether a catch with its own rule, as a missing entry, a field-move carrier or a shiny is, may
    take a slot from the reserve (pcvalue.reserve_allows). ``rated`` is as in improves."""
    from .. import pcvalue
    if not hasattr(s, 'box_counts') or catch_room(s) > pcvalue.UPGRADE_RESERVE:
        return True
    return pcvalue.reserve_allows(_with_new(s, species, dvs, rated), catch_room(s), missing=True)


def _with_new(s, species, dvs, rated=None):
    """The PC rated as the next release rates it, with a wild ``species`` holding ``dvs`` last."""
    from ..events import LEGENDARY_DEX
    from .. import pcvalue
    from .team import release_rated
    number = dex(species)
    # A caught legendary is rated as one, as release_rated rates it once held.
    candidate = pcvalue.Entry((-1, 0), (number, 0), SPECIES.get(species, {}).get('name', '?'), 5,
                              dvs=tuple(dvs or ()), origin='legendary' if number in LEGENDARY_DEX else 'caught',
                              record={'species': species, 'dvs': dvs})
    return rated(extra=(candidate,)) if rated else release_rated(s, extra=(candidate,))


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


def candidate(project, travel, tails, short, owned, wild=None, champion=False):
    """The arbiter's candidate for a project.

    Values come from planning/values.py. Expected frames are the walk to the project at the shared
    tile estimate in planning/cost.py, plus a catch priced from ``wild``, the cartridge's own encounter
    odds, or the per-kind EXPECTED_FRAMES, the training step at FRAMES_PER_EXPERIENCE or the race clock. A
    quality hunt is worth each catch's expected drop in the species' best DV tail, once per catch. A
    hunt for another copy of a registered species sits in HUNT_TIER, below training for a credit.
    A due marathon sits in Tier.RACE, after new entries and before training. It is only offered once due.
    A hunt is marked for the Collector style. ``champion`` says whether the Champion is beaten, and a
    project with a walk to it is catchable now, since the collection offers only sources open now.
    """
    method, sid = project['method'], project.get('species')
    tier = Tier.PROGRESS
    kind = NOT_HUNT
    if method == 'rematch':
        tier = Tier.UPKEEP if short else Tier.FILLER
        value = values.rematch(short)
    elif method == 'marathon':
        tier, value = Tier.RACE, values.SMALL
    elif method in ('explore', 'trainer'):
        tier, value = Tier.FILLER, values.SMALL
    elif method == 'train' and project.get('mastery_needed'):
        tier, value = Tier.UPGRADE, values.level_step(project['initial_level'], project['target_level'])
    elif method == 'train':
        # A family with its level 100 credit gains nothing the Pokédex counts, so its training is filler.
        tier, value = Tier.FILLER, values.SMALL
    elif legendary_project(project):
        # A returned legendary the Pokédex already has is a repeat, not an entry.
        tier, value = (Tier.PROGRESS, values.NEW_ENTRY) if dex(sid) not in owned else (Tier.UPGRADE, values.SMALL)
    elif new_entry(project) or project.get('needed_capture') or method in ('rod', 'amber', 'return_fossil'):
        # A rod or the Old Amber opens new entries, and a needed repeat is another adventure's entry.
        value = values.NEW_ENTRY
    elif project.get('dv_hunt') and tails.get(sid) is not None:
        tier, value = HUNT_TIER, values.quality_catch(tails[sid] / 100) * project.get('catch_goal', 1)
        kind = hunt(champion, travel is not None)
    else:
        tier, value = (HUNT_TIER if project.get('repeat') else Tier.UPGRADE), values.SMALL
        if project.get('repeat'):
            kind = hunt(champion, travel is not None)
    if method == 'train':
        frames = training_frames(project)
    elif method == 'marathon':
        frames = marathon.BUDGET
    else:
        frames = kind_frames(project, wild)
    frames += (travel or 0) * FRAMES_PER_TILE
    return Candidate(project.get('key', method), tier, value, frames, hunt=kind, goal=shadow_kind(project))


def boxed_trainee(project):
    return project['method'] == 'train' and project.get('box') is not None


def party_first(options, projects):
    """``options`` without the boxed trainees that a party trainee matches or beats on tier.

    A trainee in the party keeps training before a boxed one comes out. After step 5 a boxed low level
    partner's step looked cheap by experience, so Red and Yellow withdrew a new one every few minutes, and
    each swap took a PC trip of about 10000 frames that the walk price did not show. A boxed trainee in a
    higher tier, such as one still short of a level 100 credit while the party trainee is not, still comes
    out. ``projects`` maps each option's key to its project.
    """
    party = [option.tier for option in options
             if projects[option.key]['method'] == 'train' and not boxed_trainee(projects[option.key])]
    if not party:
        return options
    return [option for option in options if not (boxed_trainee(projects[option.key]) and option.tier >= min(party))]


def project_budget(project):
    return kinds.rules(project['method']).budget(project)


def budget_key(project):
    """The monitor key of a project's budget, apart from its idle count under the project key."""
    return 'budget:' + project.get('key', project['method'])


def project_label(project):
    """A project's name in the plan history."""
    return name(project['species']) if project.get('species') else project['method'].title()


CENTERS = tuple((m, 13, 4) for m, w in WORLD.items() if 'Pokecenter' in w['name'] and w['width'] == 14)
CENTERS += ((MAPS['INDIGO_PLATEAU_LOBBY'], 15, 8),)
LEAGUE = {MAPS[n] for n in ('LORELEIS_ROOM','BRUNOS_ROOM','AGATHAS_ROOM','LANCES_ROOM','CHAMPIONS_ROOM','HALL_OF_FAME')}
REPEATABLE = {'grass', 'surf', 'fish', 'safari'}


def throw_signature(s):
    """What can change a throw's odds: the party's species and moves and the kinds of ball held."""
    party = sorted((mon.species, tuple(sorted(move for move in mon.moves if move))) for mon in s.party)
    balls = {ITEMS[name] for name in ('POKE_BALL', 'GREAT_BALL', 'ULTRA_BALL')}
    return repr((party, sorted(item for item, count in s.items if count and item in balls)))
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


def wild_dvs(raw):
    """A wild Pokémon's two DV bytes as HP, Attack, Defense, Speed and Special, the order held copies use."""
    from pokecore.dvs import hp_dv
    attack, defense, speed, special = raw[0] >> 4, raw[0] & 15, raw[1] >> 4, raw[1] & 15
    return hp_dv(attack, defense, speed, special), attack, defense, speed, special


def picker_group(project, title, owned):
    """The group and label a manager picks ``project`` under: one thing they want, whatever the place.

    Every route, water and Safari zone a species is found in serves one want, so they share a group. The
    planner keeps its own key for each place and the picker runs the best ranked of them.
    """
    method, sid = project['method'], project.get('species')
    if method == 'train':
        level = project['target_level']
        return ('train', project['parent'], level), f'Train {name(project["parent"])} to {level}'
    if sid is None or method not in CATCH_MODES + ('gift', 'trade', 'fossil', 'prize', 'evolve'):
        return ('title', title), title
    who = name(sid)
    if legendary_project(project):
        return ('get', sid), f'Get {who}'
    if method == 'evolve':
        if project.get('upgrade_evolution'):
            return ('evolve_better', sid), f'Better {who} (evolve {name(project["parent"])})'
        return ('evolve', sid), f'Evolve {name(project["parent"])} into {who}'
    if project.get('dv_hunt'):
        return ('better', sid), f'Better {who} (DV hunt)'
    if dex(sid) not in owned:
        verb = 'Catch' if method in CATCH_MODES else 'Trade for' if method == 'trade' else 'Get'
        return ('missing', sid), f'{verb} {who} (missing entry)'
    if project.get('needed_capture'):
        return ('needed', sid), f'Catch another {who} (partner needed)'
    return ('another', sid), f'Get another {who}'


def storage_exchange_possible(s):
    """Taking a Pokemon out needs a free party slot, or somewhere to deposit a reserve first."""
    return len(s.party) < 6 or not s.box_full or s.next_free_box is not None


CATCH_MODES = ('grass', 'surf', 'fish', 'safari', 'static')
ANY_BALL = Count(tuple(ITEMS[n] for n in ('POKE_BALL', 'GREAT_BALL', 'ULTRA_BALL', 'MASTER_BALL')))
# A repeat hunt for an owned species throws more than one ball, and the Master Ball is never one of them.
HUNT_BALLS = Count(tuple(ITEMS[n] for n in ('POKE_BALL', 'GREAT_BALL', 'ULTRA_BALL')), 5)
SAFARI_ENTRY = Need(money=800)
# Plain words for each condition source_requires asks, for the goal catalogue's why_not.
NEED_WORDS = {Can('catch'): 'room to keep a catch', ANY_BALL: 'a Poké Ball', Can('surf'): 'a Pokémon that can use Surf',
              Can('take'): 'room to take it', HUNT_BALLS: 'five Poké Balls',
              **{Item(ITEMS[rod]): 'the ' + rod.replace('_', ' ').title() for rod in RODS}}
# Why the catalogue lists a source the offers draw left out, beside the failures in planning/decide.py.
NO_STEP = decide.Failure(decide.NOT_NOW, 'it cannot start from here yet')
NO_PARTNER = decide.Failure(decide.NOT_NOW, 'no Pokémon to trade for it yet')
TOO_STRONG = decide.Failure(decide.NOT_NOW, 'the wild Pokémon there are too strong for the party')
DEFERRED = decide.Failure(decide.NOT_NOW, 'it waits for a new move, party member or ball to catch it')
SEARCHED = decide.Failure(decide.NOT_NOW, 'its searches for a better copy are spent')
TRAINS_FIRST = decide.Failure(decide.NOT_NOW, 'a Pokémon in the party trains first')


def needs(found):
    """The Failure that names what a source's ``found`` Feasibility is missing."""
    words = [NEED_WORDS.get(condition, 'something it needs') for condition in found.missing]
    if found.shortfall is not None:
        words.append('more money')
    return decide.Failure(decide.NEEDS, 'needs ' + ' and '.join(words))


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


# Another adventure's partner requests last 3 game minutes. The coordinator sends them again sooner.
DEMAND_FRAMES = 10_800


class Collection:
    def __init__(self):
        self.version = 'red'
        # The project under way, a GoalRun (planning/goals.py), or None.
        self.project = None
        self.remaining = 0
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
        # Species left for a new move, member or ball, by throw_signature (planning.throws).
        self.deferred_catches = {}
        self.peer_demand = {}
        self.demand_until = 0
        # The policy context clock at the last step, in game frames that never rewind. Never saved.
        # The director's stand-downs, the marathon's turn and the pickups' waits count on it, so a
        # reload neither restarts nor stretches them.
        self.clock = 0
        self.next_marathon = 0
        self.marathon_records = {}
        self.activity_events = []
        self.marathon_previous = None
        # The arbiter's picks beside the director's, for the log and the replay audit. Never saved.
        self.shadow = Shadow()
        # The key of the project the pick last started, its arbiter candidate and the candidates it was
        # weighed with, by key, which the overworld decision weighs the project under way by. Never saved.
        self.weighed = None
        # The next activity a manager set (planning/pin.py). Never saved.
        self.pin = None
        # The project a pin set aside, with what it had done, which resumes when the pin's run ends.
        self.paused = None
        # The pick's weighing of the paused project, given back with it. Never saved.
        self.paused_weighed = None

    def demand(self):
        return self.peer_demand if self.clock < self.demand_until else {}

    def set_demand(self, requests, clock=None):
        """Keep the partners other adventures ask for until DEMAND_FRAMES pass on the clock that
        never rewinds. ``clock`` is the host's reading when the request arrives between steps."""
        self.clock = max(self.clock, clock or 0)
        self.peer_demand = dict(requests)
        self.demand_until = self.clock + DEMAND_FRAMES

    def repeat_target(self, species, map_id=None, snapshot=None, dvs=None, rated=None, watch=None):
        """The species a wild battle should catch as a repeat, or None.

        A returned legendary, a DV hunt's species on its map and a repeat project's species are
        targets. Given the wild ``dvs`` and the ``snapshot``, a target is only taken as a catch the PC
        would keep (improves, with ``rated`` as there). Otherwise Yellow's Tauros hunt caught every
        owned Nidoran, Cubone and Exeggcute in the Safari Zone and released them at the next PC.
        """
        project = self.project or {}
        if dex(species) in getattr(self, 'returned_legendaries', ()):
            target = species
        elif project.get('dv_hunt') and map_id == project.get('map'):
            target = species
        else:
            target = project.get('species') if project.get('repeat') else None
        if target == species and snapshot is not None and dvs is not None and not improves(snapshot, species, dvs, rated, watch):
            if dex(species) in getattr(self, 'returned_legendaries', ()) and snapshot.in_battle:
                # Close the return so neither the plan nor the retry timers bring back a refused legendary.
                self.declined_returns = getattr(self, 'declined_returns', set()) | {dex(species)}
                self.returned_legendaries = set(self.returned_legendaries) - {dex(species)}
            return None
        return target

    def state_dict(self):
        return {**{k:getattr(self,k) for k in ('project','remaining','eevee_choice','dojo_choice','history','completed_champion','league_appearances','project_maps','project_flags','last_repeat','last_hunt','quality_searches','deferred_catches','next_marathon','marathon_records','activity_events','paused')},
                'director': self.director.state_dict()}

    def defer(self, s, species):
        """Leave ``species`` uncaught until the party or the balls held change (planning.throws)."""
        self.deferred_catches[str(species)] = throw_signature(s)

    def deferred(self, s, species):
        """Whether a catch of ``species`` waits for a new move, member or ball, so no hunt goes for it."""
        return self.deferred_catches.get(str(species)) == throw_signature(s)

    @property
    def project(self):
        return self._project

    @project.setter
    def project(self, record):
        """Run ``record``, a GoalRun, or a project dict from a save or a test, which becomes one."""
        if record and not isinstance(record, GoalRun):
            record = GoalRun.from_dict(record, kinds.rules(record['method']))
        self._project = record

    @property
    def project_key(self):
        return self.project.get('key', self.project['method']) if self.project else None

    def hunt(self, snapshot):
        """The project's target species and DV rule for the encounter counters, or None.

        Only a project that catches wild Pokémon over and over is a hunt. A DV hunt's rule is the
        catch rule it throws a ball by (improves). Any other hunt takes any DVs.
        """
        project = self.project or {}
        species = project.get('species')
        if not kinds.rules(project.get('method')).wild or not species:
            return None
        if project.get('dv_hunt'):
            return dex(species), lambda raw: improves(snapshot, species, wild_dvs(raw))
        return dex(species), None

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
        self.director.monitor.set_spent(budget_key(project), project_budget(project) - frames)

    @property
    def idle_frames(self):
        """Frames the current project has gone without progress, as the director's monitor counts them."""
        key = self.project_key
        return self.director.monitor.spent(key) if key is not None else 0

    @idle_frames.setter
    def idle_frames(self, frames):
        key = self.project_key
        if key is not None:
            self.director.monitor.set_spent(key, frames)

    def clock_shift(self, data):
        """How far a save's marathon and pickup times move to count on the PlayClock.

        A save from before they moved timed them on the collection's own frames, which it kept as
        ``elapsed`` and a reload rewound. Each wait keeps what it had left. A newer save needs no move.
        """
        if 'elapsed' not in data:
            return 0
        return self.director.progress.now(data['elapsed']) - data['elapsed']

    def load(self, data):
        self.pin = None
        self.paused = data.get('paused')
        self.paused_weighed = None
        self.next_marathon = data.get('next_marathon', 0)
        self.marathon_records = data.get('marathon_records', {})
        self.activity_events = data.get('activity_events', [])
        self.deferred_catches = data.get('deferred_catches', {})
        for key in self.state_dict():
            if key in data and key not in ('director', 'remaining'):
                setattr(self,key,data[key])
        self.next_marathon += self.clock_shift(data)
        # A reload keeps the frames each project spent, so the save's budget and idle count are taken
        # only when the director had no tables yet. Older saves kept the retry times beside it.
        fresh = self.director.load(data.get('director', {}), data.get('elapsed', 0), data.get('attempts'))
        if fresh and 'idle_frames' in data and 'progress' not in data.get('director', {}):
            self.idle_frames = data['idle_frames']
        if 'remaining' in data and (fresh or not (self.project and budgeted(self.project))):
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

    def abandon(self, reason, stand_down=True, failure=None):
        """Leave the running project. ``stand_down`` False leaves it free to start again at once, for a
        project a manager set aside rather than one that failed. ``failure`` is the kind of failure
        (planning/decide.py) its stand-down records."""
        if not self.project:
            return False
        project = self.project
        self.end_pin(self.project_key, failure)
        self.record_quality_search()
        self.finish_marathon(False)
        label = project_label(project)
        progressed = bool(project.get('gains', {}).get('experience', 0) or project.get('gains', {}).get('catches', 0))
        if stand_down:
            self.director.finish(project, self.clock, False, reason, progressed, failure=failure)
        self.history = (self.history + [f'Changed plan: {label}. {reason}'])[-6:]
        self.project = None
        self.remaining = 0
        self.idle_token = None
        self.idle_frames = 0
        self.project_maps = []
        self.project_flags = []
        self.progress_token = None
        return True

    def pause(self):
        """Set the running project aside for a pin. Its idle count and any budget it spends on the
        monitor stay there under its own keys, so it resumes with the frames it had left."""
        project = self.project
        self.paused = {'project': project, 'remaining': self._remaining,
                       'project_maps': self.project_maps, 'project_flags': self.project_flags}
        self.paused_weighed = self.weighed
        self.history = (self.history + [f'Set aside: {project_label(project)}. A manager set the next activity'])[-6:]
        self.project = None
        self.remaining = 0
        self.idle_token = None
        self.project_maps = []
        self.project_flags = []
        self.progress_token = None
        self.weighed = None

    def resume(self):
        """Give back the project a pin set aside, with what it had done."""
        paused, self.paused = self.paused, None
        self.project = paused['project']
        if not budgeted(self.project):
            self.remaining = paused['remaining']
        self.project_maps = list(paused['project_maps'])
        self.project_flags = list(paused['project_flags'])
        self.progress_token = None
        self.idle_token = None
        self.weighed, self.paused_weighed = self.paused_weighed, None
        self.history = (self.history + [f'Resumed: {project_label(self.project)}'])[-6:]

    def finish_marathon(self, finished):
        project = self.project
        if not project or project['method'] != 'marathon':
            return
        self.activity_events.append(marathon.finish(self.marathon_records, project, finished))
        self.next_marathon = self.clock + marathon.INTERVAL
        self.marathon_previous = None

    def take_activity_events(self):
        """Journal entries as events, and queued progress rows as they are, for the emulator to write."""
        from ..events import Event
        events = [row if 'progress' in row else Event(**row) for row in self.activity_events]
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
        self.completed_champion |= champion(s)
        for chosen, flag in ((106, 'EVENT_GOT_HITMONLEE'), (107, 'EVENT_GOT_HITMONCHAN')):
            if event_set(s.event_flags, flag):
                self.dojo_choice = chosen
        self.director.forget_expired(self.clock)
        idle = CONTINUE
        if self.project and (not suspended or self.project.rules.own_clock):
            project = self.project
            rules = project.rules
            trainee = None
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
                    self.activity_events.append(marathon.start_event())
                self.activity_events += progress_events.checkpoints(before, project['checkpoint'], self.project_key)
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
                         or rules.battle_progress(project) and self.was_in_battle and not s.in_battle)
                self.director.monitor.start(self.project_key, budget=IDLE_BUDGET)
                idle = self.director.monitor.observe(self.project_key, 0 if s.in_battle or suspended else spent,
                                                     (ProgressEvent('project'),) if moved else ())
                if s.map not in self.project_maps:
                    self.project_maps.append(s.map)
                self.progress_token = token
                self.was_in_battle = bool(s.in_battle)
            finished = rules.finished(kinds.View(self, s, trainee, marathon_finished), project)
            if isinstance(finished, Abandon):
                self.abandon(finished.reason)
                return
            if training_reason and not s.in_battle and not finished:
                self.abandon(training_reason)
                return
            if budgeted(project):
                self.spend_budget(project, s, spent, new_flags)
            if finished or (self.remaining <= 0 and (project['method'] != 'train' or not s.in_battle)):
                # A project done or out of budget starts its next turn with the whole budget.
                self.director.monitor.set_spent(budget_key(project), 0)
                self.record_quality_search()
                self.finish_marathon(bool(finished))
                if finished and project.get('repeat'):
                    self.last_repeat[str(project.get('species'))] = self.clock
                self.history = (self.history + [f'{"Completed" if finished else "Will revisit"}: {rules.label(project)}'])[-6:]
                progressed = bool(project.get('gains', {}).get('experience', 0) or project.get('gains', {}).get('catches', 0))
                self.director.finish(project, self.clock, bool(finished),
                                     'Target reached' if finished else 'Expedition time budget reached', progressed)
                self.end_pin(self.project_key)
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
        return (self.clock >= self.next_marathon and s.saffron_open and nav.can_cut
                and sum(self.director.completed.values()) >= 4)

    def plan_token(self, s):
        """What the plan reads that can turn up a new project: the Pokédex, the bag, the boxes, the
        party, the event flags, the map, the projects still standing down, the marathon's turn, the
        purse and the other adventures' requests."""
        from .ledger import funds_short
        stood = self.director.monitor.stood_down()
        return (s.owned, s.items, s.stored_pokemon, tuple((p.species, p.level) for p in s.party), s.event_flags,
                s.map, frozenset(key for key in stood if self.director.waiting(key, self.clock)),
                self.clock >= self.next_marathon, funds_short(s), tuple(sorted(self.demand().items())))

    def choose(self, s, nav, rng, main):
        """The collection's goal against ``main``, starting a new project at once."""
        picked = self.pick(s, nav, rng, main)
        if picked is None:
            return None
        goal, _, start = picked
        if start is not None:
            start()
        return goal

    def candidate(self):
        """The arbiter candidate of the project under way, as the pick weighed it, or None."""
        key = (self.project or {}).get('key')
        if key is None or self.weighed is None:
            return None
        started, inner, built = self.weighed
        return inner if started == key else built.get(key)

    def pick(self, s, nav, rng, main):
        """The collection's pick against ``main``, the goal it is handed, as ``(goal, inner, start)``, or
        None.

        A new project is weighed here but not started: ``inner`` is its arbiter candidate, and ``start``
        writes the project and what it reads, which the overworld decision runs only when the step ends
        with the project's goal running (decide pipeline rule A). The abandon before the Champion, the idle
        plan, the offers draw and the pin's check are observations, so they are written here. A pin the
        draw left out waits with why, and is checked again at the next draw. A
        project under way and the passage out of Victory Road have nothing to start. A new project with
        no first goal starts at once, so it ends on the next check as before.
        """
        if s.map in LEAGUE or not s.party or not s.owned or not event_set(s.event_flags,'EVENT_GOT_POKEDEX') or main.key.startswith(('heal','party_','teach_','restock')):
            return None
        if not self.completed_champion:
            # The story comes first until the Champion is beaten. Seed 37 after Brock spent 244 of 300
            # game minutes training partners toward evolutions and 16 more hunting grass beside Mt. Moon,
            # and never reached Misty. Catches and training the story needs come from story_goal: an HM
            # partner through teaching_goal and gym or League preparation through boss_training. Wild
            # battles on the way still catch missing species.
            self.abandon('The story comes before side projects until the Champion is beaten')
            return None
        if self.project is None and self.paused is not None and self.pin is None:
            # The pin's run ended, or the pin was cancelled or dropped, so the project it set aside
            # comes back. This observes the pin, as its drop below does.
            self.resume()
        if self.project:
            goal = self.goal(s)
            return None if goal is None else (goal, None, None)
        token = self.plan_token(s)
        if token == self.idle_token:
            return None
        skipped = None if self.pin is None else {}
        offered = self.offers(s, nav, rng, skipped)
        if isinstance(offered, Goal):
            return offered, None, None
        options, projects, travel, _ = offered
        pinned = None
        if self.pin is not None:
            # The pin is checked at each draw. One the draw ranks runs, one it left out waits with why,
            # and one it no longer knows cannot run now.
            if any(option.key == self.pin.key for option in options):
                pinned, self.pin.parked = self.pin.key, None
            elif self.pin.key in skipped:
                self.pin.parked = skipped[self.pin.key][1]
            else:
                self.activity_events.append(pin.gave_up(self.drop_pin(), pin.UNAVAILABLE))
            if pinned is None and self.paused is not None:
                self.resume()
                goal = self.goal(s)
                return None if goal is None else (goal, None, None)
        if pinned is None:
            project = self.director.select(options, projects)
        else:
            project = self.director.select(options, projects, pinned=pinned)
        if project is None:
            # Nothing to do until the game changes, so the plan is not drawn again until then.
            self.idle_token = token
            return None
        # The offers draw builds a new dict for each project, so these fields are written on it only.
        # A catch is progress that gives the budget back, so a hunt's budget covers its first catch.
        project['expected_frames'] = ((travel.get(project['key']) or 0) * FRAMES_PER_TILE
                                      + kind_frames({**project, 'catch_goal': 1}, self.wild))
        appearances = (self.league_rotation(s, project, self.league_appearances)
                       if project['method'] == 'rematch' else None)
        project['initial_owned'] = list(s.owned)
        goal = self.goal(s, project, appearances)
        inner = arbiter.choose(options, pinned=pinned)
        start = partial(self._start, s, nav, project, appearances,
                        (project['key'], inner, {c.key: c for c in options}))
        if goal is None:
            # The goal is read again after the start, as a prize the purse cannot pay for ends its budget.
            start()
            goal = self.goal(s)
            return None if goal is None else (goal, None, None)
        return goal, inner, start

    def _start(self, s, nav, project, appearances, weighed):
        """Start ``project``, the pick's new project, with the League ``appearances`` it counted."""
        self.project = GoalRun.start(project, kinds.rules(project['method']))
        if appearances is not None:
            self.league_appearances = appearances
        if self.pin and project['key'] == self.pin.key:
            self.pin.started = True
        if project['method'] == 'marathon':
            self.next_marathon = self.clock + marathon.INTERVAL
            self.marathon_previous = None
        if project.get('dv_hunt'):
            self.last_hunt[str(project['species'])] = self.clock
        self.idle_frames = 0
        self.project_maps = [s.map]
        self.project_flags = list(s.event_flags)
        self.progress_token = None
        # Any other project's budget lives on the monitor and keeps what it spent before.
        if self.project.rules.own_clock:
            self.remaining = self.project.rules.clock
        nav.path.clear()
        self.weighed = weighed

    def offers(self, s, nav, rng, skipped=None):
        """The projects the plan can start now, as the arbiter's options, the projects by key, the travel
        to each and a label for each. A Goal instead when the plan must first reopen Victory Road.

        ``skipped``, a dict, gets each project the draw leaves out for now, by key, as ``(project, Failure,
        Candidate or None)``. The candidate is there when the draw priced the project before it left it
        out. The goal catalogue passes one and a decision passes none. A source the game will not offer
        again, or one the dojo choice closed, is left out of it too.
        """
        from ..trade.preferences import identity
        bag = dict(s.items)
        held = [(p.species,p.level,None) for p in s.party] + [(sid,level,box) for box,sid,level,nick in s.stored_pokemon]
        candidates = []
        travel = {}
        labels = {}
        def skip(project, failure):
            if skipped is not None:
                skipped.setdefault(kinds.rules(project['method']).key(project), (project, failure, None))
        def add(project):
            key = kinds.rules(project['method']).key(project)
            if self.director.waiting(key, self.clock):
                skip(project, decide.FAILURES.get(self.director.monitor.failure(key, self.clock), decide.STOOD_DOWN))
                return
            goal = self.goal(s, project)
            if not goal or not goal.targets:
                skip(project, NO_STEP)
                return
            distance = distance_to(goal.targets)
            if distance is None:
                skip(project, decide.NO_ROUTE)
                return
            if project['method'] == 'train':
                work_distance = distance_to(training_targets(self.version, project['initial_level']))
                if work_distance is None:
                    skip(project, decide.NO_ROUTE)
                    return
                preparation = distance + 80 if project.get('box') is not None else 0
                project['travel_distance'] = work_distance + preparation
            travel[key] = project.get('travel_distance', distance)
            labels[key] = goal.title
            candidates.append({**project,'key':key})
        sources = self.sources()
        held_individuals = [asdict(mon) for mon in s.party] + s.storage_entries()
        # A quality hunt is valued by the species' best copy as the PC rates it (investment.rarity).
        best_tails = {}
        for mon in held_individuals:
            tail = rarity(mon)
            if tail is not None:
                best_tails[mon['species']] = min(best_tails.get(mon['species'], 100), tail * 100)
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
            # only the few species reachable from the League side of Victory Road. The policy plans
            # the pushes inside, including the one out of the east corridor, so the goal is the exit.
            return Goal('collect_passage', 'Return to Kanto for more hunting grounds',
                        'Open the Victory Road passage before selecting another expedition',
                        ((MAPS['ROUTE_23'], 8, 138),))
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
                selected_dojo = getattr(self, 'returned_events', {}).get('dojo', {}).get('dex', self.dojo_choice)
                if mode == 'gift' and dex(sid) in (106, 107) and dex(sid) != selected_dojo:
                    continue
                found = feasible(source_requires(source, dex(sid) in s.owned), world, books, key='collection')
                if not found:
                    skip(dict(source, species=sid), needs(found))
                    continue
                offered = self.trade_candidate(s, source) if mode == 'trade' else None
                if mode == 'trade' and offered is None:
                    skip(dict(source, species=sid), NO_PARTNER)
                    continue
                if mode == 'grass' and source.get('level',100) > max(p.level for p in s.party)+3:
                    skip(dict(source, species=sid), TOO_STRONG)
                    continue
                if mode in ('grass', 'surf', 'fish') and self.deferred(s, sid):
                    skip(dict(source, species=sid), DEFERRED)
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
                    if project['dv_hunt'] and self.quality_searches.get(str(sid), 0) >= SEARCH_BUDGET:
                        # A species gets SEARCH_BUDGET searches for a better copy in all, wherever it is
                        # found, as in Gen II (gen2/postgame.py). Each place keeps its own budget and
                        # stand-down, so without this a hunt whose hooked copies never beat the held ones
                        # moved from one Safari Zone area to the next with no catch, and Blue stopped
                        # making progress.
                        skip(project, SEARCHED)
                        continue
                if offered is not None:
                    project.update(parent=source['give'], box=offered.get('box'),
                                   give_key=identity(offered))
                if legendary_project(project):
                    project['legendary'] = True
                    if dex(sid) in getattr(self, 'returned_legendaries', ()):
                        project.update(legendary_return=True, repeat=True, initial_count=held_count(s, sid), catch_goal=1,
                                       needed_capture=dex(sid) not in s.owned)
                goal = kinds.rules(project['method']).target(kinds.View(self, s), project)
                if not goal or not goal.targets:
                    skip(project, NO_STEP)
                    continue
                if distance_to(goal.targets) is None:
                    skip(project, decide.NO_ROUTE)
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
        priced = [candidate(project, travel.get(project['key']), best_tails, short, s.owned, self.wild,
                            champion=self.completed_champion)
                  for project in candidates]
        options = party_first(priced, projects)
        if skipped is not None:
            kept = {option.key for option in options}
            for option in priced:
                if option.key not in kept:
                    skipped.setdefault(option.key, (projects[option.key], TRAINS_FIRST, option))
        return options, projects, travel, labels

    def closed(self, s):
        """Why a manager cannot pick a collection goal now, or None when they can."""
        if not self.completed_champion:
            return 'The story comes first until the Champion is beaten'
        if s.map in LEAGUE or not s.party or not s.owned or not event_set(s.event_flags, 'EVENT_GOT_POKEDEX'):
            return 'Not available now'
        return None

    def _drawn(self, s, nav, rng, skipped=None):
        """The offers draw on a copy of ``rng``, so reading it never changes what the run does."""
        copy = random.Random()
        copy.setstate(rng.getstate())
        return self.offers(s, nav, copy, skipped)

    def _named(self, s, nav, rng):
        """The collection goals a manager can name, best first, or why there are none.

        Each goal is ``(key, project, rules, failure, option, group, title)``. The goals the draw ranks
        come first in rank order with ``failure`` None. The goals it left out follow, each with why, and
        with the candidate that priced it or None. ``group`` and ``title`` are the goal's picker_group.
        Reading it draws on a copy of ``rng`` and writes no state.
        """
        reason = self.closed(s)
        if reason:
            return reason
        skipped = {}
        offered = self._drawn(s, nav, rng, skipped)
        if isinstance(offered, Goal):
            return offered.reason
        options, projects, _, labels = offered
        listed = [(projects[option.key], None, option) for option in arbiter.rank(options)]
        listed += [entry for key, entry in skipped.items() if key not in projects or entry[2] is not None]
        named = []
        for project, failure, option in listed:
            rules = kinds.rules(project['method'])
            key = option.key if option else rules.key(project)
            group, title = picker_group(project, labels.get(key) or rules.label(project), s.owned)
            named.append((key, project, rules, failure, option, group, title))
        return named

    def catalogue(self, s, nav, rng):
        """The collection goals for the goal catalogue (planning/catalogue.py), best first, and why there
        are none.

        The goals the draw ranks come first in rank order, with the cost and worth their candidates
        priced. The goals it left out follow, each with why. Reading it draws on a copy of ``rng`` and
        writes no state.
        """
        named = self._named(s, nav, rng)
        if isinstance(named, str):
            return [], named
        # A species found in several places is one row for each, so a shared title names its place.
        shared = Counter(row[-1] for row in named)
        rows = []
        for key, project, rules, failure, option, _, title in named:
            if shared[title] > 1 and project.get('map') is not None:
                title = f'{title}, {place(project["map"])}'
            if option is None:
                rows.append(catalogue.goal(key, project['method'], rules.values(project), title, failure=failure))
            else:
                rows.append(catalogue.goal(key, project['method'], rules.values(project), title, option.tier, failure,
                                           option.expected_frames, option.value))
        return rows, (None if rows else 'Nothing to do until the game changes')

    def goal_list(self, s, nav, rng, query=None, limit=pin.LIMIT):
        """The goals a manager can set as the next activity, best first, then the goals that wait, and why
        the list is empty.

        Each goal is one group of projects (picker_group) under its best project's key, so a species is
        listed once for all the places it is found. ``query`` and ``limit`` are as in pin.grouped. The plan
        is drawn on a copy of ``rng``, so listing the goals never changes what the run does.
        """
        named = self._named(s, nav, rng)
        if isinstance(named, str):
            return [], named
        rows = [(key, group, title, option.tier if option else None, failure)
                for key, _, _, failure, option, group, title in named]
        goals = pin.grouped(rows, query, limit)
        if goals:
            return goals, None
        if query and rows:
            return [], 'No goal matches that name'
        return [], 'Nothing to do until the game changes'

    def set_pin(self, s, nav, rng, key):
        """Set ``key``, a catalogue goal's key, as the next activity. A goal that cannot run now waits with
        why in ``Pin.parked``. A ValueError says why ``key`` cannot be set."""
        named = self._named(s, nav, rng)
        if isinstance(named, str):
            raise ValueError(named)
        match = next((row for row in named if row[0] == key), None)
        if match is None:
            raise ValueError(pin.CHOOSE)
        failure, title = match[3], match[-1]
        if failure is None:
            if self.project and self.project_key != key:
                # The pin runs next and the project resumes after it. One project waits at a time, so a
                # second pin set during the first one's run ends that run instead.
                if self.paused is None:
                    self.pause()
                else:
                    self.abandon('A manager set the next activity', stand_down=False)
            if self.paused is not None and self.paused['project'].get('key') == key:
                # The manager pinned the project set aside, so it comes back with what it had done.
                self.resume()
        self.pin = pin.Pin(key, title, started=failure is None and self.project_key == key, parked=failure)
        self.idle_token = None
        return self.pin

    def pinned(self, inner=None):
        """Whether the collection offers the pinned goal: ``inner``, the candidate of a new project, or
        else the project under way. A pin that waits is not offered."""
        if self.pin is None or self.pin.parked is not None:
            return False
        return (inner.key if inner is not None else self.project_key) == self.pin.key

    def clear_pin(self):
        self.pin = None

    def drop_pin(self):
        """Drop the pin. Returns the label dropped, or None with no pin."""
        if self.pin is None:
            return None
        label, self.pin = self.pin.label, None
        return label

    def end_pin(self, key, failure=None):
        """The pinned project ended, done or not, so the pin has had its one run. A run that ended on the
        kind of ``failure`` is journaled with it."""
        if self.pin is not None and self.pin.started and self.pin.key == key:
            if failure is not None:
                self.activity_events.append(pin.gave_up(self.pin.label, decide.FAILURES.get(failure, failure)))
            self.pin = None

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
        self.league_appearances = self.league_rotation(s, self.project, self.league_appearances)

    def league_rotation(self, s, project, appearances):
        """The League appearance counts of the held Pokémon, carried over from ``appearances``. The reserve
        the rematch ``project`` brings out is written on the project."""
        from ..trade.preferences import identity
        held = [asdict(mon) for mon in s.party] + s.storage_entries()
        keys = {identity(mon) for mon in held} - {None}
        counts = {}
        for key, count in appearances.items():
            if key not in keys:
                # A count saved before trade keys named the evolution family follows its Pokémon
                # when exactly one held Pokémon has that trainer and those stats.
                matches = [held_key for held_key in keys if same(held_key, key)]
                key = matches[0] if len(matches) == 1 else None
            if key:
                counts[key] = max(count, counts.get(key, 0))
        for mon in s.party:
            key = identity(asdict(mon))
            if key:
                counts.setdefault(key, 1)
        if not storage_exchange_possible(s):
            return counts
        reserve = league_rotation.select_reserve(s, self.trade_preferences(), counts)
        if reserve:
            project.update(parent=reserve['species'], trainee_key=identity(reserve),
                           trainee_nick=reserve['nick'], family=[reserve['species']],
                           scoped_partner=True, box=reserve['box'], league_rotation=True)
        return counts

    def league_rotation_goal(self, s, project, appearances=None):
        """The goal that brings the rematch ``project``'s reserve out, or None. ``appearances`` is the count
        it adds to, the collection's own unless given."""
        from ..trade.preferences import identity
        if appearances is None:
            appearances = self.league_appearances
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
                    appearances[key] = appearances.get(key, 0) + 1
            return None
        if (not storage_exchange_possible(s) or len(s.party) >= 6
                and league_rotation.deposit_target(s, self.trade_preferences(), appearances) is None):
            project['rotation_ready'] = True
            return None
        project['box'] = partner['box']
        return Goal('party_league', 'Rotate the League team',
                    'Bring ' + (partner.get('nick') or name(partner['species'])) + ' out for the next rematch',
                    CENTERS, 'up', True)

    def goal(self, s, project=None, appearances=None):
        """The goal of ``project``, the one under way unless given. ``appearances`` is the League count a
        rematch adds to, the collection's own unless given. Each kind's rules give it (policies/kinds.py)."""
        p = self.project if project is None else project
        if not p:
            return None
        return kinds.rules(p['method']).step(kinds.View(self, s, appearances=appearances), p)
