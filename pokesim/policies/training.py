"""Separate bounded preparation from productive training time, in game frames."""

TRAINING_BUDGET = 180000
TRAINING_LIMIT = 360000
PROJECT_LIMIT = 540000
TRAINING_EXTENSION = 18000
TRAINING_IDLE = 7200
PREPARATION_BUDGET = 36000
PREPARATION_IDLE = 18000


def session(project):
    clock = project.setdefault('training_session', {
        'phase': 'preparation', 'preparation_frames': 0, 'preparation_idle': 0,
        'preparation_since_gain': 0,
        'active_frames': 0, 'active_idle': 0, 'routes': {},
    })
    clock.setdefault('preparation_since_gain', clock['preparation_frames'])
    return clock


def observe(project, delta, remaining, active, gained=False, arrived=False):
    clock = session(project)
    clock['phase'] = 'training' if active else 'preparation'
    if active:
        clock['active_frames'] += delta
        clock['active_idle'] += delta
        remaining -= delta
    else:
        clock['preparation_frames'] += delta
        clock['preparation_since_gain'] += delta
        clock['preparation_idle'] += delta
    if arrived:
        clock['preparation_idle'] = 0
    if gained:
        clock['active_idle'] = clock['preparation_idle'] = 0
        clock['preparation_since_gain'] = 0
        clock['routes'].clear()
        remaining = max(remaining, TRAINING_EXTENSION)
    remaining = min(remaining, max(0, TRAINING_LIMIT - clock['active_frames']))
    reason = None
    if clock['active_frames'] + clock['preparation_frames'] >= PROJECT_LIMIT:
        reason = 'Training project time limit reached'
    elif clock['preparation_since_gain'] >= PREPARATION_BUDGET:
        reason = 'Training preparation budget reached'
    elif not active and clock['preparation_idle'] >= PREPARATION_IDLE:
        reason = 'No training preparation progress in five game minutes'
    elif active and clock['active_idle'] >= TRAINING_IDLE:
        reason = 'No trainee experience gain in two game minutes'
    elif clock['active_frames'] >= TRAINING_LIMIT:
        reason = 'Training session limit reached'
    return remaining, reason


def route_progress(project, goal, endpoint, distance):
    """Credit strictly shorter routes, never coordinate changes or repeated replans."""
    if not project or project['method'] != 'train':
        return
    clock = session(project)
    if clock['phase'] != 'preparation':
        return
    key = ':'.join(str(value) for value in (goal, *endpoint))
    routes = clock['routes']
    previous = routes.get(key)
    if previous is not None and distance < previous:
        clock['preparation_idle'] = 0
    if previous is not None or len(routes) < 16:
        routes[key] = min(distance, previous) if previous is not None else distance


def details(project, remaining):
    if not project or project['method'] != 'train':
        return None
    clock = session(project)
    return {'phase': clock['phase'], 'active_seconds': clock['active_frames'] // 60,
            'preparation_seconds': clock['preparation_frames'] // 60,
            'preparation_remaining_seconds': max(0, PREPARATION_BUDGET - clock['preparation_since_gain']) // 60,
            'remaining_seconds': max(0, remaining) // 60}
