"""Objectives that cannot progress stand down for a while instead of repeating forever.

A hunt or a training project that stalled is remembered by key: ``hunt:<species>`` or
``train:<identity>``. A reload restores the policy from an older checkpoint, so the emulator
carries these keys over and the restored run does not walk straight back into the same trouble.
"""
import json

# Decisions an objective that stood down waits before it is tried again.
STAND_DOWN = 50000


def hunt_key(species):
    return f'hunt:{int(species)}'


def train_key(identity):
    return 'train:' + json.dumps(identity)


def stand_down(policy, key):
    policy.collection.setdefault('stood_down', {})[key] = policy.decisions


def standing_down(policy, key):
    when = (policy.collection.get('stood_down') or {}).get(key)
    return when is not None and policy.decisions - when < STAND_DOWN


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
    team = state.get('activity_team') if goal is not None and goal.key == 'collection_activity_team' else None
    return {'keys': sorted(keys), 'earlier': dict(state.get('stood_down') or {}), 'team': team}


def carry_over(policy, stalled):
    """Stand the stalled objectives down in the policy a reload just restored."""
    state = policy.collection
    stood = state.setdefault('stood_down', {})
    for key, when in stalled['earlier'].items():
        # Decisions rewind with the reload, so an earlier stand-down is kept at most from now.
        stood[key] = min(stood.get(key, when), when, policy.decisions)
    for key in stalled['keys']:
        stand_down(policy, key)
    target = state.get('target')
    if target and hunt_key(target['species']) in stalled['keys']:
        state['target'] = None
    training = state.get('training')
    if training and train_key(training['identity']) in stalled['keys']:
        state['training'] = None
    if stalled['team']:
        from .teams import RETRY_AFTER
        state.pop('activity_team', None)
        state.pop('activity_blocked', None)
        state['activity_failed'] = {'team': list(stalled['team']), 'until': policy.decisions + RETRY_AFTER}
