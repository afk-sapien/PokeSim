"""The Gen II heal and shop errands (planning/errand.py), and whether a supply errand is worth its walk.

A shop trip costs the walk there and back, the purchase, and any puzzle map on the way, since a slide
or a boulder that resets has to be solved again. Leaving the work under way costs what it loses: in
the League or a puzzle map that is the whole sequence, and inside a cave or dungeon whose story goal
is not done yet it is the walk back through it. The trip runs when it is worth more per frame than
restocking later, on the next walk past a shop. These are weighed on the utility arbiter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pokecore.gen2.maps import has_ice

from ..planning import arbiter, values
from ..planning.arbiter import Candidate, Tier
from ..planning.errand import Errand
from ..runtime.policy import Action
from .collection import ERRAND_FRAMES, MAP_FRAMES
from .menus import Buy, Sell

# Frames a puzzle map or a League run takes to do again, about an hour of play.
SEQUENCE_FRAMES = 200000
# Before Red, a restock is worth a short trip, five maps each way. Afterwards the whole region is open
# and the run has little else to break off from.
NEARBY_MAPS = 5
LATE_FRAMES = 60000
# With no ball in the bag, no catch can happen, so a restock is worth a longer trip.
EMPTY_FRAMES = 120000
_PUZZLES = {}


def puzzle_maps(data):
    """Maps whose layout resets when left: ice floors, maps with two or more boulders, and the indoor
    or cave maps whose warps lead straight into one, such as the gym floor below the boulder holes."""
    key = id(data)
    if key not in _PUZZLES:
        maps = data.maps
        puzzles = {mid for mid, entry in maps.items()
                   if has_ice(entry['collision']) or sum(obj['sprite'] == 'SPRITE_BOULDER' for obj in entry['objects']) >= 2}
        puzzles |= {mid for mid, entry in maps.items() if entry.get('environment') in {'INDOOR', 'CAVE', 'DUNGEON'}
                    and any(warp['map'] in puzzles for warp in entry['warps'])}
        _PUZZLES[key] = (data, frozenset(puzzles))
    return _PUZZLES[key][1]


def exit_cost(policy, snapshot):
    """Frames lost by breaking off the current work for an errand."""
    data = policy.data
    entry = data.maps.get(snapshot.map, {})
    if policy.in_league(snapshot) or policy.in_transmitter_room(snapshot) or snapshot.map in puzzle_maps(data):
        return SEQUENCE_FRAMES
    goal = getattr(policy, 'goal', None)
    if (entry.get('environment') in {'CAVE', 'DUNGEON'} and 'champion' not in policy.completed
            and goal is not None and goal.map_name == entry.get('constant')):
        # A story goal inside this cave or dungeon, such as the Burned Tower beasts or the Goldenrod
        # warehouse, is walked back to through every trainer and puzzle on the way.
        return SEQUENCE_FRAMES
    return 0.0


def worth(policy, snapshot):
    """Frames a restock is worth now, the price of restocking later instead."""
    if not snapshot.pockets['balls']:
        return EMPTY_FRAMES
    if 'red' in policy.completed:
        return LATE_FRAMES
    return ERRAND_FRAMES + 2 * NEARBY_MAPS * MAP_FRAMES


def trip_frames(policy, snapshot, hops, crossing=(), *, current=False):
    """Frames of a shop trip ``hops`` maps away, there and back, through the maps in ``crossing``.

    ``current`` is the shop already chosen, which the run is walking to. Its walk is under way, so only
    the purchase and any puzzle still ahead count.
    """
    puzzles = puzzle_maps(policy.data)
    crossed = len({mid for mid in crossing if mid in puzzles and mid != snapshot.map})
    walk = 0 if current else 2 * hops * MAP_FRAMES
    return ERRAND_FRAMES + walk + crossed * SEQUENCE_FRAMES


def pick(policy, snapshot, key, hops, crossing=(), *, current=False, exit_frames=None):
    """The arbiter's pick between a shop trip and restocking later, as a candidate."""
    exit_frames = exit_cost(policy, snapshot) if exit_frames is None else exit_frames
    later = Candidate('restock_later', Tier.UPKEEP, values.SMALL, worth(policy, snapshot))
    trip = Candidate(key, Tier.UPKEEP, values.SMALL, trip_frames(policy, snapshot, hops, crossing, current=current),
                     interrupt_frames=exit_frames)
    return arbiter.choose([trip, later])


def worth_trip(policy, snapshot, key, hops, crossing=(), *, current=False, exit_frames=None):
    """Whether a shop trip ``hops`` maps away through ``crossing`` beats restocking later."""
    return pick(policy, snapshot, key, hops, crossing, current=current, exit_frames=exit_frames).key == key


