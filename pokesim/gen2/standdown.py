"""Objectives that cannot progress stand down for a while instead of repeating forever.

A hunt or a training project that stalled is remembered by key: ``hunt:<species>`` or
``train:<identity>``. A reload restores the policy from an older checkpoint, so the emulator
carries these keys over and the restored run does not walk straight back into the same trouble.

The shared ``Monitor`` keeps the record in the policy's collection state, counted in decisions.
"""
import json

from ..planning.monitor import STAND_DOWNS, STOOD_DOWN, Backoff, Monitor

# Decisions an objective that stood down waits before it is tried again.
STAND_DOWN = 50000
BACKOFF = Backoff(STAND_DOWN)


def monitor(policy, backoff=BACKOFF):
    return Monitor(policy.collection, backoff=backoff)


def hunt_key(species):
    return f'hunt:{int(species)}'


def train_key(identity):
    return 'train:' + json.dumps(identity)


def team_key(team):
    return 'team:' + json.dumps(list(team))


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
        state.pop('activity_blocked', None)
