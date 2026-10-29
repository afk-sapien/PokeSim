"""Objectives that cannot progress stand down for a while instead of repeating forever.

A hunt or a training project that stalled is remembered by key: ``hunt:<species>`` or
``train:<identity>``. A reload restores the policy from an older checkpoint, so the emulator
carries these keys over and the restored run does not walk straight back into the same trouble.

The shared ``Monitor`` keeps the record in the policy's collection state, counted in decisions.
"""
import json

# search_expected is shared now. Hunts and the postgame still take it from here.
from ..planning.cost import DECISIONS_PER_BATTLE, DECISIONS_PER_MAP
from ..planning.cost import search_expected as search_expected
from ..planning.monitor import SPENT, STAND_DOWNS, STOOD_DOWN, Backoff, Monitor

# Decisions an objective that stood down waits before it is tried again.
STAND_DOWN = 50000
BACKOFF = Backoff(STAND_DOWN)

# A goal stands down once it spent three times its expected decisions (planning/cost.py) without
# progress, and never later than about two game hours.
MOST_DECISIONS = 14000
# A training trip is expected to cross a few maps and then win a battle before the trainee gains experience.
TRAINING_DECISIONS = 4 * DECISIONS_PER_MAP + DECISIONS_PER_BATTLE


def monitor(policy, backoff=BACKOFF):
    return Monitor(policy.collection, backoff=backoff)


def exhausted(policy, key, budget, amount=1, events=()):
    """Count ``amount`` against ``key`` and say when it reached ``budget`` without progress.

    The count is kept with the save and cleared by any progress event, and again once it runs out.
    """
    tracker = monitor(policy)
    tracker.start(key, budget=budget)
    if not tracker.observe(key, amount, events).stand_down:
        return False
    tracker._table(SPENT).pop(key, None)
    return True


def spend(policy, key, expected, events=(), amount=1, progressed=False):
    """Count decisions against ``key`` and stand it down once it spent three times ``expected`` without progress."""
    budget = min(MOST_DECISIONS, round(3 * expected))
    if not exhausted(policy, key, budget, amount, events):
        return False
    monitor(policy).stand_down(key, policy.decisions, progressed=progressed)
    return True


def forget(policy, key):
    """Drop what ``key`` spent toward its budget, as when its goal is met or abandoned."""
    monitor(policy)._table(SPENT).pop(key, None)


def hunt_key(species):
    return f'hunt:{int(species)}'


def train_key(identity):
    return 'train:' + json.dumps(identity)


def team_key(team):
    return 'team:' + json.dumps(list(team))


def pc_key(team):
    """The count of PC presses that changed nothing while assembling ``team``."""
    return 'pc:' + json.dumps(list(team))


def stand_down(policy, key, backoff=BACKOFF):
    return monitor(policy, backoff).stand_down(key, policy.decisions)


def standing_down(policy, key, backoff=BACKOFF):
    until = monitor(policy, backoff).until(key)
    return until is not None and policy.decisions < until


def migrate(policy):
    """Move a save's older retry records onto the monitor."""
    state = policy.collection
    failed = state.pop('activity_failed', None)
    if isinstance(failed, dict) and failed.get('team') is not None:
        state.setdefault(STOOD_DOWN, {})[team_key(failed['team'])] = failed.get('until', 0) - STAND_DOWN
    # Older saves counted carrier decisions, refused PC presses and loading steps in their own fields.
    state.pop('carrier_decisions', None)
    blocked = state.pop('activity_blocked', None)
    if blocked and state.get('activity_team') is not None:
        state.setdefault(SPENT, {})[pc_key(state['activity_team'])] = blocked
    activity = (state.get('postgame') or {}).get('activity')
    if isinstance(activity, dict):
        activity.pop('unavailable_steps', None)
    from .tower import migrate as tower
    tower(policy)


def stalled_objectives(policy):
    """Keys of the objectives in progress, which a reload for lack of progress stands down."""
    state, goal = policy.collection, policy.goal
    keys = set()
    target = state.get('target')
    if target:
        keys.add(hunt_key(target['species']))
    training = state.get('training')
    if training and goal is not None and goal.key.startswith('collection_train'):
        keys.add(train_key(training['identity']))
    from .postgame import stall_key
    search = stall_key(policy) if not target else None
    if search:
        keys.add(search)
    team = state.get('activity_team') if goal is not None and goal.key == 'collection_activity_team' else None
    if team:
        keys.add(team_key(team))
    return {'keys': sorted(keys), 'earlier': dict(state.get(STOOD_DOWN) or {}),
            'counts': dict(state.get(STAND_DOWNS) or {}), 'team': team}


def carry_over(policy, stalled):
    """Stand the stalled objectives down in the policy a reload just restored."""
    state = policy.collection
    stood = state.setdefault(STOOD_DOWN, {})
    for key, when in stalled['earlier'].items():
        # Decisions rewind with the reload, so an earlier stand-down is kept at most from now.
        stood[key] = min(stood.get(key, when), when, policy.decisions)
    counts = state.setdefault(STAND_DOWNS, {})
    for key, count in stalled.get('counts', {}).items():
        counts[key] = max(counts.get(key, 0), count)
    for key in stalled['keys']:
        stand_down(policy, key)
    target = state.get('target')
    if target and hunt_key(target['species']) in stalled['keys']:
        state['target'] = None
    training = state.get('training')
    if training and train_key(training['identity']) in stalled['keys']:
        state['training'] = None
    from .postgame import finish, stall_key
    if stall_key(policy) in stalled['keys']:
        finish(policy)
    if stalled['team']:
        state.pop('activity_team', None)
        forget(policy, pc_key(stalled['team']))
