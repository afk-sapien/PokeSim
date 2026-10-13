"""Repeatable sources of evolution stones once the cartridge's one-time stones are spent.

Bill's grandfather and Tohjo Falls give one stone each. A Pokédex or peer request that needs
another one has these repeatable sources (pret pokecrystal and pokegold):

* Crystal only: Picnicker Gina (Leaf Stone, Route 34), Schoolboy Alan (Fire Stone, Route 36),
  Lass Dana (Thunderstone, Route 38) and Fisher Tully (Water Stone, Route 42) find a stone after
  their number is registered. Only their own incoming call sets the daily "has a stone" flag
  (half the calls before the first gift, 1 in 11 after), it clears at midnight, and talking to
  them while it is set hands the stone over. Gold and Silver phone trainers never give items,
  so those cartridges have no repeatable Leaf, Fire, Water or Thunder Stone at all.
* Every game: the Clefairy dance in Mt. Moon Square on Monday night uncovers a rock with a hidden
  Moon Stone under it, once per day.
* Every game: first prize in the Bug-Catching Contest is a Sun Stone (contest.py runs that).

Every source stands down when it cannot progress, so an exhausted or unreachable one is not
walked to forever.
"""
from collections import Counter

from .standdown import stand_down, standing_down

# item: (trainer, contact id, route, object script, item flag bit, rematch flag bit, beaten event)
# Contact ids follow constants/phone_constants.asm. The flag bits are the ENGINE_*_HAS_* and
# ENGINE_*_READY_FOR_REMATCH positions in wDailyPhoneItemFlags and wDailyRematchFlags.
PHONE_GIFTS = {
    'LEAF_STONE': ('Gina', 21, 'ROUTE_34', 'TrainerPicnickerGina1', 3, 12, 'EVENT_BEAT_PICNICKER_GINA'),
    'FIRE_STONE': ('Alan', 24, 'ROUTE_36', 'TrainerSchoolboyAlan1', 4, 14, 'EVENT_BEAT_SCHOOLBOY_ALAN'),
    'THUNDERSTONE': ('Dana', 26, 'ROUTE_38', 'TrainerLassDana1', 5, 15, 'EVENT_BEAT_LASS_DANA'),
    'WATER_STONE': ('Tully', 29, 'ROUTE_42', 'TrainerFisherTully', 7, 17, 'EVENT_BEAT_FISHER_TULLY'),
}
PHONE_SLOTS = 10
# Decisions spent on one step before it stands down. A wait decision is 24 frames, so 27000 is
# about three game hours by the phone, plenty for a call that comes every 3 to 20 game minutes.
REGISTER_DECISIONS = 6000
WAIT_DECISIONS = 27000
PICKUP_DECISIONS = 8000
SQUARE_DECISIONS = 8000
# Decisions away from a step after which its count starts over, as after a battle or a detour.
GAP = 2000
MONDAY, NIGHT = 1, 2
SQUARE_ROCK = 3
_NEEDS = [None, None]


def phone_key(item):
    return f'phone:{item}'


def item_needs(policy, snapshot):
    """Evolution items the bag is short of, as {item id: missing count}.

    An item counts for each held partner whose item evolution is missing from the Pokédex, is a
    prerequisite, or is asked for by a peer, the same rule training.projects uses to spend one.
    """
    from .collection import prerequisites
    from .training import requested
    data, demand = policy.data, getattr(policy, 'demand', None) or {}
    party, stored = tuple(getattr(snapshot, 'party', ())), tuple(getattr(snapshot, 'stored', ()))
    items, owned = tuple(getattr(snapshot, 'items', ())), frozenset(getattr(snapshot, 'owned', ()))
    key = (id(data), party, stored, items, owned, tuple(sorted(demand.items())))
    if _NEEDS[0] == key:
        return dict(_NEEDS[1])
    needed = prerequisites(data, snapshot) if party or stored else set()
    targets = {}
    for mon in party + stored:
        if mon.egg:
            continue
        for evo in data.species[mon.species]['evolutions']:
            if evo['method'] != 'item':
                continue
            species = evo['species']
            if (species in owned and species not in needed
                    and not requested(data, snapshot, demand, species, item=True)):
                continue
            item = data.items.get(evo['requirements'][0])
            if item is not None:
                targets.setdefault(item, set()).add(species)
    bag = Counter()
    for item, count in items:
        bag[item] += count
    result = {item: len(wanted) - bag[item] for item, wanted in targets.items() if len(wanted) > bag[item]}
    _NEEDS[:] = [key, result]
    return dict(result)


