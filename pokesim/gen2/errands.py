"""Whether a supply errand is worth its walk, weighed on the utility arbiter.

A shop trip costs the walk there and back, the purchase, and any puzzle map on the way, since a slide
or a boulder that resets has to be solved again. Leaving the work under way costs what it loses: in
the League or a puzzle map that is the whole sequence, and inside a cave or dungeon whose story goal
is not done yet it is the walk back through it. The trip runs when it is worth more per frame than
restocking later, on the next walk past a shop.
"""
from pokecore.gen2.maps import has_ice

from ..planning import arbiter, values
from ..planning.arbiter import Candidate, Tier
from .collection import ERRAND_FRAMES, MAP_FRAMES

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
