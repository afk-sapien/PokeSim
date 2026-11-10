"""Audit the Gen II map facts the route planners trust, and list every finding the allow list does not cover.

Usage: python tools/map_audit.py <generated Gen II data directory> [gold silver crystal]

Check B covers map links. The map router counts every link as one step between two maps, and the
storage, shop, heal and roamer choices rank places by that count. So a link must join ground a
player can reach on both sides, or one gate room must lead from one map into the other.

Check C covers warps and carpets. A warp must name a real map and warp number, and land on ground.
A carpet with no warp on it is plain ground (#244), so a walk must cross it and step off it in its
own direction.

Each finding that is true of the games today is on ALLOWED with the reason it is there. The audit
fails on a finding that is not on ALLOWED, and on a row of ALLOWED that no longer matches a
finding. It reads generated data only and changes nothing.
"""
import argparse
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace

from pokesim.gen2.data import GameData
from pokesim.gen2.navigation import Navigator
from pokesim.gen2.routes import CARPETS, DIRECTIONS, OPPOSITE, Regions, side_wall

GAMES = ('gold', 'silver', 'crystal')
EVERY = frozenset(GAMES)
CRYSTAL = frozenset({'crystal'})
GOLD_SILVER = frozenset({'gold', 'silver'})
BACK = {'north': 'south', 'south': 'north', 'west': 'east', 'east': 'west'}
DOOR = range(0x60, 0x80)

ICE_PATH = 'Only ground no warp reaches meets at the seam. The walk is Ice Path (#254), and only the heal choice knows (#255).'
ROCK_TUNNEL = 'Only ground no warp reaches meets at the seam. The walk is Rock Tunnel, in the dark.'
ILEX_FOREST = 'No ground meets at the seam. The walk is Ilex Forest and its two gates, past a Cut tree.'
ELEVATOR = 'The elevator lands on the floor picked from its menu.'
LEAGUE = 'An Elite Four door shuts behind the player, so the way back lands on a wall and is never walked.'
BETA = 'An unused map the game never loads.'
MOBILE = 'A Mobile Adapter room. The bot never makes a mobile link.'
TOWER = 'A scripted ride carries the player through the Battle Tower elevator, so no walk lands in it.'

