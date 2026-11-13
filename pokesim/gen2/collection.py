"""Persistent postgame expeditions using version and time specific encounters."""
from collections import Counter
from dataclasses import replace
from functools import partial

from ..planning import values
from ..planning import arbiter, decide, pin, throws
from ..planning.arbiter import Candidate, Tier
from ..planning.cost import FRAMES_PER_BATTLE, FRAMES_PER_TILE
from ..planning.ledger import FIELD_MOVES
from ..planning.stance import HUNT
from .menus import ChangeBox, FieldMove, Storage, Teach, Use
from .navigation import DIRS
from pokecore.gen2.ram import Memory
from ..planning.monitor import STOOD_DOWN
from .standdown import (DECISION_FRAMES, exhausted, forget, hold_key, hunt_key, rung_key, search_expected, spend,
                        stand_down, standing_down, train_key)
from .standdown import monitor as standdown_monitor
from . import kinds

# Why a catch goal waits when the battle would keep its last balls (planning/throws.py).
NO_SPARE_BALL = decide.Failure(decide.NEEDS, 'needs ' + throws.spare_words(2))


def matching_time(value, current):
    return value in {'any', 'rare trees'} or current in value.split('/')


def clock_wait(policy, snapshot, mem, current_time):
    """What wanted work waits for on the cartridge clock, as in "Lapras waits for Friday", or None.

    The clock follows game time, so a weekday or time of day that is not here yet comes as fast as the
    run plays: one in-game day is about 5.2 million frames, 24 hours at 1x and well under an hour at Max.
    """
    from .contest import waiting_for_day
    wait = waiting_for_day(policy, snapshot, mem)
    if wait:
        return wait
    if wanted(policy, snapshot, LAPRAS) and mem.byte('wCurDay') % 7 != FRIDAY:
        return 'Lapras waits for Friday'
    later = {}
    for row in policy.data.encounters:
        if wanted(policy, snapshot, row['species']) and not matching_time(row['time'], current_time):
            later.setdefault(row['time'], set()).add(row['species'])
    if later:
        time = min(later, key=lambda name: (-len(later[name]), name))
        names = sorted(policy.data.species[species]['name'] for species in later[time])
        who = names[0] + (f' and {len(names) - 1} more' if len(names) > 1 else '')
        return f'{who} {"wait" if len(names) > 1 else "waits"} for {time.replace("/", " or ")}'
    return None


# Frames a clock wait is expected to last: half an in-game day, about 2.6 million frames.
CLOCK_FRAMES = 2600000


def waiting(policy, snapshot, mem, current_time):
    """The clock wait as the arbiter's passive candidate, or None when nothing waits on the clock.

    A wait accrues on any walk, so the arbiter never picks it and it holds nothing back. It is worth the
    catch it ends in. With every box full and nothing to release that catch has nowhere to go, so the
    wait is worth nothing then and is not named.
    """
    wait = clock_wait(policy, snapshot, mem, current_time)
    if not wait:
        return None
    from .ledger import catch_room
    value = values.NEW_ENTRY if catch_room(policy, snapshot, 'clock_wait') else 0.0
    return Candidate('clock_wait', Tier.PROGRESS, value, CLOCK_FRAMES, passive=True, goal=wait)


def named_wait(policy, snapshot, mem, current_time):
    """The clock wait worth naming in a label, or None."""
    candidate = waiting(policy, snapshot, mem, current_time)
    return candidate.goal if candidate is not None and candidate.value > 0 else None


def waiting_label(policy, snapshot, mem, current_time):
    """Say what the idle walk does and what it waits for."""
    doing = 'Walk the eggs to hatching' if any(mon.egg for mon in snapshot.party) else 'Walk the grass'
    wait = named_wait(policy, snapshot, mem, current_time)
    if wait:
        return f'{doing} while {wait}'
    return f'{doing} until a trade or a return brings new collection work'


def while_waiting(policy, snapshot, mem, goal, Goal):
    """Name the clock wait in the label of the work that runs while it accrues, such as breeding,
    hatching and training. The wait itself is passive and never changes which goal runs."""
    if goal is None or mem is None or not hasattr(mem, 'byte'):
        return goal
    current_time = ('morning', 'day', 'night')[min(2, mem.byte('wTimeOfDay'))]
    wait = named_wait(policy, snapshot, mem, current_time)
    if not wait:
        return goal
    return Goal(goal.key, f'{goal.label} while {wait}', goal.map_name, goal.x, goal.y, goal.face)


