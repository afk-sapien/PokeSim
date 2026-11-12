"""Audit the map facts the route planners trust, and list every finding the allow list does not cover.

Usage: python tools/map_audit.py <generated Gen II data directory> [gold silver crystal]
       python tools/map_audit.py --gen1    (Red and Blue, or Yellow with POKESIM_GEN1_VARIANT=yellow)

Check B covers map links. The walk router counts a link as one step between two maps, and the
storage, shop, heal, roamer, postgame and collection choices rank places by that count. So each
link it counts must join ground a player can reach on both sides, or one gate room must lead from
one map into the other.

Check C covers warps and carpets. A warp must name a real map and warp number, and land on ground.
A carpet with no warp on it is plain ground (#244), so a walk must cross it and step off it in its
own direction.

Check D covers crossings. A walk crosses a map from the map before it to the map after it only
with the field moves that join the ground it lands on to the ground it leaves from, so before Cut
no walk goes through Ilex Forest. For each crossing that needs a field move, a walk with each set
of moves that does not join it must take no crossing those moves do not join.

Check E covers the story manifests in pokesim/story. It walks the rows in play order, holding the
game the rows before leave. The story code must offer each row in turn, the row's place must be
reachable from the row before, and after each badge a Pokémon Center must be reachable from every
town and route the story walked. Gold, Silver and Crystal run it with the other checks. Gen I runs it
with --gen1, for the variant the process loads. In Gold, Silver and Crystal it also checks that the
Fly points the policy may pick from a town or route are the ones the cartridge's Fly map lists there,
which are only those of the region the player stands in (#124).

Each finding that is true of the games today is on ALLOWED with the reason it is there. The audit
fails on a finding that is not on ALLOWED, and on a row of ALLOWED that no longer matches a
finding. It reads generated data only and changes nothing.
"""
import argparse
import itertools
import sys
from pathlib import Path
from types import SimpleNamespace

from pokesim.gen2.data import GameData
from pokesim.gen2.navigation import Navigator
from pokesim.gen2.routes import (CARPETS, DIRECTIONS, FIELD_MOVES, OPPOSITE, WALKED, Regions, link_walks,
                                 side_wall, walk_crossings)

GAMES = ('gold', 'silver', 'crystal')
EVERY = frozenset(GAMES)
CRYSTAL = frozenset({'crystal'})
GOLD_SILVER = frozenset({'gold', 'silver'})
DOOR = range(0x60, 0x80)
SEAMS = {'pocket': 'only ground no warp reaches meets across the link',
         'no crossing': 'no ground meets across the link'}

ELEVATOR = 'The elevator lands on the floor picked from its menu.'
LEAGUE = 'An Elite Four door shuts behind the player, so the way back lands on a wall and is never walked.'
BETA = 'An unused map the game never loads.'
MOBILE = 'A Mobile Adapter room. The bot never makes a mobile link.'
TOWER = 'A scripted ride carries the player through the Battle Tower elevator, so no walk lands in it.'