@dataclass
class Heal(Errand):
    """The walk to a Pokémon Center's nurse while the party needs one.

    ``map`` is the center the walk goes to, kept while it stays reachable so equal walks do not flip it
    (Policy.center), and saved. ``pp`` says the heal is for spent PP, which the journal notes once the
    nurse is done. Both are written as the heal is offered, so the boss check and a survey read the
    center the walk takes. The heal is done when the party is healthy again, and the nurse's talk is
    the usual arrival at a person."""
    key: ClassVar[str] = 'heal'
    map: int | None = None
    pp: bool = False

    def offer(self, policy, snapshot):
        from ..planning import boss
        from ..planning.ledger import PP
        from .ledger import battle_room, cured, walk_spent
        from .policy import Goal
        if policy.heal_blocked(snapshot):
            if any(not mon.egg for mon in getattr(snapshot, 'party', ())):
                # No walk out from here, so a boss ahead is met as the party stands.
                policy.boss_ready(snapshot, True)
            return None, None
        data = policy.data
        healthy = [mon for mon in snapshot.party if not mon.egg]
        # A status a cure in the bag clears is treated where the party stands (field_cure), not walked to a nurse.
        spent = bool(healthy) and walk_spent(data, cured(data, snapshot))
        surveying = getattr(policy, 'ladder_survey', False)
        if not healthy or not spent and policy.boss_ready(snapshot, False) != boss.HEAL:
            if not surveying:
                if self.pp and self.map == snapshot.map:
                    # A heal its spent PP called for says so in the journal once the nurse is done.
                    from .collection import pin_events
                    pin_events(policy).append(boss.pp_heal_event(data.maps[snapshot.map]['name']))
                self.pp = False
            self.map = None
            return None, None
        center = policy.center(snapshot)
        if center is None:
            self.map = None
            return None, None
        mid, nurse = center
        if self.map is None and not surveying:
            self.pp = spent and battle_room(data, snapshot)[PP] == 0
        self.map = mid
        return Goal('heal', 'Restore the team at a Pokémon Center', data.maps[mid]['constant'],
                    nurse['x'], nurse['y'] + 2, 'up'), None

    def state_dict(self):
        return {'map': self.map}

    def load_state_dict(self, state):
        self.map = state.get('map')


