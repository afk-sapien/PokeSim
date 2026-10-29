"""The Johto Marathon, run on the same engine as Kanto's from pokesim.policies.marathon.

The course runs from New Bark Town out to Ecruteak City and back, by land only. Each checkpoint is the
tile below a Pokémon Center door, or below Elm's Lab door in New Bark Town:

New Bark, Cherrygrove, Violet, Azalea, Goldenrod, Ecruteak, then the same towns back.

A twelve checkpoint course out to Olivine took 134,000 to 164,000 frames in the replay batch, with
two of five races stopped by the 180,000 frame budget at the last checkpoint. Turning at Ecruteak
drops Routes 38 and 39 both ways, so a race fits the budget with room for the way to the start.

Every leg walks both ways without Surf and without a one-way ledge in its way. Ilex Forest needs Cut
and Route 36 needs Sudowoodo out of the way, so a race waits for both. Neither Fly nor Surf is used past the
starting line. The untimed way to New Bark Town may use both, which a player in Kanto needs.
"""
from ..policies import marathon as engine

NAME = 'Johto Marathon'
# Towns in course order, out and back, with the tile the runner stands on.
TOWNS = (
    ('NEW_BARK_TOWN', 6, 4),
    ('CHERRYGROVE_CITY', 29, 4),
    ('VIOLET_CITY', 31, 26),
    ('AZALEA_TOWN', 15, 10),
    ('GOLDENROD_CITY', 15, 28),
    ('ECRUTEAK_CITY', 23, 28),
    ('GOLDENROD_CITY', 15, 28),
    ('AZALEA_TOWN', 15, 10),
    ('VIOLET_CITY', 31, 26),
    ('CHERRYGROVE_CITY', 29, 4),
    ('NEW_BARK_TOWN', 6, 4),
)
# Activities the postgame rotation finishes before the first race, as Gen I waits for four projects.
PROJECTS = 4


def course(data):
    """The course with this cartridge's map ids, built once per game."""
    cached = getattr(data, 'johto_marathon', None)
    if cached is None:
        cached = data.johto_marathon = _course(data)
    return cached


def _course(data):
    maps = data.maps
    return engine.Course(
        name=NAME,
        points=tuple((data.map_ids[town], x, y) for town, x, y in TOWNS),
        town=lambda map_id: maps[map_id]['name'],
        center=lambda map_id: maps.get(map_id, {}).get('constant', '').endswith('POKECENTER_1F'),
        body='New Bark Town to Ecruteak and back, with 10 checkpoints. '
             'Wild Pokémon have not agreed to stay off the course.')


def records(policy):
    return policy.collection.setdefault('marathon', {'records': {}, 'next': 0})


def can_cut(snapshot):
    return bool(snapshot.badges & 2) and any(15 in mon.moves for mon in snapshot.party if not mon.egg)


def sudowoodo_cleared(snapshot):
    # The fought flag alone is not enough, since a returned Sudowoodo stands on Route 36 again until
    # its sprite is hidden once more.
    return snapshot.event('EVENT_FOUGHT_SUDOWOODO') and snapshot.event('EVENT_ROUTE_36_SUDOWOODO')


def eligible(policy, snapshot, finished):
    """Whether a race may start now: Champion, four postgame projects done, Cut, a clear Route 36 and no cooldown."""
    return ('champion' in policy.completed and finished >= PROJECTS and can_cut(snapshot)
            and sudowoodo_cleared(snapshot) and snapshot.frame >= records(policy).get('next', 0))


def candidate(snapshot):
    return {'kind': 'marathon', **engine.candidate(), 'started_frame': snapshot.frame, 'progress_frame': snapshot.frame}


def racing(policy):
    """True once the runner is past the starting line, where the clock runs and the course is on foot."""
    activity = (policy.collection.get('postgame') or {}).get('activity')
    return bool(activity and activity['kind'] == 'marathon' and activity['checkpoint'] > 0)


def observe(policy, snapshot, activity):
    """Run the race clock and the checkpoints on every step, as Gen I's collection observer does."""
    previous = getattr(policy, 'marathon_previous', None)
    delta = max(0, snapshot.frame - previous.frame) if previous is not None else 0
    before = activity['checkpoint']
    overworld = policy.menu is None
    progressed, _ = engine.observe(activity, snapshot, delta, previous, overworld, course(policy.data))
    policy.marathon_previous = snapshot if snapshot.valid else None
    # Battle time is not time lost wandering, so it never counts toward the idle limit, and neither does
    # a menu the planner is working through, such as a team change at a Pokémon Center. Any change of
    # tile counts as movement, so the walk to the starting line and warps between maps are not idle.
    walked = previous is not None and (previous.map, previous.x, previous.y) != (snapshot.map, snapshot.x, snapshot.y)
    if progressed or walked or snapshot.in_battle or not overworld:
        activity['progress_frame'] = snapshot.frame
    if before == 0 and activity['checkpoint'] == 1:
        events(policy).append(engine.start_event(course(policy.data)))


def done(policy, snapshot, activity):
    """A race ends at the finish line, at its 50 minute budget or after two idle minutes."""
    return (activity['checkpoint'] == len(course(policy.data).points)
            or snapshot.frame - activity['started_frame'] >= engine.BUDGET
            or snapshot.frame - activity['progress_frame'] >= engine.IDLE_LIMIT)


def finish(policy, activity):
    data = records(policy)
    finished = activity['checkpoint'] == len(course(policy.data).points)
    events(policy).append(engine.finish(data['records'], activity, finished, course(policy.data)))
    previous = getattr(policy, 'marathon_previous', None)
    data['next'] = (previous.frame if previous is not None else activity['started_frame']) + engine.INTERVAL
    policy.marathon_previous = None


def events(policy):
    """Journal entries waiting for the emulator, which adds a screenshot to each."""
    if not hasattr(policy, 'marathon_events'):
        policy.marathon_events = []
    return policy.marathon_events


def take_events(policy):
    taken, policy.marathon_events = events(policy), []
    return taken


def goal(policy, activity, Goal):
    town, x, y = engine.target(activity, course(policy.data))
    label = f'{NAME} · {engine.objective(activity, course(policy.data))}'
    return Goal('collection_marathon', label, policy.data.maps[town]['constant'], x, y)


def details(policy):
    activity = (policy.collection.get('postgame') or {}).get('activity')
    project = {**activity, 'method': 'marathon'} if activity and activity['kind'] == 'marathon' else None
    return engine.details(records(policy)['records'], project, course(policy.data))
