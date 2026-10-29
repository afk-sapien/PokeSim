"""A bounded sightseeing race, measured from ordinary gameplay observations.

One engine runs every course. A course names its checkpoints, how a map is called on the panel and
in the journal, and which maps are Pokémon Centers. Kanto's course is here. Johto's lives with the
rest of Gen II in pokesim.gen2.marathon.
"""
from dataclasses import dataclass
from typing import Callable

from ..strategy_data import MAPS, WORLD
from .progression import Goal


BUDGET = 180000
INTERVAL = 1296000
# Two minutes of game time with no step and no checkpoint ends a race.
IDLE_LIMIT = 7200


@dataclass(frozen=True)
class Course:
    name: str
    points: tuple
    town: Callable[[int], str]
    center: Callable[[int], bool]
    body: str

    @property
    def checkpoints(self):
        return len(self.points) - 1

    @property
    def start(self):
        return self.town(self.points[0][0])


def kanto_town(map_id):
    return WORLD[map_id]['name'].replace('Town', ' Town').replace('City', ' City')


KANTO = Course(
    name='Kanto Marathon',
    points=tuple((MAPS[town], x, y) for town, x, y in (
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
    )),
    town=kanto_town,
    center=lambda map_id: 'Pokecenter' in WORLD.get(map_id, {}).get('name', ''),
    body='Pallet Town to Celadon and back, with 11 checkpoints. '
         'Wild Pokémon have not agreed to stay off the course.')
COURSE = KANTO.points


def candidate():
    return {'method': 'marathon', 'checkpoint': 0, 'race_frames': 0,
            'gains': {'steps': 0, 'battles': 0, 'healing_stops': 0, 'checkpoints': 0}}


def duration(frames):
    seconds = frames // 60
    return f'{seconds // 60}:{seconds % 60:02d}'


def details(records, project, course=KANTO):
    current = None
    if project and project.get('method') == 'marathon':
        current = {'started': project['checkpoint'] > 0,
                   'frames': project['race_frames'],
                   'checkpoints': project['gains']['checkpoints']}
    return {**records, 'current': current, 'total_checkpoints': course.checkpoints, 'name': course.name}


def target(project, course=KANTO):
    return course.points[min(project['checkpoint'], course.checkpoints)]


def objective(project, course=KANTO):
    """The panel line for the race: the way to the start, or the next checkpoint and the clock."""
    index = min(project['checkpoint'], course.checkpoints)
    if index == 0:
        return f'Head to {course.start}. The clock starts at the starting line'
    return (f'{course.town(course.points[index][0])} · Checkpoint {index} of {course.checkpoints} · '
            f'{duration(project["race_frames"])} · {project["gains"]["steps"]:,} recorded steps')


def goal(project):
    return Goal('collect_marathon', KANTO.name, objective(project), (target(project),))


def observe(project, snapshot, delta, previous, overworld, course=KANTO):
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
            center = course.center(snapshot.map)
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
    reached = (overworld and not snapshot.in_battle and not getattr(snapshot, 'textbox', False)
               and not getattr(snapshot, 'start_menu', False)
               and index < len(course.points) and (snapshot.map, snapshot.x, snapshot.y) == course.points[index])
    if reached:
        project['checkpoint'] += 1
        gains['checkpoints'] = max(0, project['checkpoint'] - 1)
    return moved or reached, project['checkpoint'] == len(course.points)


def report(project, finished, course=KANTO):
    gains = project['gains']
    result = 'Finished' if finished else 'Stopped'
    return (f'{result} in {duration(project["race_frames"])} game time. '
            f'{gains["checkpoints"]}/{course.checkpoints} checkpoints, '
            f'{gains["steps"]:,} recorded steps, {gains["battles"]} battles, '
            f'{gains["healing_stops"]} healing stops. '
            + ('The prize is permission to sit down.' if finished else 'The finish line can wait.'))


def start_event(course=KANTO):
    """The journal entry for crossing the starting line."""
    return {'type': 'marathon', 'title': f'The {course.name} is on!', 'body': course.body,
            'priority': 2, 'tags': 'runner'}


def finished_title(course=KANTO):
    """The journal title of a finished race, which the Stats page counts."""
    return f'{course.name} finished!'


def finish(records, project, finished, course=KANTO):
    """Record a race that ended in ``records`` and return its journal entry."""
    previous_best = records.get('best_frames')
    new_best = finished and (previous_best is None or project['race_frames'] < previous_best)
    records['last'] = {
        'finished': finished, 'frames': project['race_frames'], 'personal_best': new_best, **project['gains']}
    if finished:
        records['completed'] = records.get('completed', 0) + 1
        records['best_frames'] = min(records.get('best_frames', project['race_frames']), project['race_frames'])
    text = report(project, finished, course)
    if new_best:
        text += ' First personal best!' if previous_best is None else (
            f' New personal best, {duration(previous_best - project["race_frames"])} faster!')
    return {'type': 'marathon', 'title': finished_title(course) if finished else f'{course.name} called off',
            'body': text, 'priority': 2, 'tags': 'runner'}