# Every finding true of the games today, as {finding: (games, reason)}. Removing a row needs the fix
# that clears its finding. No seam is on it: the walk router skips the links Route 44 and Blackthorn
# City, the two halves of Route 10 and Azalea Town and Route 34 share, so a walk goes through Ice
# Path, Rock Tunnel and Ilex Forest.
ALLOWED = {
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


def check_seams(data, regions, navigator, names, walk=True):
    """Check B: links the walk router counts whose two sides do not meet on ground a player reaches.

    ``walk=False`` checks every link the plain router counts, as the walk router did before it
    skipped the seams.
    """
    counted = {(mid, kind, destination) for mid in data.maps
               for destination, _, kind in navigator.steps(mid, walk) if kind != 'warp'}
    return {('seam', names[mid], direction, names[other], kind): SEAMS[kind]
            for (mid, direction, other), kind in link_walks(data, regions).items()
            if kind not in WALKED and (mid, direction, other) in counted}


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


# The badge and move number each field move needs.
HMS = {'cut': (2, 15), 'surf': (8, 57)}


def player(mid, moves):
    """A player on mid who can use ``moves``, with the badge and a party member for each."""
    party = (SimpleNamespace(moves=tuple(HMS[move][1] for move in moves)),)
    return SimpleNamespace(map=mid, badges=sum(HMS[move][0] for move in moves), party=party)


def check_crossings(data, navigator, names):
    """Check D: a walk takes no crossing the player's field moves do not join."""
    needs = walk_crossings(data)
    found = {}
    for previous, _, following in needs:
        for moves in FIELD_MOVES:
            for (before, here, _, _), (_, after, _, _) in itertools.pairwise(
                    navigator.walk(player(previous, moves), following) or ()):
                alternatives = needs.get((before, here, after))
                if alternatives and not any(need <= moves for need in alternatives):
                    have = '+'.join(sorted(moves)) or 'no moves'
                    need = ' or '.join('+'.join(sorted(one)) for one in alternatives)
                    found[('crossing', names[before], names[here], names[after], have)] = f'a walk crosses with {have} and needs {need}'
    return found


def gen1_state(rows, done):
    """The Red, Blue or Yellow game a player holds once the story rows in ``done`` are done.

    Every object the game can hide is hidden, except one that a row not done yet names in its
    done_when, such as the Snorlax on Route 12. So check E checks walls, warps, gates and lifts,
    not the people a script moves.
    """
    from pokesim.ram import PartyMon
    from pokesim.strategy_data import DATA, EVENTS, ITEMS, MAPS
    flags, items, moves = bytearray(320), [], []
    badges, party, saffron = 0, False, False
    for row in done:
        facts = row['done_when']
        for flag in facts.get('flags', ()):
            index = EVENTS[fill_choices(flag)]
            flags[index // 8] |= 1 << index % 8
        items = [item for item in items + [ITEMS[name] for name in facts.get('items', ())]
                 if item not in {ITEMS[name] for name in facts.get('drop', ())}]
        moves += facts.get('moves', [])
        badges |= facts.get('badges', 0)
        party = party or facts.get('party', False)
        saffron = saffron or facts.get('saffron', False)
    toggles = DATA['toggle_objects']
    hidden = bytearray([0xFF] * ((len(toggles) + 7) // 8))
    for row in rows:
        if not any(row is finished for finished in done):
            for name, number in row['done_when'].get('hidden', ()):
                index = toggles.index([MAPS[name], number])
                hidden[index // 8] &= ~(1 << index % 8)
    mon = PartyMon(0x99, 20, 20, 50, 'PARTNER', moves=tuple(moves[:4]) or (33,))
    return dict(badges=badges, event_flags=bytes(flags), items=tuple((item, 1) for item in items),
                party=(mon,) if party else (), saffron_open=saffron, hidden_objects=bytes(hidden))


# The run's choices that fill "{starter}" and "{fossil}" in a story row.
CHOICES = {'starter': 'BULBASAUR', 'fossil': 'HELIX_FOSSIL'}


def fill_choices(text):
    from pokesim import story
    return story.fill(text, **CHOICES)


def gen1_goal(row):
    """The goal a Gen I story row asks for, with an empty title."""
    from pokesim.policies.progression import GYMS, at, object_goal
    if row.get('gym'):
        _, key, _, gym, trainer, *_ = next(gym for gym in GYMS if gym[1] == row['key'])
        return object_goal(key, '', '', gym, trainer)
    if 'object' in row:
        return object_goal(row['key'], '', '', row['map'], fill_choices(row['object']))
    return at(row['key'], '', '', row['map'], row['x'], row['y'])


def where(row):
    """A short name for a story row, which tells apart the rows one key holds."""
    if row.get('gym'):
        return 'gym'
    if 'points' in row:
        return f"{len(row['points'])} points"
    return row.get('object') or f"{row['x']},{row['y']}"


# A route between two story steps may cross much of Kanto, so it may search past the walk limit.
STORY_LIMIT = 400000


def gen1_snapshot(position, state):
    from pokesim.ram import Snapshot
    return Snapshot(frame=0, map=position[0], x=position[1], y=position[2], owned=frozenset(), seen=frozenset(),
                    money=0, in_battle=0, battle_type=0, enemy_species=0, enemy_level=0, opponent=0,
                    player_name='RED', rival_name='BLUE', playtime=(0, 0, 0), textbox=False, start_menu=False, **state)


# The tilesets of Kanto's towns and routes.
OUTDOOR = frozenset({'OVERWORLD', 'PLATEAU'})


def check_centers_gen1(navigator, snapshot, walked, badge, names):
    """After a badge, a Pokémon Center is reachable from each town and route the story walked."""
    from pokesim.policies.progression import healing_goal
    nav = navigator()
    nav.update_story(snapshot)
    centers = frozenset(healing_goal(snapshot).targets)
    found = {}
    for mid, tile in walked.items():
        if tile not in centers and nav.route(tile, centers, 0, limit=STORY_LIMIT) is None:
            found[('center', badge, names[mid])] = f'no Pokémon Center is reachable from {names[mid]} {tile[1:]}'
    return found


def check_story_gen1(navigator=None, rows=None):
    """Check E for Red, Blue or Yellow, whichever Gen I data this process loaded.

    Each story row's place must be reachable from the place of the row before, with the game the
    rows before it leave. The story code must offer each row in turn, at the row's own place. After
    each badge, a Pokémon Center must be reachable from every town and route the story walked.
    ``navigator`` and ``rows`` replace the Navigator class and the manifest rows, for tests.
    """
    from pokesim import story
    from pokesim.policies.navigation import Navigator
    from pokesim.policies.progression import GAME, story_goal
    from pokesim.strategy_data import MAPS, WORLD
    navigator = navigator or Navigator
    names = {mid: name for name, mid in MAPS.items()}
    rows = story.steps(1, GAME) if rows is None else rows
    first = story.start(1)
    position = (MAPS[first['map']], first['x'], first['y'])
    found, done, walked = {}, [], {}
    for row in rows:
        snapshot = gen1_snapshot(position, gen1_state(rows, done))
        goal, wanted = story_goal(snapshot, CHOICES['starter'].lower(), CHOICES['fossil']), gen1_goal(row)
        if (goal.key, goal.targets) != (row['key'], wanted.targets):
            found[('story', row['key'], where(row), 'not offered')] = f'the story offers {goal.key} here'
        legs, targets = [], wanted.targets
        if 'arrive' in row:
            arrive, mid = row['arrive'], MAPS[row['map']]
            legs.append((position, ((mid, arrive['x'], arrive['y']),)))
            position = (mid, arrive['then']['x'], arrive['then']['y'])
        legs.append((position, targets))
        nav = navigator()
        nav.update_story(snapshot)
        for start, goals in legs:
            position = start
            if start in goals:
                continue
            if nav.route(start, goals, 0, limit=STORY_LIMIT) is None:
                found[('story', row['key'], where(row), 'no route')] = f'no route from {names[start[0]]} {start[1:]}'
                position = goals[0]
                break
            for _, _, tile in nav.path:
                if WORLD[tile[0]]['tileset'] in OUTDOOR:
                    walked.setdefault(tile[0], tile)
            position = nav.path[-1][2]
        if 'then' in row:
            position = (MAPS[row['then']['map']], row['then']['x'], row['then']['y'])
        done.append(row)
        if 'badges' in row['done_when']:
            after = gen1_snapshot(position, gen1_state(rows, done))
            found.update(check_centers_gen1(navigator, after, walked, row['key'], names))
    return found


# The starter check E plays in Gold, Silver and Crystal, and the partner beside it. The partner can learn
# Surf, Whirlpool and Waterfall, so the story never sends the run to find one that can.
GEN2_STARTER = 'totodile'
GEN2_STARTERS = ('cyndaquil', 'totodile', 'chikorita')
GEN2_PARTNER = 'GYARADOS'
# A dozen Full Restores, so the Red row is not set aside to win money for potions.
GEN2_BAG = (('FULL_RESTORE', 12),)


def gen2_state(data, done):
    """The Gold, Silver or Crystal game a player holds once the story rows in ``done`` are done.

    Every row sets its done_when flags and clears its "clear" flags, on top of the flags the start
    row of gen2.json sets. Badges, Pokégear cards, Hall of Fame entries and field moves add up.
    """
    from pokesim import story
    flags = bytearray(max(data.events.values()) // 8 + 1)

    def mark(names, on):
        for name in names:
            index = data.events[name]
            if on:
                flags[index // 8] |= 1 << index % 8
            else:
                flags[index // 8] &= ~(1 << index % 8)

    mark(story.start(2).get('flags', ()), True)
    badges = hall_of_fame = pokegear = 0
    moves, party = [], False
    for row in done:
        facts = row['done_when']
        mark(facts.get('flags', ()), True)
        mark(facts.get('clear', ()), False)
        badges |= facts.get('badges', 0)
        hall_of_fame = max(hall_of_fame, facts.get('hall_of_fame', 0))
        pokegear |= facts.get('pokegear', 0)
        moves += facts.get('moves', [])
        party = party or facts.get('party', False)
    return dict(event_flags=bytes(flags), badges=badges, hall_of_fame_count=hall_of_fame, pokegear=pokegear,
                moves=tuple(moves), party=party)


def gen2_snapshot(data, position, state, frame=0):
    """A Gen II snapshot at ``position`` holding ``state``, with the starter and its partner in the party.

    The starter knows the field moves the story taught so far.
    """
    from pokecore.gen2.ram import Mon, Snapshot

    def mon(name, moves):
        species = next(sid for sid, entry in data.species.items() if entry['constant'] == name)
        return Mon(species, name, 50, 150, 150, 0, 0, moves, (20,) * len(moves), (20,) * len(moves),
                   (150,) * 6, 125000, (15,) * 4, (0,) * 5, 1, 70, data=data)

    party = ()
    if state['party']:
        party = (mon(GEN2_STARTER.upper(), state['moves'] or (10,)), mon(GEN2_PARTNER, (33,)))
    items = tuple((data.items[name], count) for name, count in GEN2_BAG)
    pockets = {'items': items, 'balls': (), 'key': (), 'machines': ()}
    return Snapshot(frame=frame, map=position[0], x=position[1], y=position[2], player_name='GOLD',
                    rival_name='SILVER', party=party, stored=(), box_counts=(0,) * 14, active_box=0,
                    owned=frozenset(), seen=frozenset(), badges=state['badges'], items=items, pockets=pockets,
                    money=0, coins=0, in_battle=0, enemy_species=0, enemy_level=0, enemy_hp=0, enemy_max_hp=0,
                    trainer_class=0, battle_type=0, playtime=(0, 0, 0),
                    hall_of_fame_count=state['hall_of_fame_count'], event_flags=state['event_flags'],
                    tiles=('',) * 18, objects=(), valid=True, data=data,
                    # Crystal keeps the Farfetch'd's place in memory, here still at its first spot.
                    farfetchd_position=0 if 'wFarfetchdPosition' in data.symbols else None)


class Gen2Memory:
    """The bytes the Gen II story code reads from memory: the Pokégear cards."""
    memory = None

    def __init__(self, pokegear):
        self.pokegear = pokegear

    def byte(self, name):
        return self.pokegear if name == 'wPokegearFlags' else 0


def gen2_goal(policy, snapshot, row):
    """The goal a Gen II story row asks for, with an empty title. A row of points asks for its first."""
    if 'points' in row:
        x, y, face = row['points'][0]
        row = dict(row, x=x, y=y, face=face)
        return policy.story_step(snapshot, f"{row['key']}_1", '', row)
    return policy.story_step(snapshot, row['key'], '', row)


def gen2_place(goal):
    return None if goal is None else (goal.key, goal.map_name, goal.x, goal.y, goal.face)


def ground(regions, mid, region, cut, surf):
    """A tile of ``region`` on map ``mid``, which stands for the region once the labels change."""
    return min(point for point, label in regions.regions(mid, cut, surf).items() if label == region)


def check_centers_gen2(data, regions, snapshot, walked, badge, names):
    """After a badge, a Pokémon Center is reachable from each town and route the story walked."""
    from collections import deque
    from pokesim.gen2.navigation import field_moves
    moves = field_moves(snapshot)
    cut, surf = 'cut' in moves, 'surf' in moves
    found = {}
    for mid, point in walked.items():
        seen = {(mid, region) for region in regions.memberships(mid, point, cut, surf, arrive=True)}
        queue = deque(seen)
        while queue:
            node = queue.popleft()
            if names[node[0]].endswith('POKECENTER_1F'):
                break
            for destination, _, _ in regions.edges(node, cut, surf):
                if destination not in seen:
                    seen.add(destination)
                    queue.append(destination)
        else:
            found[('center', badge, names[mid])] = f'no Pokémon Center is reachable from {names[mid]} {point}'
    return found


def check_flight(data, names, destinations=None):
    """The Fly points the policy may pick from each town and route are the ones the Fly map lists (#124).

    The cartridge picks Kanto's map when the landmark of the player's map is Pallet Town's or later
    and the Indigo Plateau spawn on Route 23 is visited, and Johto's map otherwise, so no flight
    crosses between the regions. The check runs with every spawn visited, then with every spawn but
    Indigo Plateau's, as on Route 26 and 27 before the first League visit. ``destinations``
    replaces the policy's list, for tests.
    """
    from pokecore.gen2.maps import OUTSIDE
    from pokesim.gen2 import flight
    destinations = destinations or flight.destinations
    pallet = data.maps[data.map_ids['PALLET_TOWN']]['landmark']
    indigo = next(point['spawn'] for point in data.fly_points if point['map'] == data.map_ids['ROUTE_23'])

    def region(mid, visited=1 << indigo):
        return 'kanto' if data.maps[mid]['landmark'] >= pallet and visited & 1 << indigo else 'johto'

    every = (1 << 8 * 4) - 1
    found = {}
    for visited, when in ((every, ''), (every & ~(1 << indigo), ' before Indigo Plateau')):
        for mid, entry in data.maps.items():
            if entry['environment'] not in OUTSIDE:
                continue
            listed = {point['map'] for _, point in destinations(data, mid, visited)}
            shown = {point['map'] for point in data.fly_points
                     if region(point['map']) == region(mid, visited) and visited & 1 << point['spawn']}
            for point in sorted(listed - shown):
                found[('fly', names[mid], names[point], 'crosses regions' + when)] = (
                    f'the Fly map on {names[mid]} shows {region(mid, visited).title()}{when}, not {names[point]}')
            for point in sorted(shown - listed):
                found[('fly', names[mid], names[point], 'not listed' + when)] = (
                    f'the Fly map on {names[mid]} shows {names[point]}{when}, which the policy never picks')
    return found


def check_story_gen2(data, rows=None):
    """Check E for one of Gold, Silver and Crystal.

    Each story row's place must be reachable from the place of the row before, with the game the
    rows before it leave. The story code must offer each row in turn, at the row's own place. After
    each badge, a Pokémon Center must be reachable from every town and route the story walked. A
    row for another starter is checked with a policy that chose it, and the walk goes on without it.
    ``rows`` replaces the manifest rows, for tests.
    """
    from pokesim import story
    from pokesim.gen2.navigation import field_moves
    from pokesim.gen2.policy import Policy
    names = {mid: entry['constant'] for mid, entry in data.maps.items()}
    rows = story.steps(2, data.game) if rows is None else rows
    regions = Regions(data)
    policies = {starter: Policy(data, seed=1, starter=starter) for starter in GEN2_STARTERS}
    for policy in policies.values():
        # The story picks approach tiles with the regions of its navigator, so it sees the same doors.
        policy.nav.regions = regions
    first = story.start(2)
    position = (data.map_ids[first['map']], first['x'], first['y'])
    found, done, walked = {}, [], {}
    before = None
    for frame, row in enumerate(rows):
        if before is None or before[0] != row['key']:
            # Rows that share a key are choices, such as the three starters, and are checked in one state.
            state = gen2_state(data, done)
            before = (row['key'], gen2_snapshot(data, position, state, frame), state)
        _, snapshot, state = before
        observe_gen2(data, regions, snapshot)
        policy = policies[row.get('starter', GEN2_STARTER)]
        goal, wanted = policy.story(snapshot, Gen2Memory(state['pokegear'])), gen2_goal(policy, snapshot, row)
        if gen2_place(goal) != gen2_place(wanted):
            found[('story', row['key'], where(row), 'not offered')] = f'the story offers {goal and goal.key} here'
        if policy is not policies[GEN2_STARTER]:
            continue
        moves = field_moves(snapshot)
        cut, surf = 'cut' in moves, 'surf' in moves
        target = data.map_ids[wanted.map_name]
        start = SimpleNamespace(map=position[0], x=position[1], y=position[2])
        path = regions.route(start, target, [(wanted.x, wanted.y)], cut=cut, surf=surf)
        if path is None:
            found[('story', row['key'], where(row), 'no route')] = f'no route from {names[position[0]]} {position[1:]}'
        for _, (mid, region), _, _ in path or ():
            if mid not in walked and data.maps[mid]['environment'] in OUTDOOR_GEN2:
                walked[mid] = ground(regions, mid, region, cut, surf)
        position = (target, wanted.x, wanted.y)
        if 'then' in row:
            position = (data.map_ids[row['then']['map']], row['then']['x'], row['then']['y'])
        done.append(row)
        if 'badges' in row['done_when']:
            after = gen2_snapshot(data, position, gen2_state(data, done))
            observe_gen2(data, regions, after)
            found.update(check_centers_gen2(data, regions, after, walked, row['key'], names))
    return found


def observe_gen2(data, regions, snapshot):
    """Show ``regions`` the doors and walls the event flags of ``snapshot`` draw, and the objects on ice."""
    from dataclasses import replace
    from pokecore.gen2.maps import event_changes, ice_solids
    away = replace(snapshot, map=-1)
    for mid, grid in event_changes(data, away).items():
        regions.observe(mid, grid)
    for mid in regions.ice_maps:
        regions.observe_solids(mid, ice_solids(data, away, mid))


# The environments of Johto's and Kanto's towns and routes.
OUTDOOR_GEN2 = frozenset({'TOWN', 'ROUTE'})


def audit(data):
    """Every finding for one game, as {finding: detail}."""
    names = {mid: entry['constant'] for mid, entry in data.maps.items()}
    regions, navigator = Regions(data), Navigator(data)
    return {**check_seams(data, regions, navigator, names), **check_warps(data, regions, names),
            **check_carpets(data, regions, navigator, names), **check_crossings(data, navigator, names),
            **check_story_gen2(data), **check_flight(data, names)}


def problems(game, findings, allow=None):
    """Findings the allow list does not cover, and allow rows that match no finding."""
    allow = allowed(game) if allow is None else allow
    new = {key: detail for key, detail in findings.items() if key not in allow}
    stale = sorted(key for key in allow if key not in findings)
    return new, stale


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('data', type=Path, nargs='?', help='generated Gen II data directory')
    parser.add_argument('games', nargs='*', default=list(GAMES))
    parser.add_argument('--all', action='store_true', help='also print the findings the allow list covers')
    parser.add_argument('--gen1', action='store_true', help='run check E on the Gen I variant this process loads')
    args = parser.parse_args()
    if args.gen1:
        from pokesim.policies.progression import GAME
        findings = check_story_gen1()
        print(f'{GAME}: {len(findings)} findings')
        for key, detail in findings.items():
            print(f'  NEW {key}: {detail}')
        return 1 if findings else 0
    if args.data is None:
        parser.error('give the generated Gen II data directory, or --gen1')
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
