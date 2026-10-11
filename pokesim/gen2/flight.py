"""Use visited Fly destinations when they shorten the walking route, or when no walking route exists.

Fly only works outside, on town and route maps. Indoors, in a cave or in a gate with no walking route
to the goal, the policy first walks to the nearest outside place it can reach, then flies from there.
"""
from collections import deque
from dataclasses import replace

from .menus import Fly

# The map environments Fly can be used from.
OUTSIDE = frozenset({'TOWN', 'ROUTE'})


def flyer(snapshot):
    """The party slot that can use Fly, or None without the badge or a Pokémon that knows it."""
    if not snapshot.badges & 32:
        return None
    return next((i for i, mon in enumerate(snapshot.party) if not mon.egg and 19 in mon.moves), None)


def shortcut(policy, snapshot, mem, destination):
    data, nav = policy.data, policy.nav
    current = data.maps[snapshot.map]
    slot = flyer(snapshot)
    if current['environment'] not in OUTSIDE or slot is None:
        return None
    visited = int.from_bytes(mem.read('wVisitedSpawns', 4), 'little')
    targets = [(policy.goal.x, policy.goal.y)]
    cut = bool(snapshot.badges & 2) and any(15 in mon.moves for mon in snapshot.party)
    surf = bool(snapshot.badges & 8) and any(57 in mon.moves for mon in snapshot.party)
    nav.regions.observe(snapshot.map, nav.collision(snapshot, mem.memory))
    region = tuple(sorted(nav.regions.memberships(snapshot.map, (snapshot.x, snapshot.y), cut, surf)))
    if not region:
        # Halfway over a ledge the player is reported on the blocked tile it hops across. No region
        # holds that tile, so no walking route would show and Fly would be chosen for no reason.
        return None
    token = (snapshot.map, region, destination, tuple(targets), visited, hash(snapshot.event_flags), cut, surf)
    cache = getattr(nav, 'flight_cache', None)
    if cache and cache[0] == token:
        selected = cache[1]
    else:
        route = nav.regions.route(snapshot, destination, targets, cut=cut, surf=surf)
        choices = []
        # No walking route (a returned Sudowoodo blocking Route 36, say) still leaves the Fly points.
        if route is None or len(route) >= 6:
            for index, point in enumerate(data.fly_points):
                mid = point['map']
                if mid == snapshot.map or data.maps[mid]['region'] != current['region'] or not visited & 1 << point['spawn']:
                    continue
                landing = replace(snapshot, map=mid, x=point['x'], y=point['y'])
                remainder = nav.regions.route(landing, destination, targets, cut=cut, surf=surf)
                if remainder is not None and (route is None or len(remainder) + 4 < len(route)):
                    choices.append((len(remainder), index, mid))
        selected = min(choices)[1:] if choices else None
        nav.flight_cache = token, selected
    return Fly(slot, selected[0], snapshot.map, selected[1]) if selected else None


def landings(policy, destination, targets, region, visited, cut, surf, snapshot):
    """Whether some visited Fly point of the region has a walking route to the destination."""
    data, nav = policy.data, policy.nav
    for point in data.fly_points:
        mid = point['map']
        if data.maps[mid]['region'] != region or not visited & 1 << point['spawn']:
            continue
        landing = replace(snapshot, map=mid, x=point['x'], y=point['y'])
        if nav.regions.route(landing, destination, targets, cut=cut, surf=surf) is not None:
            return True
    return False


def outside(policy, snapshot, mem, destination):
    """Where to walk out to when inside with no walking route to the destination, so Fly can take over.

    Returns a map and a point there in the nearest reachable town or route region from which a visited
    Fly point leads to the destination, or None when walking works, Fly cannot be used or does not help.
    """
    data, nav = policy.data, policy.nav
    if data.maps[snapshot.map]['environment'] in OUTSIDE or flyer(snapshot) is None:
        return None
    visited = int.from_bytes(mem.read('wVisitedSpawns', 4), 'little')
    targets = [(policy.goal.x, policy.goal.y)]
    cut = bool(snapshot.badges & 2) and any(15 in mon.moves for mon in snapshot.party)
    surf = bool(snapshot.badges & 8) and any(57 in mon.moves for mon in snapshot.party)
    nav.regions.observe(snapshot.map, nav.collision(snapshot, mem.memory))
    starts = tuple((snapshot.map, region) for region in
                   sorted(nav.regions.memberships(snapshot.map, (snapshot.x, snapshot.y), cut, surf, arrive=True)))
    token = (starts, destination, tuple(targets), visited, hash(snapshot.event_flags), cut, surf)
    cache = getattr(nav, 'outside_cache', None)
    if cache and cache[0] == token:
        return cache[1]
    exit_point = None
    if nav.regions.route(snapshot, destination, targets, cut=cut, surf=surf) is None:
        helps = {}
        seen = set(starts)
        queue = deque(starts)
        while queue and exit_point is None:
            for node, _, _ in nav.regions.edges(queue.popleft(), cut, surf):
                if node in seen:
                    continue
                seen.add(node)
                entry = data.maps[node[0]]
                if entry['environment'] not in OUTSIDE:
                    queue.append(node)
                    continue
                if entry['region'] not in helps:
                    helps[entry['region']] = landings(policy, destination, targets, entry['region'],
                                                      visited, cut, surf, snapshot)
                if helps[entry['region']]:
                    labels = nav.regions.regions(node[0], cut, surf)
                    exit_point = node[0], min(point for point, label in labels.items() if label == node[1])
                    break
                # Fly does not help from here, but walking on outside might still reach a place it does.
                queue.append(node)
    nav.outside_cache = token, exit_point
    return exit_point
