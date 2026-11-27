"""Fly to a visited town when the walk on from its landing beats the walk from here by more than a flight costs.

One comparison, :func:`pick`, serves both generations. Each game brings its own costs and landings. Gen II
counts region hops between the Fly points its cartridge data lists (pokesim.gen2.flight). Kanto counts
walking steps from the landing table below.

Kanto flies after the first Hall of Fame only, where nearly all of a run's time goes. A party member that
knows Fly is taught it by the HM02 fetch (progression.fly_goal), which never puts it on a League battler.
"""
from ..strategy_data import MAPS, WORLD

FLY = 19
THUNDER_BADGE = 1 << 2
# CheckIfInOutsideMap: Fly works only where the map's tileset is one of these.
OUTSIDE = ('OVERWORLD', 'PLATEAU')
# Where each Fly destination sets the player down, by town map ID, from the cartridge's FlyWarpDataPtr.
# A town's bit in wTownVisitedFlag is its map ID, and the Fly menu names it as the map is named.
LANDINGS = {
    MAPS['PALLET_TOWN']: (5, 6),
    MAPS['VIRIDIAN_CITY']: (23, 26),
    MAPS['PEWTER_CITY']: (13, 26),
    MAPS['CERULEAN_CITY']: (19, 18),
    MAPS['LAVENDER_TOWN']: (3, 6),
    MAPS['VERMILION_CITY']: (11, 4),
    MAPS['CELADON_CITY']: (41, 10),
    MAPS['FUCHSIA_CITY']: (19, 28),
    MAPS['CINNABAR_ISLAND']: (11, 12),
    MAPS['INDIGO_PLATEAU']: (9, 6),
    MAPS['SAFFRON_CITY']: (9, 30),
}
TOWN_NAMES = {MAPS[name]: name for name in MAPS if MAPS[name] in LANDINGS}
# A flight's menus and animation, in walking steps: the frames from opening the menu to landing over the
# frames a postgame walk takes per step, the battles met on the way included since a flight skips those too.
# Both are means measured on two deep Red saves, see the pull request that added Kanto's Fly.
FLIGHT_FRAMES = 824
STEP_FRAMES = 34.5
FLIGHT_STEPS = round(FLIGHT_FRAMES / STEP_FRAMES)


def pick(walk, rests, minimum, margin):
    """The landing to fly to, or None to walk.

    ``walk`` is the walking cost from here, None when no walking route exists. ``rests`` yields
    (cost, landing) in preference order, with cost None where no route leads on from that landing, and is
    read only when a flight could pay. A walk under ``minimum`` is never flown. A landing counts when its
    cost plus ``margin``, the flight's own price, is under ``walk``. The cheapest wins, the first on a tie.
    """
    if walk is not None and walk < minimum:
        return None
    best = None
    for cost, landing in rests:
        if cost is not None and (walk is None or cost + margin < walk) and (best is None or cost < best[0]):
            best = cost, landing
    return best[1] if best else None


def flyer(snapshot):
    """The first party slot that knows Fly, or None."""
    return next((i for i, mon in enumerate(snapshot.party) if FLY in mon.moves), None)


def can_fly(snapshot):
    """Whether Kanto's Fly is open here: after the first Hall of Fame, with the Thunder Badge, outside, and a
    party member that knows it."""
    return bool(snapshot.hall_of_fame_count and snapshot.badges & THUNDER_BADGE
                and WORLD.get(snapshot.map, {}).get('tileset') in OUTSIDE and flyer(snapshot) is not None)


def visited(snapshot):
    """The landings of the towns the Fly menu lists, in town map ID order, as (map, x, y)."""
    return [(m, *LANDINGS[m]) for m in sorted(LANDINGS) if snapshot.towns_visited >> m & 1]


def destination(nav, snapshot, targets):
    """The town map ID to fly to on the way to ``targets``, or None to walk.

    The walk here is the navigator's route, and one search from every visited landing at once finds the
    nearest landing and its remaining walk. That search is kept until the targets, the visited towns, the
    story flags or the field moves change, since a step taken here changes the walk and not the landings.
    """
    if not targets or not can_fly(snapshot):
        return None
    pos = (snapshot.map, snapshot.x, snapshot.y)
    targets = frozenset(targets)
    if pos in targets:
        return None
    nav.route(pos, targets, snapshot.frame)
    walk = len(nav.path) if nav.path else None
    if walk is not None and walk < FLIGHT_STEPS:
        return None
    token = (targets, snapshot.towns_visited, hash(snapshot.event_flags), nav.can_surf, nav.can_cut)
    cache = getattr(nav, 'flight_cache', None)
    if not cache or cache[0] != token:
        cache = nav.flight_cache = token, nav.nearest_start(visited(snapshot), targets, snapshot.frame)
    found = cache[1]
    rests = [] if found is None else [found]
    landing = pick(walk, rests, FLIGHT_STEPS, FLIGHT_STEPS)
    return None if landing is None else landing[0]
