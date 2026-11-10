"""Bounded directional walking for English Red and Blue. No route planning."""
from .state_actions import _Budget, _integer
from .control_results import control_status

DIRECTIONS = ('up', 'down', 'left', 'right')


def position(memory):
    return {'map_id': memory[0xD35E], 'x': memory[0xD362], 'y': memory[0xD361]}


def walk_tiles(port, direction, count, *, max_frames, input_locked=lambda: False):
    """Walk a caller-selected direction and stop on a choice, obstruction or map change.

    Turning is handled mechanically. No exits or destinations are selected.
    Map changes stop the command without inferring distance across coordinate systems.
    """
    if port.version not in (None, 'red', 'blue'):
        raise ValueError('walk_tiles currently supports Red and Blue only')
    if direction not in DIRECTIONS:
        raise ValueError('Choose up, down, left or right')
    _integer(count, 'count', 1)
    if count > 8:
        raise ValueError('A walking command supports at most eight tiles')
    budget = _Budget(port, max_frames)
    memory = port.memory
    before = position(memory)
    completed = 0
    reason = 'complete'
    outcome = None
    for _ in range(count):
        if port.stopped():
            reason = 'stopped'
            break
        if port.observe()['kind'] != 'overworld' or memory[0xD057]:
            reason = 'choice'
            outcome = 'Stopped at dialogue, menu or battle.'
            break
        if input_locked() or memory[0xC200]:
            reason = 'input_locked'
            outcome = 'Stopped while movement or scripted controls are active.'
            break
        location = position(memory)
        facing = memory[0xC109]
        status = budget.send(direction, 8, 16)
        if not status and memory[0xC200]:
            status = budget.send(None, 16, 0)
        current = position(memory)
        if (not status and current == location and memory[0xC109] != facing
                and port.observe()['kind'] == 'overworld' and not input_locked()):
            status = budget.send(direction, 8, 16)
            if not status and memory[0xC200]:
                status = budget.send(None, 16, 0)
            current = position(memory)
        if current['map_id'] != location['map_id']:
            reason = 'map_changed'
            outcome = 'Stopped at map transition.'
            break
        completed += abs(current['x'] - location['x']) + abs(current['y'] - location['y'])
        if status:
            reason = 'stopped' if port.stopped() else 'budget' if status in ('timeout', 'consumer_budget') else status
            outcome = 'Stopped at controller or frame budget boundary.'
            break
        if current == location:
            reason = 'blocked'
            outcome = f'Moved {completed} tiles, then blocked or no further movement.'
            break
    after = position(memory)
    settled = (not port.stopped() and port.observe()['kind'] == 'overworld'
               and not memory[0xD057] and not memory[0xC200] and not input_locked())
    result = {'outcome': outcome or f'Moved {completed} tiles.', 'tiles_moved': completed,
              'requested_tiles': count, 'position_before': before, 'position_after_input': after,
              'map_changed': before['map_id'] != after['map_id'],
              'control': control_status('walk_tiles', reason, completed=completed >= count and reason == 'complete',
                                        settled=settled, frames=budget.elapsed(), inputs=budget.actions)}
    if reason == 'blocked':
        result['blocked_at'] = after
    return result