def tree_score(x, y, trainer_id):
    # Facing tile coordinates include the four tile map border in cartridge RAM.
    x, y = x + 4, y + 4
    return ((x * y + x + y) // 5 - trainer_id) % 10


def encounter_points(policy, snapshot, mid, method, *, rare=False):
    data = policy.data
    entry = data.maps[mid]
    grid = policy.nav.collision(snapshot, policy.memory) if mid == snapshot.map else policy.nav.regions.live.get(mid, entry['collision'])
    width, height = entry['width'], entry['height']
    points = []
    warps = {(warp['x'], warp['y']) for warp in entry['warps']}
    rocks = {(obj['x'], obj['y']) for index, obj in enumerate(entry['objects'], 1)
             if obj['sprite'] == 'SPRITE_ROCK' and index not in policy.nav.regions.cleared_rocks.get(mid, set())}
    trainer = Memory(policy.memory, data).word('wPlayerID') if method == 'headbutt' else 0
    for y in range(height):
        for x in range(width):
            tile = grid[y * width + x]
            if (x, y) in warps:
                continue
            if method in {'grass', 'surf'}:
                good = tile in (0x10, 0x14, 0x18, 0x1C) if method == 'grass' else tile in (0x21, 0x29)
                # The cartridge treats every floor tile of a cave or dungeon as an encounter tile.
                good |= method == 'grass' and entry['environment'] in {'CAVE', 'DUNGEON'} and tile == 0
                if good:
                    points.append((x, y, None))
            elif method.endswith('rod') and policy.nav.passable(tile):
                for face, (dx, dy) in DIRS.items():
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height and grid[ny * width + nx] in (0x21, 0x29):
                        points.append((x, y, face))
            elif method in {'headbutt', 'rock smash'} and policy.nav.passable(tile):
                for face, (dx, dy) in DIRS.items():
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    if method == 'rock smash':
                        good = (nx, ny) in rocks
                    else:
                        good = grid[ny * width + nx] in (0x15, 0x1D) and (tree_score(nx, ny, trainer) == 0) == rare
                    if good:
                        points.append((x, y, face))
    return points


UNOWN = 201
# Letters each solved Ruins of Alph puzzle unlocks, in wUnlockedUnowns bit order (pret data/wild/unlocked_unowns.asm).
UNOWN_SETS = (range(1, 12), range(12, 19), range(19, 24), range(24, 27))
LAPRAS, FRIDAY = 131, 5


def unown_letter(dvs):
    """Letter number, 1 for A to 26 for Z, from the two DV bytes (pret GetUnownLetter)."""
    first, second = dvs[0], dvs[1]
    value = ((first & 0x60) << 1) | ((first & 0x06) << 3) | ((second & 0x60) >> 3) | ((second & 0x06) >> 1)
    return value // 10 + 1


def unown_missing(policy, snapshot):
    """Unown letters the solved puzzles let appear but the Unown Pokédex still lacks."""
    if getattr(policy, 'memory', None) is None or 'wUnownDex' not in policy.data.symbols:
        return set()
    mem = Memory(policy.memory, policy.data)
    unlocked = mem.byte('wUnlockedUnowns')
    letters = {letter for bit, group in enumerate(UNOWN_SETS) if unlocked >> bit & 1 for letter in group}
    return letters - set(mem.read('wUnownDex', 26))


_HELD = [None, (), Counter()]


def held_counts(snapshot):
    """Copies of each species in the party and every box, eggs aside.

    Planning asks for every encounter row on each step, so the count is made once per snapshot.
    """
    objects, sizes = (snapshot, snapshot.party, snapshot.stored), (len(snapshot.party), len(snapshot.stored))
    if _HELD[0] is None or any(old is not new for old, new in zip(_HELD[0], objects)) or _HELD[1] != sizes:
        _HELD[:] = [objects, sizes, Counter(mon.species for mon in snapshot.party + snapshot.stored if not mon.egg)]
    return _HELD[2]


# Wild partners whose rare held item (the second item in the ROM's base data, 2% of encounters)
# is the one that evolves them over the cable. A cartridge has a single fixed King's Rock and
# Dragon Scale, so once those are spent a wild carrier is the only way left to Politoed,
# Slowking or Kingdra. Magnemite's Metal Coat is left out: it would have to move to Onix or Scyther.
ITEM_CARRIERS = {61: ('KINGS_ROCK', 186), 79: ('KINGS_ROCK', 199), 117: ('DRAGON_SCALE', 230)}
_ITEM_HUNTS = [None, None]
# A carrier hunt is expected to meet 1 / (chance * CARRIER_ITEM_ODDS) wild battles before one holds the
# item, so its search budget comes from that. Silver spent about a third of its frames on carrier hunts.
CARRIER_ITEM_ODDS = 0.02


def item_hunts(policy, snapshot):
    """Carrier species to catch for their held trade item, as {species: item}.

    A carrier is wanted while its evolution is missing here, or a peer asks for it and no copy
    is here to send, and neither the bag nor a stored partner already holds the item.
    """
    demand = getattr(policy, 'demand', None) or {}
    party, stored = tuple(getattr(snapshot, 'party', ())), tuple(getattr(snapshot, 'stored', ()))
    items, owned = tuple(getattr(snapshot, 'items', ())), frozenset(getattr(snapshot, 'owned', ()))
    key = (party, stored, items, owned, tuple(sorted(demand.items())))
    if _ITEM_HUNTS[0] == key:
        return _ITEM_HUNTS[1]
    data, bag = getattr(policy, 'data', None), dict(items)
    held = Counter(mon.species for mon in party + stored if not mon.egg)
    carried = {(mon.species, getattr(mon, 'held_item', 0)) for mon in party + stored if not mon.egg}
    result = {}
    for species, (name, target) in ITEM_CARRIERS.items():
        item = getattr(data, 'items', {}).get(name)
        if item is None or bag.get(item) or (species, item) in carried:
            continue
        if target not in owned or demand.get(target) and not held[target]:
            result[species] = item
    _ITEM_HUNTS[:] = [key, result]
    return result


HUNT_GOALS = {'collection_hunt', 'collection_fish', 'collection_field'}


def target_expected(policy, snapshot, target, maps=0):
    """Decisions a hunt target is expected to take, from its encounter rate and the maps on the way.
    A carrier is searched for its held item, so only one battle in fifty with it counts."""
    odds = CARRIER_ITEM_ODDS if target['species'] in item_hunts(policy, snapshot) else 1.0
    return search_expected(target['chance'], maps, odds)


def catching(snapshot, species):
    """Whether a wild battle with ``species`` is on."""
    return getattr(snapshot, 'in_battle', 0) == 1 and getattr(snapshot, 'enemy_species', None) == species


def travelling(snapshot, row):
    """Whether a wild battle is on away from the map a hunt searches."""
    here = getattr(snapshot, 'map', None)
    return getattr(snapshot, 'in_battle', 0) == 1 and here is not None and here != row.get('map', here)


def observe_search(policy, snapshot):
    """Count each decision a hunt spends searching against its species, across target restarts.

    A target kept while training, storage or another errand runs first costs nothing. A better-DV hunt
    makes progress with each new copy it catches. The species stands down once its budget runs out.
    The battle with the species itself is the catch, not the search, so it costs nothing either: a
    strong Pokémon at full health can take a dozen balls, more than the whole search was expected to
    take. A carrier's battles are still counted, since most of them hold no item and are the search.
    A wild battle on the way to the hunt's map costs nothing too. A Gold hunt fishing for Goldeen in
    Silver Cave Room 2 went back through Room 1 after each trip to the PC, and its cave battles there
    spent the whole budget, so the hunt stood down with its species biting at 70%.
    """
    goal = getattr(policy, 'goal', None)
    if goal is None or goal.key not in HUNT_GOALS:
        return
    target = policy.collection.get('target')
    if target:
        if 'expected' not in target:
            target['expected'] = target_expected(policy, snapshot, target)
        if travelling(snapshot, target) or (catching(snapshot, target['species'])
                                            and target['species'] not in item_hunts(policy, snapshot)):
            return
        spend(policy, hunt_key(target['species']), target['expected'])
        return
    activity = (policy.collection.get('postgame') or {}).get('activity')
    if (activity and activity['kind'] == 'quality' and not activity.get('suspended')
            and not catching(snapshot, activity['species']) and not travelling(snapshot, activity['row'])):
        caught = activity.get('caught', 0)
        events = ('catch',) if caught > activity.get('counted', 0) else ()
        activity['counted'] = caught
        expected = activity.get('expected') or search_expected(activity['row'].get('chance', 10))
        spend(policy, hunt_key(activity['species']), expected, events, progressed=caught > 0)
    elif (activity and activity['kind'] == 'shiny' and not activity.get('suspended')
          and not travelling(snapshot, activity['row'])):
        # A shiny search is for any wild battle on its map, so each one met is its progress. It stands
        # down only when its map stops giving battles, as when its grass cannot be reached.
        from ..planning.progress import encounters
        met = activity.get('encounters', 0)
        events = encounters(activity.get('counted', 0), met)
        activity['counted'] = met
        spend(policy, f'shiny:{activity["row"]["map"]}', search_expected(100, activity.get('maps', 0)), events,
              progressed=met > 0)


PEER_STORE = 'peer_store'
# PC visits a peer-store trip may take before it stands down.
PEER_STORE_OPS = 8


def peer_store_slots(policy, snapshot, *, trainee=True):
    """Party slots holding a Pokémon to box so a peer can be offered it, best choice first.

    Gen II offers only boxed Pokémon, so a stone evolution made for a peer, or a trade-evolved or
    peer-requested arrival, can sit in the party for good and never reach the peer. The lead, the
    trainee, the Exp. Share holder, plan partners and the only holder of a field move stay (see
    hatch_spares). A trained, shiny or perfect partner stays too, since it would not be offered.
    With ``trainee`` False the trainee counts as it would once a hunt is picked over its training.
    """
    from ..milestones import is_perfect
    from ..shiny import is_shiny
    from .breeding import hatch_spares
    demand = getattr(policy, 'demand', None) or {}
    if not demand and not any(not mon.egg and mon.species in trade_targets(policy.data) for mon in snapshot.party[1:]):
        return []
    result = []
    for slot in hatch_spares(policy, snapshot, trainee=trainee):
        mon = snapshot.party[slot]
        record = {'dvs': list(mon.dvs)}
        if ((demand.get(mon.species) or mon.species in trade_targets(policy.data))
                and sum(mon.stat_exp) < 20000 and not is_shiny(record) and not is_perfect(record)):
            result.append(slot)
    return result


_TRADE_TARGETS = {}


def trade_targets(data):
    """Species that only evolve over the cable. The cache keys on the data itself, not its game name,
    so a second load of the same game reads its own species. The entry holds the data, so its id is not
    reused while cached."""
    key = id(data)
    if key not in _TRADE_TARGETS:
        _TRADE_TARGETS[key] = (data, frozenset(int(evo['species']) for row in data.species.values()
                                               for evo in row.get('evolutions', ()) if evo['method'] == 'trade'))
    return _TRADE_TARGETS[key][1]


def peer_store(policy, snapshot, Goal):
    if (standing_down(policy, PEER_STORE) or not any(count < 20 for count in snapshot.box_counts)
            or len(snapshot.party) < 2 or not peer_store_slots(policy, snapshot)):
        policy.collection.pop('peer_store_ops', None)
        return None
    mon = snapshot.party[peer_store_slots(policy, snapshot)[0]]
    goal = policy.storage_goal(snapshot)
    return Goal('collection_peer_store', f'Store {mon.name} where a peer trade can reach it',
                goal.map_name, goal.x, goal.y, goal.face)


def peer_store_arrive(policy, snapshot):
    state = policy.collection
    state['peer_store_ops'] = state.get('peer_store_ops', 0) + 1
    slots = peer_store_slots(policy, snapshot)
    if not slots or len(snapshot.party) < 2 or state['peer_store_ops'] > PEER_STORE_OPS:
        if slots:
            stand_down(policy, PEER_STORE)
        state.pop('peer_store_ops', None)
        return 'b'
    if snapshot.box_counts[snapshot.active_box] >= 20:
        box = next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
        if box is None:
            stand_down(policy, PEER_STORE)
            return 'b'
        policy.menu = ChangeBox(box)
        return 'a'
    policy.menu = Storage('DEPOSIT', slots[0], len(snapshot.party))
    return 'a'


def wanted(policy, snapshot, species):
    return own_wanted(policy, snapshot, species) or peer_wanted(policy, snapshot, species)


def own_wanted(policy, snapshot, species):
    """Whether this adventure wants a copy of ``species`` for itself: a missing entry, a plan's
    missing prerequisite, a missing Unown letter or a carrier of a trade item."""
    return (species not in snapshot.owned
            or species in policy.collection.get('prerequisites', ()) and not held_counts(snapshot)[species]
            or species == UNOWN and bool(unown_missing(policy, snapshot))
            or species in item_hunts(policy, snapshot))


def peer_wanted(policy, snapshot, species):
    """Whether the PC holds fewer copies of ``species`` than its own one and one more for each linked
    adventure that misses it."""
    demand = policy.demand.get(species, 0)
    return bool(demand) and held_counts(snapshot)[species] < demand + 1


def hunt_wanted(policy, snapshot):
    """``wanted`` for the Pokédex hunt, as a function of the species. A copy only linked adventures ask
    for is hunted while one more fits without a kept copy going for it (release.supply_room). Once
    copies kept for trade filled the boxes, each such catch released another kept copy, and that
    copy's own hunt opened next. A Crystal run caught and released Slowpoke, Weedle and Goldeen twice
    each that way in under an hour. The PC is rated once, and only when such a copy comes up."""
    from .release import supply_room
    room = []

    def hunted(species):
        if own_wanted(policy, snapshot, species):
            return True
        if not peer_wanted(policy, snapshot, species):
            return False
        if not room:
            room.append(supply_room(policy, snapshot))
        return room[0]
    return hunted


def throw_signature(snapshot):
    """What can change a throw's odds: the party's species and moves and the kinds of ball held."""
    party = sorted((mon.species, tuple(sorted(move for move in mon.moves if move))) for mon in snapshot.party if not mon.egg)
    return repr((party, sorted(item for item, count in snapshot.pockets['balls'] if count)))


def defer(policy, snapshot, species):
    """Leave ``species`` uncaught until the party or the ball pocket changes (planning.throws)."""
    policy.collection.setdefault('deferred', {})[str(species)] = throw_signature(snapshot)


def deferred(policy, snapshot, species):
    """Whether a catch of ``species`` waits for a new move, member or ball, so no hunt goes for it."""
    return policy.collection.get('deferred', {}).get(str(species)) == throw_signature(snapshot)


def lapras(policy, snapshot, mem, Goal):
    """Meet the Union Cave Lapras, which surfaces on Fridays until the day's battle sets its flag."""
    if (not wanted(policy, snapshot, LAPRAS) or mem.byte('wCurDay') % 7 != FRIDAY
            or mem.byte('wDailyFlags2') & 2 or not snapshot.badges & 8
            or not snapshot.event('EVENT_GOT_HM03_SURF') or not snapshot.can_catch):
        policy.collection.pop('lapras', None)
        return None
    # Give up for the day if the meeting never happens, so other Friday work still gets done.
    started = policy.collection.setdefault('lapras', policy.decisions)
    if policy.decisions - started > 3000:
        return None
    if not any(57 in mon.moves or 57 in policy.data.species[mon.species]['machines']
               for mon in snapshot.party if not mon.egg):
        return None
    data = policy.data
    mid = data.map_ids['UNION_CAVE_B2F']
    entry = data.maps[mid]
    index, obj = next((i, obj) for i, obj in enumerate(entry['objects'], 1) if obj['script'] == 'UnionCaveLapras')
    # Objects are briefly missing right after a warp, so fall back to the spawn point.
    x, y = next(((x, y) for i, x, y in snapshot.objects if i == index), (obj['x'], obj['y'])) \
        if snapshot.map == mid else (obj['x'], obj['y'])
    grid = policy.nav.collision(snapshot, policy.memory) if snapshot.map == mid else entry['collision']
    choices = []
    for face, (dx, dy) in DIRS.items():
        px, py = x - dx, y - dy
        if not (0 <= px < entry['width'] and 0 <= py < entry['height']):
            continue
        if not policy.nav.passable(grid[py * entry['width'] + px], surf=True):
            continue
        if snapshot.map == mid:
            # Lapras swims around, so only a water tile reachable right now beside it will do.
            path = policy.nav.local(snapshot, [(px, py)], policy.memory, surf=True)
            if path is None:
                continue
            choices.append((len(path), px, py, face))
        else:
            # From afar, head for the side facing the western shore the player surfs out from.
            choices.append((px, px, py, face))
    if not choices:
        return Goal('collection_lapras', 'Find the Friday Lapras in Union Cave', 'UNION_CAVE_B2F', 4, 31)
    _, px, py, face = min(choices)
    return Goal('collection_lapras', 'Catch the Friday Lapras in Union Cave', 'UNION_CAVE_B2F', px, py, face)


_PREREQUISITES = [None, None]


def prerequisites(data, snapshot):
    """Find breeding and evolution partners that were collected but later traded away.

    Called several times per step, so the answer is kept until the species table, the dex or a
    held copy changes. Snapshot regions are reused while their bytes match, so the key compares
    by identity in the common case.
    """
    key = (data.species, snapshot.owned, snapshot.party, snapshot.stored, getattr(snapshot, 'daycare', ()))
    cached = _PREREQUISITES[0]
    if cached is not None and cached[0] is key[0] and cached[1:] == key[1:]:
        return set(_PREREQUISITES[1])
    needed = _prerequisites(data, snapshot)
    _PREREQUISITES[:] = [key, frozenset(needed)]
    return needed


def _prerequisites(data, snapshot):
    mons = snapshot.party + snapshot.stored + tuple(mon for mon in getattr(snapshot, 'daycare', ()) if mon)
    held = {mon.species for mon in mons}
    needed = set()
    for source, row in data.species.items():
        for evolution in row['evolutions']:
            if (evolution['species'] not in snapshot.owned
                    and not any(mon.species == source and (evolution['method'] in {'item', 'trade'} or mon.level < 100)
                                for mon in mons)):
                needed.add(source)
    babies = {172: {25, 26}, 173: {35, 36}, 174: {39, 40}, 236: {106, 107, 237},
              238: {124}, 239: {125}, 240: {126}}
    for baby, parents in babies.items():
        if baby not in snapshot.owned and not parents & held:
            needed.update(parents)
    if 132 not in held:
        # Ditto stays even after the Pokédex is full. It is the Day Care partner for every gift and
        # static that has no wild source, and for genderless families like Magnemite and Staryu.
        needed.add(132)
    return needed


def league_run(policy, snapshot):
    """A postgame League run and the team that would take it, as the oracle reads them (planning/league.run)."""
    from ..planning import league
    from ..planning.readiness import Boss
    from .readiness import BOSS_TABLE, league_lineup
    moves = policy.data.moves
    boss = policy.league_boss(snapshot) if hasattr(policy, 'league_boss') else Boss('league', league=True)
    power = lambda move: moves.get(move, {}).get('power')
    attack_pp = lambda move: moves.get(move, {}).get('pp', 0) if power(move) else 0
    return league.run(BOSS_TABLE, boss, snapshot.party, getattr(policy, 'move_power', power), attack_pp,
                      league_lineup(policy.data), getattr(policy, 'collection', {}).get('league_lost'))


def league_verdict(policy, snapshot):
    """None when the team may choose a postgame League run, or the oracle's Train verdict."""
    from ..planning.readiness import judge
    boss, fighters = league_run(policy, snapshot)
    return judge(boss, fighters, getattr(policy, 'losses', None))


def league_key(identity):
    """The stand-down that keeps a trainee out of League runs after a run it was in failed.

    The monitor keeps it, so the reload to the League entry save, which rewinds the run's own records
    and the loss it noted, leaves it in place.
    """
    return 'league:' + train_key(identity)


def league_trainees(policy, snapshot):
    """The training project's trainee, in the party or a box, below the lowest level the League's lineup
    fields (planning/league.run), with its identity. A list of at most one.

    A boxed trainee counts too. A Gold run left its level 25 Poliwhirl in a box and took a level 100
    Typhlosion with weak partners to the Elite Four for prize money, where the Typhlosion ran out of
    attacks. A trainee at the lineup's lowest level joins the team and adds the depth the oracle asks
    for after a loss.
    """
    from .training import identity
    want = (getattr(policy, 'collection', {}).get('training') or {}).get('identity')
    if want is None:
        return []
    low = league_run(policy, snapshot)[0].low or 0
    mon = next((mon for mon in snapshot.party + snapshot.stored if identity(mon) == want), None)
    return [(mon, want)] if mon is not None and mon.level < low else []


def trainee_out(policy, snapshot):
    """Whether a trainee a failed League run took in still stands down from League runs."""
    return any(standing_down(policy, league_key(want)) for _, want in league_trainees(policy, snapshot))


def league_closed(policy, snapshot):
    """Whether a postgame League run may not start, or go on from outside the League: the oracle's Train
    verdict (league_verdict), or a trainee a failed run took in that is still below the lineup's lowest level."""
    return league_verdict(policy, snapshot) is not None or trainee_out(policy, snapshot)


def funding_closed(policy, snapshot):
    """Whether a League run for prize money may not start, or go on from outside the League.

    A funding run is for money the work needs, not for a ready team, so the oracle stops one only after
    a run lost (``league_lost``). A Gold run took a level 100 Typhlosion and a level 22 trainee to the
    Elite Four for prize money, lost, and restarted from the entry save again and again. The trainee
    such a run took in stays out until it reaches the lineup's lowest level.
    """
    if policy.collection.get('league_lost') is not None and league_closed(policy, snapshot):
        return True
    return trainee_out(policy, snapshot)


def league_restarted(policy, snapshot):
    """Stand down from League runs the trainee the run under way took in, after a reload restarted
    the run from its entry save. ``snapshot`` is the game before the reload. True when one stood down."""
    trainees = league_trainees(policy, snapshot)
    for _, want in trainees:
        stand_down(policy, league_key(want))
    return bool(trainees)


def lose_league(policy, snapshot):
    """End the League run under way as lost: the oracle counts the loss (``league_lost``), and the
    trainee the run took in stands down from League runs."""
    state = policy.collection
    for key in ('league_loop', 'funding', 'league_entered'):
        state.pop(key, None)
    state['league_lost'] = league_run(policy, snapshot)[1].depth
    league_restarted(policy, snapshot)


def league_funding(policy, snapshot, Goal, *, again=False):
    """Run the Elite Four again for prize money, ending with a Hall of Fame entry.

    ``again`` is the postgame loop of a run with nothing else left, which challenges the League for
    its own sake rather than for money.
    """
    if not policy.in_league(snapshot):
        if snapshot.event('EVENT_WILLS_ROOM_ENTRANCE_CLOSED'):
            return Goal('funds_arrive', 'Return to the League reception', 'INDIGO_PLATEAU_POKECENTER_1F', 17, 10)
        label = ('Challenge the Elite Four again for another Hall of Fame entry' if again
                 else 'Challenge the League to fund the next expedition')
        return policy.person(snapshot, 'funds_will', label, 'WILLS_ROOM', 'WillScript_Battle')
    for trainer, room in [('WILL', 'WILLS'), ('KOGA', 'KOGAS'), ('BRUNO', 'BRUNOS'), ('KAREN', 'KARENS')]:
        if not snapshot.event(f'EVENT_BEAT_ELITE_4_{trainer}'):
            return policy.person(snapshot, 'funds_' + trainer.lower(), 'Continue the League expedition',
                                 room + '_ROOM', trainer.title() + 'Script_Battle')
    if not snapshot.event('EVENT_BEAT_CHAMPION_LANCE'):
        return policy.person(snapshot, 'funds_lance', 'Challenge Champion Lance again', 'LANCES_ROOM', 'LancesRoomLanceScript')
    return Goal('funds_champion', 'Record another League victory', 'HALL_OF_FAME', 4, 7)


def call_off_league(policy):
    """Treat the postgame League run under way as lost, so the team prepares before the next.

    The guards call this after restarting the same attempt from the entry save again and again. The
    entry save was taken before the run went in, so this marks it entered and the League loop then
    sees a team outside the League without its Hall of Fame entry, as after a black out. A run for
    prize money (``funding``) is called off the same way.
    """
    state = policy.collection
    if state.get('league_loop') is None and state.get('funding') is None:
        return False
    state['league_entered'] = True
    return True


def league_loop(policy, snapshot, Goal):
    """The next step of a postgame League run under way, or None once it is over or called off."""
    state = policy.collection
    loop = state.get('league_loop')
    if loop is not None and snapshot.hall_of_fame_count >= loop:
        state.pop('league_loop', None)
        state.pop('league_entered', None)
        state.pop('league_lost', None)
    elif loop is not None and not policy.in_league(snapshot) and state.get('league_entered'):
        # Leaving the League without its Hall of Fame entry means the team blacked out. A live Crystal
        # run took one level 71 Poliwhirl and its trainees back to Lance every twenty minutes and lost
        # each time, so the next run waits for the team to grow.
        lose_league(policy, snapshot)
    elif loop is not None and not policy.in_league(snapshot) and league_closed(policy, snapshot):
        # A postgame run is optional, so a team too weak to finish it trains instead of trying.
        state.pop('league_loop', None)
    elif loop is not None:
        # A postgame League run, once started, finishes with its Hall of Fame entry before new work.
        if policy.in_league(snapshot):
            state['league_entered'] = True
        state['phase'] = 'league'
        return league_funding(policy, snapshot, Goal, again=True)
    return None


def choice_key(row):
    return f"{row['species']}:{row['map']}:{row['method']}"


def hunt_candidates(choices):
    """The arbiter's candidates for the hunt pick, for shadow mode only.

    A species the Pokédex lacks, or one a request, prerequisite or carried item asks for, is worth a
    new entry. Any other is a repeat. Frames are the walk there and the wild battles the encounter
    chance says it takes, at the shared estimates in planning/cost.py.
    """
    candidates = []
    for elsewhere, owned, route, species, mid, method, row in choices:
        walk = route - 50 / max(1, row['chance'])
        kind = 'hunt new entry' if not owned else 'hunt repeat' if elsewhere else 'hunt request'
        frames = walk * FRAMES_PER_TILE + search_expected(row['chance'], per_battle=FRAMES_PER_BATTLE + 10 * FRAMES_PER_TILE)
        candidates.append(Candidate(choice_key(row), Tier.PROGRESS, values.SMALL if kind == 'hunt repeat' else values.NEW_ENTRY,
                                    frames, goal=kind))
    return candidates


# Frames of one map crossed on the way to a rung's goal, about thirty steps.
MAP_FRAMES = 30 * FRAMES_PER_TILE
# Frames a rung's work takes once its walk is over. A short errand is a talk, a gift, a pickup or a
# purchase, as Gen I prices it (policies/strategic.py).
ERRAND_FRAMES = 3000
# A static or returned legend's battle and catch.
LEGEND_FRAMES = 6000
# A Ruins of Alph puzzle, a Celebi shrine visit, a Day Care pairing or a Game Corner prize.
ACTIVITY_FRAMES = 12000
# A Bug-Catching Contest, twenty minutes of the park.
CONTEST_FRAMES = 30000
# A wait by the phone for a stone trainer's call, at 3600 frames a game minute. A call comes about
# every 25 game minutes, after the 20 minute timer and its retries, and it rings on any walk with
# service too.
PHONE_WAIT_FRAMES = 25 * 3600
# Training toward an evolution, as Gen I prices it (policies/collection.py EXPECTED_FRAMES).
EVOLVE_FRAMES = 60000
# A League run of five rooms, about thirty battles.
LEAGUE_FRAMES = 30 * FRAMES_PER_BATTLE
# A Battle Tower challenge with its preparation: seven battles, the trip to Olivine and the team swap.
TOWER_FRAMES = 60000
# Frames lost by leaving the rung under way for another: the walk back to it and the steps it took.
INTERRUPT_FRAMES = 2 * ERRAND_FRAMES
# A map the route search cannot reach counts as this many maps away.
FAR_MAPS = 50
# Goals that accrue on any walk, which the arbiter never picks. The Day Care counts the steps of any
# walk, so pacing Goldenrod for its egg runs only when no other rung has work.
PASSIVE = frozenset(('collection_hatch',))
_MISSING = object()


def _slots(policy):
    """The state a rung's build may write: the collection's fields, the stand-downs and spent budgets, the
    menu task and the milestones."""
    slots = {('collection', key): value for key, value in policy.collection.items()}
    slots.update({('monitor', key): value for key, value in policy.monitor_tables.items()})
    slots['menu'] = getattr(policy, 'menu', None)
    slots['completed'] = getattr(policy, 'completed', None)
    return slots


def _save(policy):
    from copy import deepcopy
    slots = _slots(policy)
    # A menu task can hold the emulator, so it is kept by reference. A rung replaces it, never edits it.
    menu = slots.pop('menu')
    return {**deepcopy(slots), 'menu': menu}


def _differs(slot, now, before):
    if slot == 'menu':
        return now is not before
    return now != before


def _set(policy, slot, value):
    """Set ``slot`` to ``value``, the object itself, or remove it for _MISSING."""
    if slot == 'menu':
        policy.menu = None if value is _MISSING else value
    elif isinstance(slot, tuple):
        table = policy.collection if slot[0] == 'collection' else policy.monitor_tables
        if value is _MISSING:
            table.pop(slot[1], None)
        else:
            table[slot[1]] = value
    elif slot == 'completed' and isinstance(policy.completed, dict) and isinstance(value, dict):
        # The milestones dict is shared with the emulator, so it keeps its identity.
        policy.completed.clear()
        policy.completed.update(value)
    elif hasattr(policy, slot):
        setattr(policy, slot, value)


def _restore(policy, saved):
    """Put back every slot ``_save`` took."""
    now = _slots(policy)
    for slot in set(now) | set(saved):
        value = saved.get(slot, _MISSING)
        if _differs(slot, now.get(slot, _MISSING), value):
            _set(policy, slot, value)


def draft(policy, build):
    """Run ``build`` and take its writes back. Returns what ``build`` gave and its writes, each slot's new
    value or _MISSING for a slot it removed, which ``write`` lands.

    A build hands the objects it wrote over to its writes and the policy gets copies of the old ones, so a
    menu task or goal that holds an object the build wrote still holds the one ``write`` lands.
    """
    from copy import deepcopy
    before = _save(policy)
    result = build()
    now = _slots(policy)
    writes = {}
    for slot in set(now) | set(before):
        value = now.get(slot, _MISSING)
        if _differs(slot, value, before.get(slot, _MISSING)):
            # The milestones dict is cleared in place when it is put back, so its writes are a copy.
            writes[slot] = deepcopy(value) if slot == 'completed' else value
    for slot in writes:
        _set(policy, slot, before.get(slot, _MISSING))
    return result, writes


def write(policy, writes):
    """Land the writes a ``draft`` took."""
    for slot, value in writes.items():
        _set(policy, slot, value)


class Rungs:
    """The rungs of one collection decision, each offered to the decide pipeline as its own source.

    Each rung's build runs in a draft, so it writes nothing, and offers its goal with its tier, worth and
    frames and a commit that lands its writes only when it is picked. A rung that offers nothing, as when
    it stands down, lands its writes at once, since they record what it saw. So does a passive goal, such
    as the Day Care walk, which runs on any walk and only when no rung has active work. A rung whose best
    tier cannot beat the best offer so far is not asked.
    """

    def __init__(self, policy, snapshot):
        self.policy, self.snapshot = policy, snapshot
        self.offers = []
        # Every rung's candidate, the passive and the colliding ones too, for the survey and the catalogue.
        self.candidates, self.passive = [], []
        self.stopped = False
        # The rung the last decision picked, which any other rung pays INTERRUPT_FRAMES to cut into.
        self.running = getattr(policy, 'ladder_rung', None)
        # The next activity a manager set (planning/pin.py). Its rung is asked even below the best tier so
        # far, since the pinned lane ranks it first, and passes the same checks as any other rung.
        self.pin = getattr(policy, 'pin', None)
        self.pin_rung = self.pin.key.split(':', 1)[0] if self.pin else None
        # The key of the offer that is the pinned goal, which the decision ranks in the pinned lane.
        self.pinned_key = None
        # Why the pinned goal cannot run in this decision, a Failure from planning/decide.py.
        self.pin_parked = None
        # A survey asks every rung, for the goal list a manager picks from, and changes nothing.
        self.survey = getattr(policy, 'ladder_survey', False)
        self.asked, self.labels = set(), {}
        # In a survey, the goals a rung left out for now, each (key, title, Failure), for the catalogue.
        self.skipped = []

    def pinned(self, key):
        """Whether the candidate ``key`` is the pinned goal. A pin on a rung that stood down names the
        rung alone, so any goal that rung offers is the pinned one."""
        if self.pin is None:
            return False
        return key == self.pin.key or ':' not in self.pin.key and key.split(':', 1)[0] == self.pin_rung

    def best(self):
        """The best offer's candidate so far, or None."""
        ranked = arbiter.rank([offered.candidate for offered in self.offers], self.pinned_key)
        return ranked[0] if ranked else None

    def decision(self):
        return decide.decide(self.offers, self.pinned_key)

    def travel(self, goal):
        """Frames of the walk to ``goal``'s map, by the maps on the way."""
        policy, snapshot = self.policy, self.snapshot
        mid = policy.data.map_ids.get(goal.map_name)
        walk = getattr(getattr(policy, 'nav', None), 'walk', None)
        if mid is None or walk is None or mid == snapshot.map:
            return 0
        path = walk(snapshot, mid)
        return MAP_FRAMES * (len(path) if path is not None else FAR_MAPS)

    def offer(self, name, tier, value, work, build, price=None, blocked=None):
        """Ask rung ``name``, whose best tier is ``tier``. ``build`` gives its goal or None. ``price``,
        given the goal, gives its tier, value and frames of work if they differ from ``tier``, ``value``
        and ``work``. ``blocked``, given the goal,
        gives the Failure that keeps it from starting, or None. A blocked goal is not offered, its build
        writes nothing, and a pin on it waits with the reason."""
        if self.stopped:
            return
        best = self.best()
        if best is not None and arbiter.ahead(best, tier) and not self.survey and name != self.pin_rung:
            return
        if self.policy.monitor_tables.get(STOOD_DOWN) and standing_down(self.policy, rung_key(name)):
            # The watchdog gave up on this rung after its reloads did not help (emulator.py). A pin on it
            # waits, and says why.
            if name == self.pin_rung:
                self.pin_parked = decide.STOOD_DOWN
            if self.survey:
                kind = standdown_monitor(self.policy).failure(rung_key(name), self.policy.clock)
                self.skipped.append((name, RUNGS.get(name, name).capitalize(), decide.FAILURES.get(kind, decide.STOOD_DOWN)))
            return
        self.asked.add(name)

        def built():
            # A price and a block read what the build wrote, such as the hunt's new target, so they run in
            # the draft.
            goal = build()
            if goal is None:
                return None, None, None
            return goal, None if price is None else price(goal), None if blocked is None else blocked(goal)
        (goal, priced, failure), writes = draft(self.policy, built)
        waiting = getattr(self.policy, 'no_route_waiting', None)
        if goal is not None and failure is None and waiting is not None and waiting(goal):
            # The walk to this goal found no route lately (policy.no_route), so another rung runs first.
            failure = decide.NO_ROUTE
        if failure is not None:
            if self.pinned(f'{name}:{goal.key}'):
                self.pin_parked = failure
            if self.survey:
                self.skipped.append((f'{name}:{goal.key}', goal.label, failure))
            return
        if goal is None:
            # A rung that offers nothing but asks for League prize money, as the Game Corner prize
            # partner does, ends the rungs: the League run starts in this decision.
            funding = self.policy.collection.get('funding')
            write(self.policy, writes)
            self.stopped = funding is None and self.policy.collection.get('funding') is not None
            return
        if priced is not None:
            tier, value, work = priced
        interrupt = INTERRUPT_FRAMES if self.running is not None and name != self.running else 0.0
        candidate = Candidate(f'{name}:{goal.key}', tier, value, work + self.travel(goal),
                              passive=goal.key in PASSIVE, interrupt_frames=interrupt, goal=name)
        self.candidates.append(candidate)
        self.labels[candidate.key] = goal.label
        if candidate.passive:
            write(self.policy, writes)
            self.passive.append((name, goal))
            return
        if self.pinned(candidate.key):
            self.pinned_key = candidate.key
        from .pipeline import offer
        offered = offer('rung', goal, candidate, source=name, commit=partial(write, self.policy, writes))
        # Two rungs that offer one goal are one offer, the better of the two.
        earlier = next((other for other in self.offers if other.key == offered.key), None)
        if earlier is not None:
            if arbiter.rank([earlier.candidate, candidate], self.pinned_key)[0] is earlier.candidate:
                return
            self.offers.remove(earlier)
        self.offers.append(offered)

    def settle(self, pick):
        """Start, end or drop the manager's pin once the decision has weighed the rungs.

        The pin starts when the decision picks its key and ends, done or not, when a later decision picks
        something else. A run that ends because its goal was parked is journaled with the reason. A pin
        whose goal is parked before it starts, because its rung stood down or its walk found no route
        lately, waits with the reason, which the API state carries. A pin whose rung was asked and offered
        another goal or none cannot run now, so it is dropped with a journal entry. A pin that lost only to
        upkeep waits for the next decision. A pin on a rung that stood down takes the key of the goal that
        rung starts.
        """
        policy, current = self.policy, self.pin
        if current is None or self.survey:
            return
        current.parked = self.pin_parked
        key = None if pick is None else pick.candidate.key
        if key is not None and self.pinned(key):
            current.key, current.started = key, True
        elif current.started:
            policy.pin = None
            if current.parked:
                pin_events(policy).append(pin.gave_up(current.label, current.parked))
        elif current.parked:
            return
        elif self.pin_rung in self.asked and not any(self.pinned(c.key) for c in self.candidates):
            policy.pin = None
            pin_events(policy).append(pin.gave_up(current.label, pin.UNAVAILABLE))


def holds(policy, snapshot, mem, Goal):
    """The goal of an activity under way, or of a failed precondition, which no rung cuts into.

    A started contest, Tower challenge, League funding run or postgame League run finishes first, since
    leaving it loses what it has done. With no ball pocket that can catch, every catch waits for a box.
    """
    state = policy.collection
    from .contest import journey as contest
    if state.get('contest'):
        goal = contest(policy, snapshot, Goal)
        if goal:
            return goal
    from .tower import journey as tower
    if state.get('tower'):
        goal = tower(policy, snapshot, Goal)
        if goal:
            return goal
    if not snapshot.can_catch and not policy.in_league(snapshot):
        if any(count < 20 for count in snapshot.box_counts):
            goal = policy.storage_goal(snapshot)
            return Goal('collection_box', 'Make room for new catches', goal.map_name, goal.x, goal.y, goal.face)
    if state.get('funding') is not None:
        goal = funding_run(policy, snapshot, Goal)
        if state.get('funding') is not None:
            state['phase'] = 'league'
            return goal
    return league_loop(policy, snapshot, Goal)


def funding_run(policy, snapshot, Goal):
    """The next step of the League run for prize money under way, or None once it is over, lost or
    closed (funding_closed). ``funding`` is left set while the run goes on."""
    state = policy.collection
    funding = state.get('funding')
    if funding is None:
        return None
    if snapshot.hall_of_fame_count >= funding:
        state.pop('funding', None)
        state.pop('league_entered', None)
        state.pop('league_lost', None)
    elif not policy.in_league(snapshot) and state.get('league_entered'):
        # Out of the League without its Hall of Fame entry: the team blacked out, or the run was called
        # off after it restarted from the entry save (call_off_league). It is lost, as a League loop's is.
        lose_league(policy, snapshot)
    elif not policy.in_league(snapshot) and funding_closed(policy, snapshot):
        state.pop('funding', None)
    else:
        if policy.in_league(snapshot):
            state['league_entered'] = True
        return league_funding(policy, snapshot, Goal)
    return None


def held(policy, snapshot, mem, Goal):
    """The goal holds() gives, unless a park set it aside after it stalled (emulator._park), so the rungs run
    until its stand-down runs out."""
    goal = holds(policy, snapshot, mem, Goal)
    if goal and policy.monitor_tables.get(STOOD_DOWN) and standing_down(policy, hold_key(goal.key)):
        return None
    return goal


def start_funding(policy, snapshot, Goal):
    """Start a League run for prize money when the purse is short of what wanted work needs, or None."""
    state = policy.collection
    from .breeding import pairings
    from .ledger import BREEDING_FUNDS, funding_short
    from .. import config
    starter_gifts = getattr(config, 'LEAGUE_REWARDS', False) and not {152, 155, 158} <= snapshot.owned
    from .quests import static_wanted, ultra_shortfall
    from .store_stock import shortfall as store_shortfall
    if not (funding_short(policy, snapshot) or starter_gifts
            or snapshot.can_catch and ultra_shortfall(policy, snapshot) and static_wanted(policy, snapshot)
            # A wanted Day Care pair waits for its money to start, and nothing else earns it.
            or snapshot.money < BREEDING_FUNDS and not state.get('breeding')
            and getattr(snapshot, 'daycare', None) is not None and pairings(policy, snapshot)
            or store_shortfall(policy, snapshot)):
        return None
    if funding_closed(policy, snapshot):
        return None
    state['funding'] = snapshot.hall_of_fame_count + 1
    state['phase'] = 'league'
    return league_funding(policy, snapshot, Goal)


def _alone(policy, goal, source, tier, value, frames):
    """Offer ``goal`` as the collection's only goal, from ``source``, and return it."""
    from .pipeline import offer
    policy.collection_offers, policy.collection_pinned, policy.collection_goal = [], None, goal
    if goal is not None:
        candidate = Candidate(f'{source}:{goal.key}', tier, value, frames, goal=source)
        policy.collection_offers = [offer('rung', goal, candidate, source=source)]
    return goal


def journey(policy, snapshot, mem, Goal):
    """The collection's next goal: an activity under way, or else the decide pipeline's pick of the rungs.

    Every rung offers its goal with its tier, its value and the frames of its walk and work, and the
    pipeline picks the most value per frame in the highest tier. Enablers such as the Super Rod, the
    move tutors, a League run for money and pickups that expire are upkeep. New entries and what opens
    them are progress. A repeat Tower challenge is filler and the postgame activities keep their own
    tiers. The clock wait and the Day Care walk accrue on any walk, so they are passive and never hold
    back active work. The rungs' offers go on the step's ballot (policy.journey), and the pick's writes
    land now, since the step reads them next.
    """
    data, state = policy.data, policy.collection
    # The decision that asked the collection, which tells the decide pipeline the story goal is its own.
    policy.collection_decision = getattr(policy, 'decisions', None)
    policy.collection_offers, policy.collection_pinned, policy.collection_goal = [], None, None
    from .npc_trades import requests as trade_requests
    state['prerequisites'] = sorted(prerequisites(data, snapshot) | trade_requests(policy, snapshot, getattr(mem, 'memory', None)))
    goal = held(policy, snapshot, mem, Goal)
    policy.ladder_hold = goal or None
    if goal:
        policy.ladder_rung, policy.ladder_offers, policy.ladder_pick = None, [], None
        return goal
    current_time = ('morning', 'day', 'night')[min(2, mem.byte('wTimeOfDay'))] if hasattr(mem, 'byte') else 'day'
    rungs = Rungs(policy, snapshot)
    new = values.NEW_ENTRY
    offer = rungs.offer
    UPKEEP, PROGRESS = Tier.UPKEEP, Tier.PROGRESS

    def super_rod():
        if snapshot.event('EVENT_GOT_SUPER_ROD'):
            return None
        return policy.person(snapshot, 'super_rod', 'Get the Super Rod for the Pokédex expedition',
                             'ROUTE_12_SUPER_ROD_HOUSE', 'Route12SuperRodHouseFishingGuruScript')

    def tutor(flag, map_name, script, label):
        return lambda: None if snapshot.event(flag) else policy.person(snapshot, flag.lower(), label, map_name, script)

    def returned():
        if not getattr(policy, 'returned', set()) & {243, 244, 245, 249, 250, 251}:
            return None
        from .quests import legends
        return legends(policy, snapshot, Goal)

    from .item_sources import phones, pickups
    from .quests import gifts, legends, stones, trade_items
    from .ruins import journey as ruins
    from .npc_trades import journey as npc_trades
    from .tower import journey as tower
    from .celebi import journey as celebi
    from .contest import journey as contest
    from .breeding import hatching, journey as breed
    from .gamecorner import journey as prizes
    from .store_stock import journey as store
    from .champion_shop import journey as champion_shop
    from .training import journey as training
    from . import postgame
    offer('super_rod', UPKEEP, new, ERRAND_FRAMES, super_rod)
    offer('headbutt_tutor', UPKEEP, new, ERRAND_FRAMES, tutor('EVENT_GOT_TM02_HEADBUTT', 'ILEX_FOREST',
          'IlexForestHeadbuttGuyScript', 'Learn about Headbutt encounters'))
    offer('rock_smash_tutor', UPKEEP, new, ERRAND_FRAMES, tutor('EVENT_GOT_TM08_ROCK_SMASH', 'ROUTE_36',
          'Route36RockSmashGuyScript', 'Learn about Rock Smash encounters'))
    offer('funding', UPKEEP, new, LEAGUE_FRAMES, lambda: start_funding(policy, snapshot, Goal))
    # A returned legendary waits at its original home ahead of routine collection.
    offer('returned', UPKEEP, new, LEGEND_FRAMES, returned)
    # A stone a phone trainer holds today and the Monday night Moon Stone expire, so they are upkeep.
    offer('pickups', UPKEEP, new, ERRAND_FRAMES, lambda: pickups(policy, snapshot, mem, Goal))
    offer('ruins', PROGRESS, new, ACTIVITY_FRAMES, lambda: ruins(policy, snapshot, Goal))
    offer('lapras', PROGRESS, new, LEGEND_FRAMES, lambda: lapras(policy, snapshot, mem, Goal))
    offer('gifts', PROGRESS, new, ERRAND_FRAMES, lambda: gifts(policy, snapshot, Goal))
    offer('trade_items', PROGRESS, new, ERRAND_FRAMES, lambda: trade_items(policy, snapshot, Goal))
    offer('npc_trades', PROGRESS, new, 2 * ERRAND_FRAMES, lambda: npc_trades(policy, snapshot, mem, Goal))
    # The first Tower challenge earns its prize once. It is worth little against a new entry.
    if 'tower' not in policy.completed:
        offer('tower', PROGRESS, values.SMALL, TOWER_FRAMES, lambda: tower(policy, snapshot, Goal))
    offer('celebi', PROGRESS, new, ACTIVITY_FRAMES, lambda: celebi(policy, snapshot, Goal))
    offer('contest', PROGRESS, new, CONTEST_FRAMES, lambda: contest(policy, snapshot, Goal))
    offer('breed', PROGRESS, new, ACTIVITY_FRAMES, lambda: breed(policy, snapshot, Goal))
    offer('prizes', PROGRESS, new, ACTIVITY_FRAMES, lambda: prizes(policy, snapshot, Goal))
    offer('stones', PROGRESS, new, ERRAND_FRAMES, lambda: stones(policy, snapshot, Goal))
    # Registering a number is an errand, but the wait lasts until a call comes. Other open work goes
    # first, since the call rings during it and pickups collects the stone it brings.
    offer('phones', PROGRESS, new, ERRAND_FRAMES, lambda: phones(policy, snapshot, mem, Goal),
          price=lambda goal: (PROGRESS, new, PHONE_WAIT_FRAMES) if goal.key == 'collection_phone_wait' else None)
    offer('store', PROGRESS, new, ERRAND_FRAMES, lambda: store(policy, snapshot, Goal))
    offer('champion_shop', PROGRESS, new, ERRAND_FRAMES, lambda: champion_shop(policy, snapshot, Goal))
    offer('hatching', PROGRESS, new, ERRAND_FRAMES, lambda: hatching(policy, snapshot, Goal))
    offer('peer_store', PROGRESS, new, ERRAND_FRAMES, lambda: peer_store(policy, snapshot, Goal))
    offer('training', PROGRESS, new, EVOLVE_FRAMES, lambda: training(policy, snapshot, mem, Goal))
    offer('legends', PROGRESS, new, LEGEND_FRAMES, lambda: legends(policy, snapshot, Goal))
    offer('hunt', PROGRESS, new, 0, lambda: pokedex_hunt(policy, snapshot, Goal, current_time),
          price=lambda goal: hunt_price(policy, snapshot), blocked=lambda goal: hunt_blocked(policy, snapshot))
    # A finished run keeps playing the way Red, Blue and Yellow do: better-DV hunts, training ten levels
    # at a time, a due marathon, shiny searches and League runs, as the postgame's own arbiter picks them.
    offer('postgame', Tier.RACE, values.SMALL, 0, lambda: postgame.journey(policy, snapshot, mem, Goal, current_time),
          price=lambda goal: postgame_price(policy, snapshot))
    if 'tower' in policy.completed:
        # A repeat challenge earns nothing new, so it is filler.
        offer('tower', Tier.FILLER, values.SMALL, TOWER_FRAMES, lambda: tower(policy, snapshot, Goal))
    wait = waiting(policy, snapshot, mem, current_time) if hasattr(mem, 'byte') else None
    policy.ladder_offers = rungs.candidates + ([wait] if wait is not None else [])
    policy.ladder_decision = getattr(policy, 'decisions', None)
    policy.ladder_labels = rungs.labels
    if rungs.survey:
        policy.ladder_skipped = rungs.skipped
    if state.get('funding') is not None and not policy.in_league(snapshot) and funding_closed(policy, snapshot):
        state.pop('funding', None)
    if state.get('funding') is not None:
        # A rung that offered nothing, such as the Game Corner prize partner, just asked for League prize
        # money. Start that run now, or one decision picks a later goal such as the Tohjo Falls Moon
        # Stone and the next one walks away from it. No rung's goal runs, so none of their writes land.
        policy.ladder_rung, policy.ladder_pick = 'funding', None
        state['phase'] = 'league'
        goal = league_funding(policy, snapshot, Goal)
        frames = LEAGUE_FRAMES + (rungs.travel(goal) if goal is not None else 0)
        return _alone(policy, goal, 'funding', Tier.UPKEEP, new, frames)
    pick = rungs.decision().pick
    rungs.settle(pick)
    if pick is None:
        policy.ladder_rung = policy.ladder_pick = None
        if rungs.passive:
            name, passive = rungs.passive[0]
            goal = while_waiting(policy, snapshot, mem, passive, Goal)
            return _alone(policy, goal, name, Tier.FILLER, 0.0, ERRAND_FRAMES)
        eggs = any(mon.egg for mon in snapshot.party)
        # Carried eggs hatch on this walk, so only a walk without them is idle.
        state['phase'] = 'hatching' if eggs else 'waiting'
        # Nothing else is useful until the cartridge clock opens a window or a trade brings new work.
        # The plan is rebuilt every step, so clock-gated work starts as soon as its window opens.
        goal = patrol(policy, snapshot, Goal, waiting_label(policy, snapshot, mem, current_time))
        return _alone(policy, goal, 'collection', Tier.FILLER, 0.0, ERRAND_FRAMES)
    # The step reads the menu task and the collection the pick wrote right after this, so they land now and
    # the step's ballot carries the offers without their writes.
    pick.commit()
    policy.ladder_rung, policy.ladder_pick = pick.source, pick.candidate.key
    goal = pick.goal
    if pick.source in {'breed', 'hatching', 'training'}:
        goal = while_waiting(policy, snapshot, mem, goal, Goal)
    policy.collection_offers = [replace(offered, goal=goal, commit=None) if offered is pick
                                else replace(offered, commit=None) for offered in rungs.offers]
    policy.collection_pinned, policy.collection_goal = rungs.pinned_key, goal
    return goal


def pin_events(policy):
    """Journal rows about the pin that the emulator has not written yet."""
    if not hasattr(policy, 'pin_events'):
        policy.pin_events = []
    return policy.pin_events


def survey(policy, snapshot, mem, Goal):
    """Every rung's candidate for this moment, best first, with labels, the activity that holds the
    ladder if one does, and the goals the rungs left out for now, each (key, title, Failure). Each rung is
    asked as a decision would ask it and then everything is undone."""
    saved = _save(policy)
    names = ('ladder_rung', 'ladder_offers', 'ladder_pick', 'ladder_decision', 'ladder_labels', 'ladder_hold',
             'ladder_skipped', 'collection_decision', 'collection_offers', 'collection_pinned', 'collection_goal')
    kept = {name: getattr(policy, name, _MISSING) for name in names}
    rng = policy.rng.getstate() if hasattr(policy, 'rng') else None
    events = list(pin_events(policy))
    policy.ladder_survey = True
    policy.ladder_skipped = []
    try:
        journey(policy, snapshot, mem, Goal)
        offers = arbiter.rank(getattr(policy, 'ladder_offers', None) or [])
        labels = dict(getattr(policy, 'ladder_labels', None) or {})
        hold = getattr(policy, 'ladder_hold', None)
        skipped = list(policy.ladder_skipped)
    finally:
        policy.ladder_survey = False
        _restore(policy, saved)
        for name, value in kept.items():
            if value is _MISSING:
                if hasattr(policy, name):
                    delattr(policy, name)
            else:
                setattr(policy, name, value)
        if rng is not None:
            policy.rng.setstate(rng)
        policy.pin_events = events
    return offers, labels, hold, skipped


# Plain words for each collection rung, the kinds of the goal catalogue.
RUNGS = {
    'super_rod': 'get the Super Rod',
    'headbutt_tutor': 'learn about Headbutt encounters',
    'rock_smash_tutor': 'learn about Rock Smash encounters',
    'funding': 'run the League for prize money',
    'returned': 'meet a returned legendary at its home',
    'pickups': 'pick up a stone that is offered only today',
    'ruins': 'solve the Ruins of Alph picture boards',
    'lapras': 'meet the Union Cave Lapras on a Friday',
    'gifts': 'receive a Pokémon someone gives away',
    'trade_items': 'get an item a trade evolution needs',
    'npc_trades': 'trade with a person for their Pokémon',
    'tower': 'take the Battle Tower challenge',
    'celebi': 'meet Celebi at the Ilex Forest shrine',
    'contest': 'earn a Sun Stone in the Bug-Catching Contest',
    'breed': 'breed a missing Pokémon at the Day Care',
    'prizes': 'exchange Game Corner coins for a Pokémon',
    'stones': 'get an evolution stone',
    'phones': 'collect a stone a phone contact holds',
    'store': 'buy extra Goldenrod Dept. Store stock',
    'champion_shop': 'buy limited TMs and Champion supplies',
    'hatching': 'hatch the eggs the party carries',
    'peer_store': 'box a Pokémon a peer adventure can take',
    'training': 'raise a collected partner',
    'legends': 'meet a legendary Pokémon',
    'hunt': 'find a wild Pokémon for the Pokédex',
    'postgame': 'keep playing once the Pokédex work runs out',
}
GOAL_PARAM = ('goal', 'key', 'the goal the rung offers')


def catalogue(policy, snapshot, mem, Goal):
    """The collection goals for the goal catalogue (planning/catalogue.py), best first, and why there
    are none.

    The goals the rungs offer come first in rank order, with the cost and worth their candidates priced.
    The goals they left out follow, each with why. A passive goal such as the clock wait runs on any walk,
    so it is not listed. The survey undoes every write.
    """
    from ..planning import catalogue as listing
    if 'red' not in policy.completed:
        return [], 'Finish the story first'
    offers, labels, hold, skipped = survey(policy, snapshot, mem, Goal)
    rows = []
    for offer in offers:
        if offer.passive:
            continue
        rung, _, goal = offer.key.partition(':')
        rows.append(listing.goal(offer.key, rung, {'goal': goal}, labels.get(offer.key, offer.key), offer.tier,
                                 cost=offer.expected_frames, worth=offer.value))
    listed = {row['key'] for row in rows}
    for key, title, failure in skipped:
        if key not in listed:
            rung, _, goal = key.partition(':')
            rows.append(listing.goal(key, rung, {'goal': goal or None}, title, failure=failure))
            listed.add(key)
    if rows:
        return rows, None
    if hold is not None:
        return [], f'{hold.label} finishes first'
    return [], 'Nothing to do until the game changes'


def goal_list(policy, snapshot, mem, Goal, query=None, limit=pin.LIMIT):
    """The goals a manager can set as the next activity, best first, then the goals that wait, and why
    the list is empty.

    Offers with one label serve one want, so each label is listed once under its best offer's key. A
    passive goal such as the clock wait runs on any walk, so it is not listed. ``query`` and ``limit``
    are as in pin.grouped.
    """
    if 'red' not in policy.completed:
        return [], 'Finish the story first'
    offers, labels, hold, skipped = survey(policy, snapshot, mem, Goal)
    rows = []
    for offer in offers:
        if offer.passive:
            continue
        label = labels.get(offer.key, offer.key)
        rows.append((offer.key, label, label, offer.tier))
    listed = {offer.key for offer in offers}
    for key, title, failure in skipped:
        if key not in listed:
            rows.append((key, title, title, None, failure))
            listed.add(key)
    goals = pin.grouped(rows, query, limit)
    if goals:
        return goals, None
    if query and rows:
        return [], 'No goal matches that name'
    if hold is not None:
        return [], f'{hold.label} finishes first'
    return [], 'Nothing to do until the game changes'


def hunt_price(policy, snapshot):
    """The Pokédex hunt's tier, value and frames: a new entry, or a small gain for a repeat, priced from
    the encounter rate of the target the hunt chose."""
    target = policy.collection.get('target')
    if not target:
        return Tier.PROGRESS, values.SMALL, ERRAND_FRAMES
    species = target['species']
    repeat = (species in snapshot.owned and not policy.demand.get(species)
              and species not in policy.collection.get('prerequisites', ()) and species not in item_hunts(policy, snapshot))
    return (Tier.PROGRESS, values.SMALL if repeat else values.NEW_ENTRY,
            target_expected(policy, snapshot, target) * DECISION_FRAMES)


def hunt_blocked(policy, snapshot):
    """Why the Pokédex hunt cannot start, or None. A hunt whose catch the battle would refuse to throw at,
    by the spare ball rule (planning/throws.py), waits for balls or money, so a run whose last balls are
    kept does other work instead of fleeing every target it finds."""
    from .ledger import spare_throw
    target = policy.collection.get('target')
    if target and not spare_throw(policy.data, snapshot, target['species']):
        return NO_SPARE_BALL
    return None


def postgame_price(policy, snapshot):
    """The postgame activity's own tier, value and frames, or a filler League run's."""
    from . import postgame
    activity = postgame.state(policy).get('activity')
    if not activity:
        return Tier.FILLER, values.SMALL, LEAGUE_FRAMES
    candidate = postgame.candidate(policy, snapshot, activity)
    return candidate.tier, candidate.value, candidate.expected_frames * DECISION_FRAMES


def pokedex_hunt(policy, snapshot, Goal, current_time):
    """Walk the Pokédex hunt target, choosing one first when there is none, or None with nothing to hunt."""
    data, state = policy.data, policy.collection
    target = state.get('target')
    # With every box full and nothing to release, a hunt could never keep a catch.
    room = not policy.no_room(snapshot)
    hunted = hunt_wanted(policy, snapshot)
    leaves = {}

    def hopeless(species, level):
        # A catch the battle would only run from, judged before travelling (planning.throws). A Lv 40
        # Kingler on a super rod took 17 minutes of fishing for one battle that left it at once.
        if level is None:
            return False
        if (species, level) not in leaves:
            leaves[species, level] = policy.leaves_wild(snapshot, species, level)
        return leaves[species, level]

    if (target and (not hunted(target['species']) or not matching_time(target['time'], current_time)
                   or not room or standing_down(policy, hunt_key(target['species']))
                   or deferred(policy, snapshot, target['species']) or hopeless(target['species'], target.get('level')))):
        if not wanted(policy, snapshot, target['species']):
            # Caught, or its item found: the search is done, so its spent decisions go too.
            forget(policy, hunt_key(target['species']))
        state['target'] = target = None
    if target is None:
        groups = {}
        items = dict(snapshot.items)
        for row in data.encounters if room else ():
            if (not hunted(row['species']) or not matching_time(row['time'], current_time)
                    or standing_down(policy, hunt_key(row['species'])) or not usable(policy, snapshot, row, items)
                    or deferred(policy, snapshot, row['species']) or hopeless(row['species'], row.get('level'))):
                continue
            method = row['method']
            key = (row['map'], method, row['species'], row['time'] == 'rare trees')
            groups.setdefault(key, {**row, 'chance': 0})['chance'] += row['chance']
        routes, points = {}, {}
        choices = []
        distances = {}
        for mid, _, _, _ in groups:
            if mid not in distances:
                route = policy.nav.walk(snapshot, mid)
                distances[mid] = len(route) if route is not None else 9999
        carriers = item_hunts(policy, snapshot)
        ranked = sorted(groups.items(), key=lambda pair: (not bool(policy.demand.get(pair[0][2])
                         or pair[0][2] in state['prerequisites'] or pair[0][2] in carriers),
                         distances[pair[0][0]] + 50 / max(1, pair[1]['chance'])))
        for (mid, method, species, rare), row in ranked:
            if choices and len(choices) >= 12:
                break
            key = (mid, method, rare)
            if key not in points:
                points[key] = encounter_points(policy, snapshot, mid, method, rare=rare)
                routes[key] = policy.nav.regions.route(snapshot, mid, [point[:2] for point in points[key]], cut=True, surf=True)
            route = routes[key]
            if route is None or not points[key]:
                continue
            choices.append((not bool(policy.demand.get(species) or species in state['prerequisites']
                                     or species in carriers),
                            species in snapshot.owned,
                            len(route) + 50 / max(1, row['chance']), species, mid, method, row))
        if choices:
            target = dict(min(choices, key=lambda row: row[:-1])[-1], started=policy.decisions)
            target['expected'] = target_expected(policy, snapshot, target, distances.get(target['map'], 0) % 9999)
            state['target'] = target = kinds.target(target)
            shadow = getattr(policy, 'shadow', None)
            if shadow is not None:
                shadow.compare('hunt', lambda: hunt_candidates(choices), choice_key(target))
        else:
            return None
    return hunt(policy, snapshot, Goal)


def postgame_league(policy, snapshot, mem, current_time):
    """Whether a postgame League run may start: the Champion is beaten and the team is ready.

    A clock window opening later does not hold the run back, since the clock wait is passive and
    clock-gated work starts on the first decision after its window opens.
    """
    if 'champion' not in getattr(policy, 'completed', {}) or not snapshot.hall_of_fame_count:
        return False
    return not league_closed(policy, snapshot)


HUNT_METHODS = {'grass', 'surf', 'old rod', 'good rod', 'super rod', 'headbutt', 'rock smash'}


def usable(policy, snapshot, row, items):
    """Whether the party can search an encounter row now: walking, surfing, a rod in the bag, or a
    Headbutt or Rock Smash it knows or can be taught."""
    data, method = policy.data, row['method']
    if method not in HUNT_METHODS:
        return False
    if method in {'headbutt', 'rock smash'}:
        move = 29 if method == 'headbutt' else 249
        machine = data.items['TM_HEADBUTT' if move == 29 else 'TM_ROCK_SMASH']
        return any(move in mon.moves or machine in items and move in data.species[mon.species]['machines']
                   and not all(known in FIELD_MOVES for known in mon.moves)
                   for mon in snapshot.party if not mon.egg)
    return not method.endswith('rod') or data.items[method.upper().replace(' ', '_')] in items


def active_target(policy):
    """The encounter row being searched: a Pokédex hunt, or else a postgame search."""
    from .postgame import searching
    return policy.collection.get('target') or searching(policy)


# Where the run passes time when nothing else is useful, the last resort of the plan.
PATROL_MAP, PATROL_HOME = 'ROUTE_29', (12, 8)


def patrol(policy, snapshot, Goal, label):
    """Walk between the Route 29 grass tiles when nothing else is useful, the last resort of the plan.

    The cartridge clock follows game time, so a wait lasts up to a few million frames. Standing still
    for that long looks like a frozen run and does nothing, while walking the grass keeps the
    screen moving and battles wild Pokémon until the plan finds real work again.
    """
    data = policy.data
    mid = data.map_ids[PATROL_MAP]
    if snapshot.map != mid:
        return Goal('collection_idle', label, PATROL_MAP, *PATROL_HOME)
    here = (snapshot.x, snapshot.y)
    points = sorted((point[:2] for point in encounter_points(policy, snapshot, mid, 'grass') if point[:2] != here),
                    key=lambda point: (abs(point[0] - here[0]) + abs(point[1] - here[1]),
                                       policy.nav.visits.get((mid, *point), 0)))
    candidates = []
    for x, y in points[:24]:
        path = policy.nav.local(snapshot, [(x, y)], policy.memory)
        if path:
            candidates.append((policy.nav.visits.get((mid, x, y), 0), len(path), x, y))
            if len(candidates) >= 4:
                break
    if not candidates:
        return Goal('collection_idle', label, PATROL_MAP, *PATROL_HOME)
    _, _, x, y = min(candidates)
    return Goal('collection_idle', label, PATROL_MAP, x, y)


def hunt(policy, snapshot, Goal, target=None, label=None):
    """Walk an encounter row. ``target`` is a postgame search, which ``label`` names, instead of the
    Pokédex hunt target. A postgame search that cannot go on ends and gives None."""
    data, state = policy.data, policy.collection
    postgame = target is not None
    target = target or state['target']
    state['phase'] = 'hunting'
    mid, method = target['map'], target['method']
    points = encounter_points(policy, snapshot, mid, method, rare=target['time'] == 'rare trees')
    if not points:
        if postgame:
            return unavailable(policy, snapshot, Goal)
        # No tile of its map yields it, so the next pick looks elsewhere until the stand-down ends.
        stand_down(policy, hunt_key(target['species']))
        state['target'] = None
        return Goal('collection_wait', 'Replan the Pokédex expedition', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    if mid == snapshot.map:
        candidates = []
        ordered = sorted(points, key=lambda point: (abs(point[0] - snapshot.x) + abs(point[1] - snapshot.y),
                         policy.nav.visits.get((mid, point[0], point[1]), 0)))
        for x, y, face in ordered:
            if (x, y) == (snapshot.x, snapshot.y) and method in {'grass', 'surf'}:
                continue
            path = policy.nav.local(snapshot, [(x, y)], policy.memory, surf=True)
            if path is not None:
                visits = policy.nav.visits.get((mid, x, y), 0)
                candidates.append((len(path), visits, x, y, face))
                if len(candidates) >= 4:
                    break
        if candidates:
            _, _, x, y, face = min(candidates, key=lambda row: row[:4])
    if mid != snapshot.map or not candidates:
        # Only a tile in a region the route reaches will do. A cave's floor outside its walls counts as an
        # encounter tile too, and aiming there walks nowhere.
        regions = policy.nav.regions
        if regions.between(snapshot, True, True):
            # Nothing can be judged until the player lands, so the walk aims at the first tile for now.
            point = points[0]
        else:
            route = regions.route(snapshot, mid, [point[:2] for point in points], cut=True, surf=True)
            if route:
                wanted = {route[-1][1][1]}
            elif route is None:
                wanted = set()
            else:
                # Already in a region that has the tiles.
                wanted = regions.memberships(snapshot.map, (snapshot.x, snapshot.y), True, True, arrive=True)
            point = next((point for point in points if wanted & regions.memberships(mid, point[:2], True, True)), None)
        if point is None:
            if postgame:
                return unavailable(policy, snapshot, Goal)
            # No reachable tile yields it, so the next pick looks elsewhere until the stand-down ends.
            stand_down(policy, hunt_key(target['species']))
            state['target'] = None
            return Goal('collection_wait', 'Replan the Pokédex expedition', data.maps[mid]['constant'], snapshot.x, snapshot.y)
        x, y, face = point
    if label is None:
        name = data.species[target['species']]['name']
        item = item_hunts(policy, snapshot).get(target['species'])
        if item and target['species'] in snapshot.owned:
            name += ' holding ' + data.item_names.get(item, 'its item')
        label = f'Search for {name}'
    key = 'collection_fish' if method.endswith('rod') else 'collection_field' if method in {'headbutt', 'rock smash'} else 'collection_hunt'
    if postgame:
        forget(policy, LOADING)
    # Every hunt runs from the battles it cannot catch from (planner design S5). This is the one place
    # that sets the hunt scope: Pokédex, carrier, better-copy and shiny searches alike.
    return Goal(key, f'{label} in {data.maps[mid]["name"]}', data.maps[mid]['constant'], x, y, face, kind=HUNT)


# Steps a postgame outing waits for its encounter map to finish loading before it is abandoned.
LOADING, LOADING_STEPS = 'outing:loading', 21


def unavailable(policy, snapshot, Goal):
    """Allow map transitions to finish before abandoning a postgame outing."""
    if exhausted(policy, LOADING, LOADING_STEPS):
        return abandon(policy)
    return Goal('collection_wait', 'Wait for the encounter map to finish loading',
                policy.data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)


def abandon(policy):
    from .postgame import drop
    drop(policy)
    return None


def give_up(policy):
    """Drop the hunt target after the game refused its rod or field move, so the next plan picks another."""
    state = policy.collection
    target = state.get('target')
    if target:
        stand_down(policy, hunt_key(target['species']))
    else:
        from .postgame import drop
        drop(policy)
    state['target'] = None
    return 'wait'


def arrive(policy, snapshot):
    key = policy.goal.key
    from .gamecorner import arrive as prize
    result = prize(policy, snapshot)
    if result is not None:
        return result
    from .teams import arrive as team
    result = team(policy, snapshot)
    if result is not None:
        return result
    from .breeding import arrive as breed
    result = breed(policy, snapshot)
    if result is not None:
        return result
    from .quests import arrive as gift
    result = gift(policy, snapshot)
    if result is not None:
        return result
    from .npc_trades import arrive as npc_trade
    result = npc_trade(policy, snapshot)
    if result is not None:
        return result
    from .item_sources import arrive as item_source
    result = item_source(policy, snapshot)
    if result is not None:
        return result
    from .store_stock import arrive as store
    result = store(policy, snapshot)
    if result is not None:
        return result
    from .champion_shop import arrive as champion_shop
    result = champion_shop(policy, snapshot)
    if result is not None:
        return result
    from .training import arrive as train
    result = train(policy, snapshot)
    if result is not None:
        return result
    if key == 'collection_peer_store':
        return peer_store_arrive(policy, snapshot)
    if key == 'collection_release':
        from .ledger import release_step
        return release_step(policy, snapshot)
    if key == 'collection_box':
        box = next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
        if box is not None:
            policy.menu = ChangeBox(box)
            return 'a'
    if key == 'collection_fish':
        method = active_target(policy)['method']
        rod = Use(policy.data.items[method.upper().replace(' ', '_')])
        if not policy.allowed(rod, snapshot):
            return give_up(policy)
        policy.menu = rod
        return 'wait'
    if key == 'collection_field':
        method = active_target(policy)['method']
        move = 29 if method == 'headbutt' else 249
        slot = next((i for i, mon in enumerate(snapshot.party) if not mon.egg and move in mon.moves), None)
        if slot is None:
            slot = next((i for i, mon in enumerate(snapshot.party) if not mon.egg
                         and move in policy.data.species[mon.species]['machines']
                         and not all(known in FIELD_MOVES for known in mon.moves)), None)
            task = Teach(move, slot) if slot is not None else None
        else:
            task = FieldMove(slot, 'HEADBUTT' if move == 29 else 'ROCK SMASH')
        if task is None or not policy.allowed(task, snapshot):
            return give_up(policy)
        policy.menu = task
        return 'wait'
    if key in {'collection_wait', 'collection_idle', 'collection_hunt', 'collection_roam_hunt', 'collection_roam_lead',
               'collection_static_lead', 'collection_marathon'}:
        return 'wait'
    return None