# Every finding true of the games today, as {finding: (games, reason)}. The seams are suspected bugs:
# the map router counts each as one step, so the storage, shop and roamer choices rank the far side
# as next door. Removing a row needs the fix that clears its finding.
ALLOWED = {
    ('seam', 'ROUTE_44', 'east', 'BLACKTHORN_CITY', 'pocket'): (EVERY, ICE_PATH),
    ('seam', 'BLACKTHORN_CITY', 'west', 'ROUTE_44', 'pocket'): (EVERY, ICE_PATH),
    ('seam', 'ROUTE_10_NORTH', 'south', 'ROUTE_10_SOUTH', 'pocket'): (EVERY, ROCK_TUNNEL),
    ('seam', 'ROUTE_10_SOUTH', 'north', 'ROUTE_10_NORTH', 'pocket'): (EVERY, ROCK_TUNNEL),
    ('seam', 'AZALEA_TOWN', 'west', 'ROUTE_34', 'no crossing'): (EVERY, ILEX_FOREST),
    ('seam', 'ROUTE_34', 'east', 'AZALEA_TOWN', 'no crossing'): (EVERY, ILEX_FOREST),
    ('warp', 'GOLDENROD_DEPT_STORE_ELEVATOR', 1, 'dynamic'): (EVERY, ELEVATOR),
    ('warp', 'GOLDENROD_DEPT_STORE_ELEVATOR', 2, 'dynamic'): (EVERY, ELEVATOR),
    ('warp', 'CELADON_DEPT_STORE_ELEVATOR', 1, 'dynamic'): (EVERY, ELEVATOR),
    ('warp', 'CELADON_DEPT_STORE_ELEVATOR', 2, 'dynamic'): (EVERY, ELEVATOR),
    ('warp', 'FAST_SHIP_1F', 1, 'dynamic'): (EVERY, 'The S.S. Aqua docks at Olivine or Vermilion, and its gangway lands at that port.'),
    ('warp', 'POKECENTER_2F', 1, 'dynamic'): (EVERY, 'The stairs lead back down to the Pokémon Center the player came up from.'),
    ('warp', 'KOGAS_ROOM', 1, 'no landing'): (EVERY, LEAGUE),
    ('warp', 'KOGAS_ROOM', 2, 'no landing'): (EVERY, LEAGUE),
    ('warp', 'BRUNOS_ROOM', 1, 'no landing'): (EVERY, LEAGUE),
    ('warp', 'BRUNOS_ROOM', 2, 'no landing'): (EVERY, LEAGUE),
    ('warp', 'KARENS_ROOM', 1, 'no landing'): (EVERY, LEAGUE),
    ('warp', 'KARENS_ROOM', 2, 'no landing'): (EVERY, LEAGUE),
    ('warp', 'LANCES_ROOM', 1, 'no landing'): (GOLD_SILVER, LEAGUE),
    ('warp', 'LANCES_ROOM', 2, 'no landing'): (GOLD_SILVER, LEAGUE),
    ('warp', 'HALL_OF_FAME', 1, 'no landing'): (EVERY, 'The Hall of Fame ends in the credits, and nobody walks back to Lance.'),
    ('warp', 'HALL_OF_FAME', 2, 'no landing'): (EVERY, 'The Hall of Fame ends in the credits, and nobody walks back to Lance.'),
    ('warp', 'OLIVINE_HOUSE_BETA', 1, 'no landing'): (EVERY, BETA),
    ('warp', 'OLIVINE_HOUSE_BETA', 2, 'no landing'): (EVERY, BETA),
    ('warp', 'SAFARI_ZONE_FUCHSIA_GATE_BETA', 2, 'no landing'): (GOLD_SILVER, BETA),
    ('warp', 'SAFARI_ZONE_FUCHSIA_GATE_BETA', 3, 'no landing'): (EVERY, BETA),
    ('warp', 'SAFARI_ZONE_FUCHSIA_GATE_BETA', 4, 'no landing'): (EVERY, BETA),
    ('warp', 'MOBILE_TRADE_ROOM', 1, 'no landing'): (CRYSTAL, MOBILE),
    ('warp', 'MOBILE_TRADE_ROOM', 2, 'no landing'): (CRYSTAL, MOBILE),
    ('warp', 'MOBILE_BATTLE_ROOM', 1, 'no landing'): (CRYSTAL, MOBILE),
    ('warp', 'MOBILE_BATTLE_ROOM', 2, 'no landing'): (CRYSTAL, MOBILE),
    ('warp', 'BATTLE_TOWER_1F', 3, 'no landing'): (CRYSTAL, TOWER),
    ('warp', 'BATTLE_TOWER_HALLWAY', 1, 'no landing'): (CRYSTAL, TOWER),
}


def allowed(game):
    """The allow list for one game, as {finding: reason}."""
    return {key: reason for key, (games, reason) in ALLOWED.items() if game in games}


def reachable(data, regions):
    """Every region a player can reach from a warp, with Cut and Surf.

    Most maps have a walkable ring of tree tops around the edge that no warp opens onto, and the
    rings of two maps often meet across a link. Those rings are left out.
    """
    seeds = {(mid, region) for mid, entry in data.maps.items() for warp in entry['warps']
             for region in regions.memberships(mid, (warp['x'], warp['y']), True, True, arrive=True)}
    seen, queue = set(seeds), deque(seeds)
    while queue:
        for target, _, _ in regions.edges(queue.popleft(), True, True):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def check_seams(data, regions, names):
    """Check B: links whose two sides do not meet on ground a player reaches."""
    reached = reachable(data, regions)
    crossings, rings, rooms = set(), set(), {}
    for mid in data.maps:
        for region in set(regions.regions(mid, True, True).values()):
            node = (mid, region)
            for target, _, kind in regions.edges(node, True, True):
                if kind in BACK and target[0] != mid:
                    (crossings if node in reached else rings).add((mid, kind, target[0]))
                elif kind == 'warp' and node in reached:
                    rooms.setdefault(node, set()).add(target[0])
    found = {}
    for mid, entry in data.maps.items():
        for link in entry['connections']:
            other, direction = link['map'], link['direction']
            key = ('seam', names[mid], direction, names[other])
            if (mid, direction, other) in crossings:
                if (other, BACK[direction], mid) not in crossings:
                    found[key + ('one way',)] = f'nothing walks back {BACK[direction]} from {names[other]}'
                continue
            # A gate room whose one region has doors into both maps is a walk of one room.
            if any(room not in (mid, other) and {mid, other} <= targets for (room, _), targets in rooms.items()):
                continue
            if (mid, direction, other) in rings:
                found[key + ('pocket',)] = 'only ground no warp reaches meets across the link'
            else:
                found[key + ('no crossing',)] = 'no ground meets across the link'
    return found


