"""Earn Sun Stones through the native Bug-Catching Contest."""
from .menus import choose
from .ram import Memory


def score(mem, prefix):
    if not mem.byte(prefix + 'Species'):
        return 0
    first, second = mem.read(prefix + 'DVs', 2)
    bonus = ((second >> 4) & 2) // 2 + (second & 2) * 2 + ((first >> 4) & 2) * 4 + (first & 2) * 8
    return (mem.word(prefix + 'MaxHP') * 4 + sum(mem.word(prefix + stat)
            for stat in ('Attack', 'Defense', 'Speed', 'SpclAtk', 'SpclDef'))
            + bonus + mem.word(prefix + 'HP') // 8 + bool(mem.byte(prefix + 'Item')))


# The contest runs on Tuesday, Thursday and Saturday by the cartridge clock (wCurDay counts from Sunday).
# That clock follows wall time, not simulation speed, so a skipped day can be days of real time away.
CONTEST_DAYS = (2, 4, 6)


def needs_sun_stone(policy, snapshot):
    return len({182, 192} - snapshot.owned) > dict(snapshot.items).get(policy.data.items['SUN_STONE'], 0)


def waiting_for_day(policy, snapshot, mem):
    """Why the Sun Stone work is idle, in words for the status line, or None when it is not waiting."""
    if not needs_sun_stone(policy, snapshot) or policy.collection.get('contest') or policy.collection.get('tower'):
        return None
    if mem.byte('wCurDay') % 7 in CONTEST_DAYS:
        return 'Waiting for tomorrow: the Bug-Catching Contest was already entered today' if mem.byte('wDailyFlags1') & 2 else None
    return 'Waiting for Tuesday, Thursday or Saturday: the Bug-Catching Contest'


def journey(policy, snapshot, Goal, *, force=False):
    mem, data = Memory(policy.memory, policy.data), policy.data
    state = policy.collection.get('contest')
    running = bool(mem.byte('wStatusFlags2') & 4)
    if state is None:
        needed = needs_sun_stone(policy, snapshot)
        if (not force and not needed or mem.byte('wCurDay') % 7 not in CONTEST_DAYS
                or mem.byte('wDailyFlags1') & 2 or policy.collection.get('tower')):
            return None
        if not snapshot.can_catch:
            goal = policy.storage_goal(snapshot)
            return Goal('collection_box', 'Make room for the Bug-Catching Contest', goal.map_name, goal.x, goal.y, goal.face)
        state = policy.collection['contest'] = {'entered': False, 'started': policy.decisions}
    name = data.maps[snapshot.map]['constant']
    if running:
        state['entered'] = True
        if name != 'NATIONAL_PARK_BUG_CONTEST':
            return Goal('contest_results', 'Finish the Bug-Catching Contest', name, snapshot.x, snapshot.y)
        if (score(mem, 'wContestMon') >= 376 or not mem.byte('wParkBallsRemaining')
                or policy.decisions - state['started'] > 5000):
            return Goal('contest_finish', 'Take the contest catch to the judges', 'ROUTE_35_NATIONAL_PARK_GATE', 3, 1)
        from .collection import encounter_points
        points = encounter_points(policy, snapshot, snapshot.map, 'grass')
        points = sorted((point for point in points if point[:2] != (snapshot.x, snapshot.y)),
                        key=lambda point: abs(point[0] - snapshot.x) + abs(point[1] - snapshot.y))[:24]
        choices = [(policy.nav.local(snapshot, [point[:2]], policy.memory), point) for point in points]
        choices = [(len(path), policy.nav.visits.get((snapshot.map, *point[:2]), 0), point)
                   for path, point in choices if path]
        if choices:
            point = min(choices)[2]
            return Goal('contest_search', 'Find a strong contest Pokémon', name, *point[:2])
        return Goal('contest_search', 'Enter the contest grass', name, 10, 30)
    if state['entered']:
        if mem.byte('wScriptRunning') or '┌' in snapshot.tiles[12]:
            return Goal('contest_results', 'Hear the contest results', name, snapshot.x, snapshot.y)
        policy.collection['contest_result'] = {'first_place': mem.byte('wBugContestFirstPlaceWinnerID') == 1}
        policy.collection.pop('contest', None)
        policy.completed['contest'] = snapshot.frame
        return None
    return Goal('contest_enter', 'Enter the Bug-Catching Contest', 'ROUTE_35_NATIONAL_PARK_GATE', 2, 2, 'up')


def control(policy, snapshot, mem):
    if not policy.collection.get('contest') or not snapshot.in_battle or not mem.byte('wStatusFlags2') & 4:
        return None
    text = snapshot.text
    if 'YES' in text and 'NO' in text:
        keep = score(mem, 'wEnemyMon') >= score(mem, 'wContestMon')
        return choose(snapshot.tiles, 'YES' if keep else 'NO', exact=True) or 'a'
    if 'FIGHT' in text and 'TYPE' not in text:
        catching = (score(mem, 'wEnemyMon') > max(350, score(mem, 'wContestMon'))
                    and bool(mem.byte('wParkBallsRemaining')))
        x = 1 if catching else 2
        current = mem.byte('wMenuCursorX')
        if current != x:
            return 'left' if current > x else 'right'
        return 'down' if mem.byte('wMenuCursorY') < 2 else 'a'
    return 'a'
