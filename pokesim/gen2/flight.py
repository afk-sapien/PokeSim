"""Use visited Fly destinations when they shorten a reachable walking route."""
from dataclasses import replace

from .menus import Fly


def shortcut(policy, snapshot, mem, destination):
    data, nav = policy.data, policy.nav
    current = data.maps[snapshot.map]
    if current['environment'] not in {'TOWN', 'ROUTE'} or not snapshot.badges & 32:
        return None
    slot = next((i for i, mon in enumerate(snapshot.party) if not mon.egg and 19 in mon.moves), None)
    if slot is None:
        return None
    visited = int.from_bytes(mem.read('wVisitedSpawns', 4), 'little')
    targets = [(policy.goal.x, policy.goal.y)]
    cut = bool(snapshot.badges & 2) and any(15 in mon.moves for mon in snapshot.party)
    surf = bool(snapshot.badges & 8) and any(57 in mon.moves for mon in snapshot.party)
    nav.regions.observe(snapshot.map, nav.collision(snapshot, mem.memory))
    region = tuple(sorted(nav.regions.memberships(snapshot.map, (snapshot.x, snapshot.y), cut, surf)))
    token = (snapshot.map, region, destination, tuple(targets), visited, hash(snapshot.event_flags), cut, surf)
    cache = getattr(nav, 'flight_cache', None)
    if cache and cache[0] == token:
        selected = cache[1]
    else:
        route = nav.regions.route(snapshot, destination, targets, cut=cut, surf=surf)
        choices = []
        if route is not None and len(route) >= 6:
            for index, point in enumerate(data.fly_points):
                mid = point['map']
                if mid == snapshot.map or data.maps[mid]['region'] != current['region'] or not visited & 1 << point['spawn']:
                    continue
                landing = replace(snapshot, map=mid, x=point['x'], y=point['y'])
                remainder = nav.regions.route(landing, destination, targets, cut=cut, surf=surf)
                if remainder is not None and len(remainder) + 4 < len(route):
                    choices.append((len(remainder), index, mid))
        selected = min(choices)[1:] if choices else None
        nav.flight_cache = token, selected
    return Fly(slot, selected[0], snapshot.map, selected[1]) if selected else None