def check_warps(data, regions, names):
    """Check C, warps: each one names a real map and warp number, and lands on ground."""
    found = {}
    for mid, entry in data.maps.items():
        for number, warp in enumerate(entry['warps'], 1):
            key = ('warp', names[mid], number)
            destination = data.maps.get(warp['map'])
            if destination is None:
                found[key + ('no map',)] = f"leads to map {warp['map']}, which the data does not have"
                continue
            if warp['warp'] == -1:
                found[key + ('dynamic',)] = f"lands where the game chooses in {names[warp['map']]}"
                continue
            if not 1 <= warp['warp'] <= len(destination['warps']):
                found[key + ('no such warp',)] = f"names warp {warp['warp']} of {len(destination['warps'])} in {names[warp['map']]}"
                continue
            if entry['collision'][warp['y'] * entry['width'] + warp['x']] not in DOOR:
                continue
            landing = destination['warps'][warp['warp'] - 1]
            point = (landing['x'], landing['y'])
            if not regions.memberships(warp['map'], point, True, True, arrive=True):
                found[key + ('no landing',)] = f'lands at {point} in {names[warp["map"]]} with no ground to step onto'
    return found


def stand(mid, point):
    return SimpleNamespace(map=mid, x=point[0], y=point[1], objects=(), badges=0, party=(), event_flags=b'', items=())


def check_carpets(data, regions, navigator, names):
    """Check C, carpets: each carpet with no warp is ground a walk crosses and steps off.

    The carpets are listed from ``data``. ``regions`` and ``navigator`` may read another view of
    it, which is how the test rebuilds the facts from before #244.
    """
    found = {}
    for mid, entry in data.maps.items():
        width, height = entry['width'], entry['height']
        doors = {(warp['x'], warp['y']) for warp in entry['warps']}
        labels = regions.regions(mid, False, False)
        for index, tile in enumerate(entry['collision']):
            point = (index % width, index // width)
            button = CARPETS.get(tile)
            if button is None or point in doors:
                continue
            key = ('carpet', names[mid], *point)
            dx, dy = DIRECTIONS[button]
            step = (point[0] + dx, point[1] + dy)
            if point not in labels:
                found[key + ('not ground',)] = 'no region holds it'
            elif not (0 <= step[0] < width and 0 <= step[1] < height):
                found[key + ('faces the edge',)] = f'faces {button} off the map, where the router reads no link'
            elif side_wall(tile, button) or side_wall(entry['collision'][step[1] * width + step[0]], OPPOSITE[button]):
                # Some cave blocks keep a carpet above a wall, and the game never walks off it either.
                continue
            elif step in labels and labels[step] != labels[point]:
                found[key + ('walled in',)] = f'the ground {button} of it is in another region'
            elif step in labels and navigator.local(stand(mid, point), [step]) != [button]:
                found[key + ('no step off',)] = f'a walk does not step {button} off it'
    return found


def audit(data):
    """Every finding for one game, as {finding: detail}."""
    names = {mid: entry['constant'] for mid, entry in data.maps.items()}
    regions = Regions(data)
    return {**check_seams(data, regions, names), **check_warps(data, regions, names),
            **check_carpets(data, regions, Navigator(data), names)}


def problems(game, findings, allow=None):
    """Findings the allow list does not cover, and allow rows that match no finding."""
    allow = allowed(game) if allow is None else allow
    new = {key: detail for key, detail in findings.items() if key not in allow}
    stale = sorted(key for key in allow if key not in findings)
    return new, stale


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('data', type=Path, help='generated Gen II data directory')
    parser.add_argument('games', nargs='*', default=list(GAMES))
    parser.add_argument('--all', action='store_true', help='also print the findings the allow list covers')
    args = parser.parse_args()
    failed = False
    for game in args.games:
        findings = audit(GameData.load(args.data, game))
        new, stale = problems(game, findings)
        print(f'{game}: {len(findings)} findings, {len(new)} not allowed, {len(stale)} stale allow rows')
        for key, detail in sorted(findings.items(), key=lambda item: str(item[0])):
            if key in new or args.all:
                print(f"  {'NEW' if key in new else 'allowed'} {key}: {detail}")
        for key in stale:
            print(f'  STALE {key}')
        failed |= bool(new or stale)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
