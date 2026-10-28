"""Persistent postgame expeditions using version and time specific encounters."""
from collections import Counter

from ..planning.ledger import FIELD_MOVES
from .menus import ChangeBox, FieldMove, Release, Storage, Teach, Use
from .navigation import DIRS
from pokecore.gen2.ram import Memory
from .standdown import (exhausted, forget, hunt_key, search_expected, spend, stand_down, standing_down)


def matching_time(value, current):
    return value in {'any', 'rare trees'} or current in value.split('/')


def clock_wait(policy, snapshot, mem, current_time):
    """What wanted work waits for on the cartridge clock, as in "Lapras waits for Friday", or None.

    The clock follows game time, so a weekday or time of day that is not here yet comes as fast as the
    run plays: one in-game day is about 5.2 million frames, 24 hours at 1x and well under an hour at Max.
    Every other activity goes first, so this only names the wait in the label of the filler work.
    """
    if policy.no_room(snapshot):
        # Each of these waits ends in a catch, and with every box full and nothing to release none can
        # start. Naming one would also hold back the postgame League run that still has work to do.
        return None
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


def waiting_label(policy, snapshot, mem, current_time):
    """Say what the idle walk does and what it waits for."""
    doing = 'Walk the eggs to hatching' if any(mon.egg for mon in snapshot.party) else 'Walk the grass'
    wait = clock_wait(policy, snapshot, mem, current_time)
    if wait:
        return f'{doing} while {wait}'
    return f'{doing} until a trade or a return brings new collection work'


def while_waiting(policy, snapshot, mem, goal, Goal):
    """Name the clock wait in the label of filler work such as breeding, hatching and training."""
    if goal is None or mem is None or not hasattr(mem, 'byte'):
        return goal
    current_time = ('morning', 'day', 'night')[min(2, mem.byte('wTimeOfDay'))]
    wait = clock_wait(policy, snapshot, mem, current_time)
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


def observe_search(policy, snapshot):
    """Count each decision a hunt spends searching against its species, across target restarts.

    A target kept while training, storage or another errand runs first costs nothing. A better-DV hunt
    makes progress with each new copy it catches. The species stands down once its budget runs out.
    """
    goal = getattr(policy, 'goal', None)
    if goal is None or goal.key not in HUNT_GOALS:
        return
    target = policy.collection.get('target')
    if target:
        if 'expected' not in target:
            target['expected'] = target_expected(policy, snapshot, target)
        spend(policy, hunt_key(target['species']), target['expected'])
        return
    activity = (policy.collection.get('postgame') or {}).get('activity')
    if activity and activity['kind'] == 'quality' and not activity.get('suspended'):
        caught = activity.get('caught', 0)
        events = ('catch',) if caught > activity.get('counted', 0) else ()
        activity['counted'] = caught
        expected = activity.get('expected') or search_expected(activity['row'].get('chance', 10))
        spend(policy, hunt_key(activity['species']), expected, events, progressed=caught > 0)


PEER_STORE = 'peer_store'
# PC visits a peer-store trip may take before it stands down.
PEER_STORE_OPS = 8


def peer_store_slots(policy, snapshot):
    """Party slots holding a Pokémon to box so a peer can be offered it, best choice first.

    Gen II offers only boxed Pokémon, so a stone evolution made for a peer, or a trade-evolved or
    peer-requested arrival, can sit in the party for good and never reach the peer. The lead, the
    trainee, the Exp. Share holder, plan partners and the only holder of a field move stay (see
    hatch_spares). A trained, shiny or perfect partner stays too, since it would not be offered.
    """
    from ..milestones import is_perfect
    from ..shiny import is_shiny
    from .breeding import hatch_spares
    demand = getattr(policy, 'demand', None) or {}
    if not demand and not any(not mon.egg and mon.species in trade_targets(policy.data) for mon in snapshot.party[1:]):
        return []
    result = []
    for slot in hatch_spares(policy, snapshot):
        mon = snapshot.party[slot]
        record = {'dvs': list(mon.dvs)}
        if ((demand.get(mon.species) or mon.species in trade_targets(policy.data))
                and sum(mon.stat_exp) < 20000 and not is_shiny(record) and not is_perfect(record)):
            result.append(slot)
    return result


_TRADE_TARGETS = {}


def trade_targets(data):
    """Species that only evolve over the cable."""
    if data.game not in _TRADE_TARGETS:
        _TRADE_TARGETS[data.game] = {int(evo['species']) for row in data.species.values()
                                     for evo in row.get('evolutions', ()) if evo['method'] == 'trade'}
    return _TRADE_TARGETS[data.game]


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
    held = held_counts(snapshot)[species]
    return (species not in snapshot.owned
            or species in policy.collection.get('prerequisites', ()) and not held
            or held < policy.demand.get(species, 0) + 1 and bool(policy.demand.get(species))
            or species == UNOWN and bool(unown_missing(policy, snapshot))
            or species in item_hunts(policy, snapshot))


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


