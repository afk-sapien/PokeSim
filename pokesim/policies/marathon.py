"""A bounded sightseeing race, measured from ordinary gameplay observations."""
from ..strategy_data import MAPS, WORLD
from .progression import Goal


BUDGET = 180000
INTERVAL = 1296000
COURSE = tuple((MAPS[town], x, y) for town, x, y in (
    ('PALLET_TOWN', 9, 9),
    ('VIRIDIAN_CITY', 20, 18),
    ('PEWTER_CITY', 20, 18),
    ('VERMILION_CITY', 20, 18),
    ('LAVENDER_TOWN', 10, 9),
    ('SAFFRON_CITY', 20, 22),
    ('CELADON_CITY', 41, 10),
    ('SAFFRON_CITY', 20, 22),
    ('VERMILION_CITY', 20, 18),
    ('PEWTER_CITY', 20, 18),
    ('VIRIDIAN_CITY', 20, 18),
    ('PALLET_TOWN', 9, 9),
))


def candidate():
    return {'method': 'marathon', 'checkpoint': 0, 'race_frames': 0,
            'gains': {'steps': 0, 'battles': 0, 'healing_stops': 0, 'checkpoints': 0}}


def duration(frames):
    seconds = frames // 60
    return f'{seconds // 60}:{seconds % 60:02d}'


def details(records, project):
    current = None
    if project and project.get('method') == 'marathon':
        current = {'started': project['checkpoint'] > 0,
                   'frames': project['race_frames'],
                   'checkpoints': project['gains']['checkpoints']}
    return {**records, 'current': current, 'total_checkpoints': len(COURSE) - 1}


def goal(project):
    index = min(project['checkpoint'], len(COURSE) - 1)
    target = COURSE[index]
    town = WORLD[target[0]]['name'].replace('Town', ' Town').replace('City', ' City')
    if index == 0:
        return Goal('collect_marathon', 'Kanto Marathon',
                    'Head to Pallet Town. The clock starts at the starting line', (target,))
    return Goal('collect_marathon', 'Kanto Marathon',
                f'{town} · Checkpoint {index} of {len(COURSE) - 1} · '
                f'{duration(project["race_frames"])} · {project["gains"]["steps"]:,} recorded steps', (target,))


def observe(project, snapshot, delta, previous, overworld):
    """Count verified adjacent movement only. Warps and gaps never invent distance."""
    if not snapshot.valid:
        return False, False
    index = project['checkpoint']
    running = index > 0
    gains = project['gains']
    moved = False
    if running:
        project['race_frames'] += delta
        if previous and 0 < snapshot.frame - previous.frame <= 120:
            moved = (overworld and not previous.in_battle and not snapshot.in_battle
                     and previous.map == snapshot.map
                     and abs(previous.x - snapshot.x) + abs(previous.y - snapshot.y) == 1)
            gains['steps'] += int(moved)
            if not previous.in_battle and snapshot.in_battle:
                gains['battles'] += 1
            center = 'Pokecenter' in WORLD.get(snapshot.map, {}).get('name', '')
            if not center:
                project.pop('healed_here', None)
            if center and previous.map == snapshot.map and not snapshot.in_battle and not project.get('healed_here'):
                before = [(m.species, m.nick, m.trainer_id, m.dvs) for m in previous.party]
                after = [(m.species, m.nick, m.trainer_id, m.dvs) for m in snapshot.party]
                restored = any(b.hp > a.hp or a.status and not b.status or sum(b.pp) > sum(a.pp)
                               for a, b in zip(previous.party, snapshot.party))
                if before == after and restored:
                    gains['healing_stops'] += 1
                    project['healed_here'] = True
    reached = (overworld and not snapshot.in_battle and not snapshot.textbox and not snapshot.start_menu
               and index < len(COURSE) and (snapshot.map, snapshot.x, snapshot.y) == COURSE[index])
    if reached:
        project['checkpoint'] += 1
        gains['checkpoints'] = max(0, project['checkpoint'] - 1)
    return moved or reached, project['checkpoint'] == len(COURSE)


def report(project, finished):
    gains = project['gains']
    result = 'Finished' if finished else 'Stopped'
    return (f'{result} in {duration(project["race_frames"])} game time. '
            f'{gains["checkpoints"]}/{len(COURSE) - 1} checkpoints, '
            f'{gains["steps"]:,} recorded steps, {gains["battles"]} battles, '
            f'{gains["healing_stops"]} healing stops. '
            + ('The prize is permission to sit down.' if finished else 'The finish line can wait.'))