def _bit(mem, symbol, bit):
    return bool(mem.byte(symbol, bit // 8) & (1 << (bit % 8)))


def _registered(mem, contact):
    return contact in mem.read('wPhoneList', PHONE_SLOTS)


def _limited(policy, key, limit):
    """Whether ``key`` has been the goal for over ``limit`` decisions in a row.

    A step that other work interrupted for a while starts its count again when it comes back.
    """
    state = policy.collection.setdefault('item_sources', {})
    start, last = state.get(key) or (policy.decisions, policy.decisions)
    if policy.decisions - last > GAP:
        start = policy.decisions
    if policy.decisions - start > limit:
        state.pop(key, None)
        return True
    state.clear()
    state[key] = [start, policy.decisions]
    return False


def pickups(policy, snapshot, mem, Goal):
    """Time-limited collection: a stone a phone trainer holds today, or the Monday night Moon Stone."""
    data = policy.data
    needs = item_needs(policy, snapshot)
    if data.game == 'crystal':
        for name, (trainer, contact, route, script, item_bit, rematch_bit, _) in PHONE_GIFTS.items():
            item = data.items[name]
            key = phone_key(name)
            if (item not in needs or standing_down(policy, key) or not _registered(mem, contact)
                    or not (_bit(mem, 'wDailyPhoneItemFlags', item_bit) or _bit(mem, 'wDailyRematchFlags', rematch_bit))):
                continue
            if _limited(policy, 'pickup:' + name, PICKUP_DECISIONS):
                stand_down(policy, key)
                continue
            # A rematch the trainer asked for comes before the gift in the trainer's own script.
            label = (f'Collect the {data.item_names.get(item, name)} from {trainer}'
                     if _bit(mem, 'wDailyPhoneItemFlags', item_bit) else f'Answer {trainer}’s rematch so the stone can follow')
            return policy.person(snapshot, 'collection_phone_gift', label, route, script)
    return moon_square(policy, snapshot, mem, needs, Goal)


def moon_square(policy, snapshot, mem, needs, Goal):
    data = policy.data
    item = data.items.get('MOON_STONE')
    key = 'moon_square'
    square = data.map_ids.get('MOUNT_MOON_SQUARE')
    if item not in needs or square is None or standing_down(policy, key):
        return None
    danced = mem.byte('wDailyFlags2') & 1
    if snapshot.map == square and danced and not snapshot.event('EVENT_MOUNT_MOON_SQUARE_HIDDEN_MOON_STONE'):
        # The dance uncovered the stone this visit. Leaving the square hides it again.
        if _limited(policy, key, SQUARE_DECISIONS):
            stand_down(policy, key)
            return None
        rock = any(index == SQUARE_ROCK for index, _, _ in snapshot.objects)
        if rock:
            return Goal('collection_square_rock', 'Smash the rock the Clefairy danced around', 'MOUNT_MOON_SQUARE', 7, 8, 'up')
        return Goal('collection_square_stone', 'Pick up the Moon Stone under the rock', 'MOUNT_MOON_SQUARE', 7, 8, 'up')
    if danced or mem.byte('wCurDay') % 7 != MONDAY or mem.byte('wTimeOfDay') != NIGHT:
        return None
    from .quests import rock_smash_task
    if rock_smash_task(policy, snapshot) is None or policy.nav.route(snapshot.map, square) is None:
        return None
    if _limited(policy, key, SQUARE_DECISIONS):
        stand_down(policy, key)
        return None
    return Goal('collection_square', 'Watch the Clefairy dance in Mt. Moon on Monday night', 'MOUNT_MOON_SQUARE', 7, 11)


def phones(policy, snapshot, mem, Goal):
    """Register a stone trainer's number, then wait somewhere with phone service for the call."""
    data = policy.data
    if data.game != 'crystal':
        return None
    needs = item_needs(policy, snapshot)
    for name, (trainer, contact, route, script, _, _, beaten) in PHONE_GIFTS.items():
        item, key = data.items[name], phone_key(name)
        if item not in needs or standing_down(policy, key):
            continue
        stone = data.item_names.get(item, name)
        if not _registered(mem, contact):
            if sum(1 for slot in mem.read('wPhoneList', PHONE_SLOTS) if slot) >= PHONE_SLOTS:
                stand_down(policy, key)
                continue
            if _limited(policy, 'register:' + name, REGISTER_DECISIONS):
                stand_down(policy, key)
                continue
            verb = 'Get' if snapshot.event(beaten) else 'Beat'
            return policy.person(snapshot, 'collection_phone_register',
                                 f'{verb} {trainer}’s number for a {stone}', route, script)
        if _limited(policy, 'wait:' + name, WAIT_DECISIONS):
            stand_down(policy, key)
            continue
        # Calls never come from the map the caller stands on, in caves without service or on a
        # doorway, so wait by a Pokémon Center PC.
        spot = policy.storage_goal(snapshot)
        return Goal('collection_phone_wait', f'Wait by the phone for {trainer} to find a {stone}',
                    spot.map_name, spot.x, spot.y, spot.face)
    return None


def arrive(policy, snapshot):
    key = policy.goal.key
    if key == 'collection_phone_wait':
        return 'wait'
    if key == 'collection_square':
        # The dance runs by itself on the trigger tile. Off Monday night nothing happens there.
        return 'wait'
    if key == 'collection_square_rock':
        from .quests import rock_smash_task
        task = rock_smash_task(policy, snapshot)
        if task is None:
            stand_down(policy, 'moon_square')
            return 'b'
        policy.menu = task
        return 'wait'
    return None


def answer(policy, snapshot):
    """The YES answer to a stone trainer asking to swap numbers, or None for any other prompt."""
    goal = policy.goal
    if goal is None or goal.key != 'collection_phone_register' or 'YES' not in snapshot.text or 'NO' not in snapshot.text:
        return None
    from .menus import choose
    return choose(snapshot.tiles, 'YES', exact=True)