@dataclass
class Shop(Errand):
    """A supply trip: buy capture supplies at a mart or, with no ball and no money for one, sell a spare
    item for them.

    ``purchase`` is what the clerk is asked for, (item, amount) to buy or (item, count) to sell.
    ``location`` is the shop chosen for a purchase, (map, clerk script, item), kept while its trip is
    worth it so the trip does not switch halfway. Both are saved, and both are written only when the
    trip is picked (rule A). The trip is done when nothing is worth buying, and a talk at the clerk
    that changes nothing drops it."""
    key: ClassVar[str] = 'shop'
    purchase: tuple | None = None
    location: tuple | None = None

    def offer(self, policy, snapshot):
        """A supply errand worth breaking off for and the commit that writes its purchase and its shop, or
        ``(None, None)``.

        Each trip is weighed against restocking later on the arbiter (worth_trip): the walk there and
        back, the puzzle maps on the way and what leaving the current work loses. That keeps the run
        from shopping out of the League, a puzzle map or a story dungeon, and from shopping through
        Ice Path before it is solved.
        """
        if not snapshot.event('EVENT_GAVE_MYSTERY_EGG_TO_ELM'):
            self.location = None
            return None, None
        from . import ledger
        data, nav = policy.data, policy.nav
        exit_frames = exit_cost(policy, snapshot)
        if exit_frames >= worth(policy, snapshot):
            # No trip can beat restocking later from here. The chosen shop stays chosen for after.
            return None, None
        cut, surf = bool(snapshot.badges & 2), bool(snapshot.badges & 8)
        if snapshot.money < ledger.price(data, 'POKE_BALL'):
            self.location = None
            # With no ball and no money for one, the ledger sells what is worth least for money.
            sale = None if snapshot.pockets['balls'] else ledger.ball_sale(data, snapshot)
            if sale is None:
                return None, None
            choices = []
            for mid, entry in data.maps.items():
                if entry['region'] != policy.travel_region(snapshot):
                    continue
                for shop in entry['shops']:
                    if not policy.clerk_present(snapshot, entry, shop):
                        continue
                    goal = policy.person(snapshot, 'sell_supplies', 'Sell a spare item for capture supplies', entry['constant'], shop['script'])
                    route = nav.regions.route(snapshot, mid, [(goal.x, goal.y)], cut=cut, surf=surf)
                    if route is not None and worth_trip(policy, snapshot, 'sell_supplies', len(route),
                                                        [node[0] for _, node, _, _ in route], exit_frames=exit_frames):
                        choices.append((len(route), mid, goal))
            if choices:
                def sell():
                    self.purchase = sale
                return min(choices, key=lambda row: row[:2])[-1], sell
            return None, None
        requests = ledger.supplies(policy, snapshot)
        if not requests:
            self.location = None
            return None, None
        if self.location and nav.regions.between(snapshot, cut, surf):
            # In a ledge hop the coordinates read the wall tile jumped over, which is in no region, so no
            # route can be judged until the player lands. The shop already chosen stays the goal. The walk
            # to Olivine Mart drops three ledges on Route 39, and the trip was dropped in each hop.
            mid, script, _ = self.location
            return policy.person(snapshot, 'buy_balls', 'Restock adventure supplies', data.maps[mid]['constant'], script), None
        choices = []
        for priority, (key, names, amount) in enumerate(requests):
            reserve = ledger.held_money(data, snapshot, key)
            for mid, entry in data.maps.items():
                if entry['region'] != policy.travel_region(snapshot) or not entry['shops']:
                    continue
                # Cures are bought only where the player stands (ledger.cure_wanted), never on a trip.
                if key == 'cures' and mid != snapshot.map:
                    continue
                route = nav.walk(snapshot, mid)
                if route is None:
                    continue
                current = bool(self.location) and mid == self.location[0]
                crossing = [dest for _, dest, _, _ in route]
                if not worth_trip(policy, snapshot, 'buy_balls', len(route), crossing,
                                  current=current, exit_frames=exit_frames):
                    continue
                for shop in entry['shops']:
                    if not policy.clerk_present(snapshot, entry, shop):
                        continue
                    item = next((data.items[name] for name in names
                                 if data.items[name] in shop['items']
                                 and data.item_attributes[data.items[name]]['price'] <= snapshot.money - reserve), None)
                    if item:
                        goal = policy.person(snapshot, 'buy_balls', 'Restock adventure supplies', entry['constant'], shop['script'])
                        walk = nav.regions.route(snapshot, mid, [(goal.x, goal.y)], cut=cut, surf=surf)
                        # The walk can pass a puzzle map the map route did not, and a trip that breaks off
                        # there drops the shop at its mouth, so the next goal walks back out and the shop
                        # is chosen again.
                        if walk is None or not worth_trip(
                                policy, snapshot, 'buy_balls', len(route), crossing + [node[0] for _, node, _, _ in walk],
                                current=current, exit_frames=exit_frames):
                            continue
                        choices.append((priority, 0 if self.location == (mid, shop['script'], item) else 1,
                                        len(walk), mid, item, shop['script'], amount, reserve))
        if not choices:
            self.location = None
            return None, None
        _, _, _, mid, item, script, amount, reserve = min(choices)
        price = data.item_attributes[item]['price']

        def buy():
            self.location = (mid, script, item)
            self.purchase = (item, min(amount, (snapshot.money - reserve) // price))
        return policy.person(snapshot, 'buy_balls', 'Restock adventure supplies', data.maps[mid]['constant'], script), buy

    def act(self, policy, snapshot):
        """The press at the clerk the player faces: the Buy or the Sell menu, or B to leave when nothing
        here can be bought with the money in hand. None away from the clerk."""
        key = policy.goal.key
        if policy.interaction != key:
            return None
        if key == 'buy_balls':
            item, amount = self.purchase or (None, 0)
            affordable = snapshot.money // policy.data.item_attributes[item]['price'] if item else 0
            if min(amount, affordable) < 1:
                # Nothing here can be bought with the money in hand: forget the errand and leave.
                self.drop()
                policy.interaction = None
                return Action('b', 8, 36)
            policy.menu = Buy(item, min(amount, affordable), dict(snapshot.items).get(item, 0))
            return Action('a', 8, 36)
        if key == 'sell_supplies':
            item, count = self.purchase
            policy.menu = Sell(item, count)
            return Action('a', 8, 36)
        return None

    def drop(self):
        """Forget the purchase and the chosen shop."""
        self.purchase = self.location = None

    def state_dict(self):
        return {'purchase': self.purchase, 'location': self.location}

    def load_state_dict(self, state):
        self.purchase = tuple(state['purchase']) if state.get('purchase') else None
        self.location = tuple(state['location']) if state.get('location') else None