# Every Elite Four and Champion Pokémon is level 40 or higher, and the five battles field 26 of them.
LEAGUE_LEVEL, LEAGUE_OPPONENTS = 40, 26


def league_ready(policy, snapshot):
    """Whether the party is strong enough to choose a League run.

    Nothing restores PP inside the League. A level 100 Vaporeon beside Pokémon too weak to face the
    Elite Four ran out of attacks at Lance and the battle never ended. So the Pokémon at League
    level need at least one attack for each opponent, counted at full PP since the run heals first.
    """
    moves = policy.data.moves
    lost = getattr(policy, 'collection', {}).get('league_lost')
    if lost is not None and league_strength(snapshot) < min(lost + LEAGUE_REGROWTH, league_ceiling(snapshot)):
        return False
    return sum(moves.get(move, {}).get('pp', 0) for mon in snapshot.party
               if not mon.egg and mon.level >= LEAGUE_LEVEL
               for move in mon.moves if moves.get(move, {}).get('power')) >= LEAGUE_OPPONENTS


# A team that lost a postgame League run tries again only after this many more levels at League level.
LEAGUE_REGROWTH = 10


def league_strength(snapshot):
    """The levels the party holds at League level, which grow as training brings it closer to winning."""
    return sum(mon.level for mon in snapshot.party if not mon.egg and mon.level >= LEAGUE_LEVEL)


def league_ceiling(snapshot):
    """The most League strength the party can reach, so a team that lost at level 100 may try again."""
    return 100 * len(snapshot.party)


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
    sees a team outside the League without its Hall of Fame entry, as after a black out.
    """
    state = policy.collection
    if state.get('league_loop') is None:
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
        state.pop('league_loop', None)
        state.pop('league_entered', None)
        state['league_lost'] = league_strength(snapshot)
    elif loop is not None and not policy.in_league(snapshot) and not league_ready(policy, snapshot):
        # A postgame run is optional, so a team too weak to finish it trains instead of trying.
        state.pop('league_loop', None)
    elif loop is not None:
        # A postgame League run, once started, finishes with its Hall of Fame entry before new work.
        if policy.in_league(snapshot):
            state['league_entered'] = True
        state['phase'] = 'league'
        return league_funding(policy, snapshot, Goal, again=True)
    return None


def journey(policy, snapshot, mem, Goal):
    data, state = policy.data, policy.collection
    from .npc_trades import requests as trade_requests
    state['prerequisites'] = sorted(prerequisites(data, snapshot) | trade_requests(policy, snapshot, getattr(mem, 'memory', None)))
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
    if not snapshot.event('EVENT_GOT_SUPER_ROD'):
        return policy.person(snapshot, 'super_rod', 'Get the Super Rod for the Pokédex expedition',
                             'ROUTE_12_SUPER_ROD_HOUSE', 'Route12SuperRodHouseFishingGuruScript')
    for flag, map_name, script, label in [
            ('EVENT_GOT_TM02_HEADBUTT', 'ILEX_FOREST', 'IlexForestHeadbuttGuyScript', 'Learn about Headbutt encounters'),
            ('EVENT_GOT_TM08_ROCK_SMASH', 'ROUTE_36', 'Route36RockSmashGuyScript', 'Learn about Rock Smash encounters')]:
        if not snapshot.event(flag):
            return policy.person(snapshot, flag.lower(), label, map_name, script)
    funding = state.get('funding')
    if funding is not None and snapshot.hall_of_fame_count >= funding:
        state.pop('funding', None)
        funding = None
    from pokecore.gen2.breeding import retrieval_cost
    from .breeding import pairings
    fees = retrieval_cost(data, snapshot)
    from .. import config
    starter_gifts = getattr(config, 'LEAGUE_REWARDS', False) and not {152, 155, 158} <= snapshot.owned
    from .quests import static_wanted, ultra_shortfall
    from .store_stock import shortfall as store_shortfall
    if funding is None and (snapshot.money < 5000 and sum(count for _, count in snapshot.pockets['balls']) < 4
                            or fees and snapshot.money < fees + 1000 or starter_gifts
                            or snapshot.can_catch and ultra_shortfall(policy, snapshot) and static_wanted(policy, snapshot)
                            # A wanted Day Care pair waits for 3000 to start, and nothing else earns it.
                            or snapshot.money < 3000 and not state.get('breeding')
                            and getattr(snapshot, 'daycare', None) is not None and pairings(policy, snapshot)
                            or store_shortfall(policy, snapshot)):
        state['funding'] = funding = snapshot.hall_of_fame_count + 1
    if funding is not None:
        state['phase'] = 'league'
        return league_funding(policy, snapshot, Goal)
    goal = league_loop(policy, snapshot, Goal)
    if goal:
        return goal
    if getattr(policy, 'returned', set()) & {243, 244, 245, 249, 250, 251}:
        # A returned legendary waits at its original home ahead of routine collection.
        from .quests import legends
        goal = legends(policy, snapshot, Goal)
        if goal:
            return goal
    from .item_sources import pickups
    # A stone a phone trainer holds today and the Monday night Moon Stone expire, so they go first.
    goal = pickups(policy, snapshot, mem, Goal)
    if goal:
        return goal
    from .ruins import journey as ruins
    goal = ruins(policy, snapshot, Goal)
    if goal:
        return goal
    goal = lapras(policy, snapshot, mem, Goal)
    if goal:
        return goal
    from .quests import gifts
    gift = gifts(policy, snapshot, Goal)
    if gift:
        return gift
    from .quests import trade_items
    goal = trade_items(policy, snapshot, Goal)
    if goal:
        return goal
    from .npc_trades import journey as npc_trades
    goal = npc_trades(policy, snapshot, mem, Goal)
    if goal:
        return goal
    if 'tower' not in policy.completed:
        goal = tower(policy, snapshot, Goal)
        if goal:
            return goal
    from .celebi import journey as celebi
    goal = celebi(policy, snapshot, Goal)
    if goal:
        return goal
    goal = contest(policy, snapshot, Goal)
    if goal:
        return goal
    from .breeding import journey as breed
    goal = breed(policy, snapshot, Goal)
    # The Day Care counts the steps of any walk and carried eggs hatch on any walk, so pacing Goldenrod
    # for them waits behind every other errand. The egg and partner errands still go first.
    nursery = None
    if goal and goal.key == 'collection_hatch':
        nursery, goal = goal, None
    if goal:
        return while_waiting(policy, snapshot, mem, goal, Goal)
    from .gamecorner import journey as prizes
    goal = prizes(policy, snapshot, Goal)
    if goal:
        return goal
    if state.get('funding') is not None:
        # The prize partner just asked for League prize money. Start that run now, or one decision
        # picks a later goal such as the Tohjo Falls Moon Stone and the next one walks away from it.
        state['phase'] = 'league'
        return league_funding(policy, snapshot, Goal)
    from .quests import stones
    goal = stones(policy, snapshot, Goal)
    if goal:
        return goal
    from .item_sources import phones
    goal = phones(policy, snapshot, mem, Goal)
    if goal:
        return goal
    from .store_stock import journey as store
    goal = store(policy, snapshot, Goal)
    if goal:
        return goal
    from .champion_shop import journey as champion_shop
    goal = champion_shop(policy, snapshot, Goal)
    if goal:
        return goal
    from .breeding import hatching
    goal = hatching(policy, snapshot, Goal)
    if goal:
        return while_waiting(policy, snapshot, mem, goal, Goal)
    goal = peer_store(policy, snapshot, Goal)
    if goal:
        return goal
    from .training import journey as training
    goal = training(policy, snapshot, mem, Goal)
    if goal:
        return while_waiting(policy, snapshot, mem, goal, Goal)
    current_time = ('morning', 'day', 'night')[min(2, mem.byte('wTimeOfDay'))]
    target = state.get('target')
    # With every box full and nothing to release, a hunt could never keep a catch.
    room = not policy.no_room(snapshot)
    if (target and (not wanted(policy, snapshot, target['species']) or not matching_time(target['time'], current_time)
                   or not room or standing_down(policy, hunt_key(target['species'])))):
        if not wanted(policy, snapshot, target['species']):
            # Caught, or its item found: the search is done, so its spent decisions go too.
            forget(policy, hunt_key(target['species']))
        state.setdefault('attempts', {})[str(target['species'])] = policy.decisions
        state['target'] = target = None
    if target is None:
        from .quests import legends
        legend = legends(policy, snapshot, Goal)
        if legend:
            return legend
        groups = {}
        items = dict(snapshot.items)
        for row in data.encounters if room else ():
            if (not wanted(policy, snapshot, row['species']) or not matching_time(row['time'], current_time)
                    or standing_down(policy, hunt_key(row['species'])) or not usable(policy, snapshot, row, items)):
                continue
            method = row['method']
            key = (row['map'], method, row['species'], row['time'] == 'rare trees')
            groups.setdefault(key, {**row, 'chance': 0})['chance'] += row['chance']
        routes, points = {}, {}
        choices = []
        distances = {}
        for mid, _, _, _ in groups:
            if mid not in distances:
                route = policy.nav.route(snapshot.map, mid)
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
            attempted = state.get('attempts', {}).get(str(species), -100000)
            recent = policy.decisions - attempted < 18000
            choices.append((not bool(policy.demand.get(species) or species in state['prerequisites']
                                     or species in carriers),
                            species in snapshot.owned, recent,
                            len(route) + 50 / max(1, row['chance']), species, mid, method, row))
        if choices:
            target = dict(min(choices, key=lambda row: row[:-1])[-1], started=policy.decisions)
            target['expected'] = target_expected(policy, snapshot, target, distances.get(target['map'], 0) % 9999)
            state['target'] = target
        else:
            goal = tower(policy, snapshot, Goal)
            if goal:
                return goal
            # A finished run keeps playing the way Red, Blue and Yellow do: better-DV hunts, training ten
            # levels at a time, bounded shiny searches and League runs, in rotation (see postgame).
            from . import postgame
            goal = postgame.journey(policy, snapshot, mem, Goal, current_time)
            if goal:
                return goal
            if nursery:
                return while_waiting(policy, snapshot, mem, nursery, Goal)
            eggs = any(mon.egg for mon in snapshot.party)
            # Carried eggs hatch on this walk, so only a walk without them is idle.
            state['phase'] = 'hatching' if eggs else 'waiting'
            # Nothing else is useful until the cartridge clock opens a window or a trade brings new work.
            # The plan is rebuilt every step, so clock-gated work starts as soon as its window opens.
            return patrol(policy, snapshot, Goal, waiting_label(policy, snapshot, mem, current_time))
    return hunt(policy, snapshot, Goal)


def postgame_league(policy, snapshot, mem, current_time):
    """Whether a postgame League run may start: the Champion is beaten, the team is ready and no clock wait is due."""
    if 'champion' not in getattr(policy, 'completed', {}) or not snapshot.hall_of_fame_count:
        return False
    if not league_ready(policy, snapshot):
        return False
    return clock_wait(policy, snapshot, mem, current_time) is None


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
        state.setdefault('attempts', {})[str(target['species'])] = policy.decisions
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
        else:
            route = policy.nav.regions.route(snapshot, mid, [point[:2] for point in points], cut=True, surf=True)
            if route:
                region = route[-1][1][1]
                x, y, face = next((point for point in points
                                   if region in policy.nav.regions.memberships(mid, point[:2], True, True)), points[0])
            else:
                if postgame:
                    return unavailable(policy, snapshot, Goal)
                state.setdefault('attempts', {})[str(target['species'])] = policy.decisions
                state['target'] = None
                return Goal('collection_wait', 'Replan the Pokédex expedition', data.maps[mid]['constant'], snapshot.x, snapshot.y)
    else:
        route = policy.nav.regions.route(snapshot, mid, [point[:2] for point in points], cut=True, surf=True)
        region = route[-1][1][1] if route else None
        x, y, face = next((point for point in points
                           if region in policy.nav.regions.memberships(mid, point[:2], True, True)), points[0])
    if label is None:
        name = data.species[target['species']]['name']
        item = item_hunts(policy, snapshot).get(target['species'])
        if item and target['species'] in snapshot.owned:
            name += ' holding ' + data.item_names.get(item, 'its item')
        label = f'Search for {name}'
    key = 'collection_fish' if method.endswith('rod') else 'collection_field' if method in {'headbutt', 'rock smash'} else 'collection_hunt'
    if postgame:
        forget(policy, LOADING)
    return Goal(key, f'{label} in {data.maps[mid]["name"]}', data.maps[mid]['constant'], x, y, face)


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
        state.setdefault('attempts', {})[str(target['species'])] = policy.decisions
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
        from .ledger import member, unequip_step
        step = unequip_step(policy, snapshot)
        if step is not None:
            return step
        unit = policy.storage_target(snapshot)
        if unit is None:
            return 'wait'
        mon = unit.detail
        if unit.action == 'unequip':
            policy.collection['unequip'] = member(mon)
            return unequip_step(policy, snapshot) or 'wait'
        policy.menu = (ChangeBox(mon.box) if mon.box != snapshot.active_box
                       else Release(mon.box, mon.position, member(mon)))
        return 'a'
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
    if key in {'collection_wait', 'collection_idle', 'collection_hunt', 'collection_roam_hunt', 'collection_roam_lead', 'collection_static_lead'}:
        return 'wait'
    return None
