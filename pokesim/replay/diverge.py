"""Where two recorded runs of one rung part.

Both runs start from the rung's start state, so their traces line up record by record until the
first one that differs. Three places are reported: the first record of any kind (a decide record
differs there when game memory has already parted), the first action (a press, release, tick,
write, load or input), and the first goal change. Each comes with the last decide before it on
both sides, which names the goal, map and position. This compares two recorded traces. It does
not play either commit again.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from pokecore.trace import Trace

SEGMENT = 'trace/0001.jsonl.gz'
# Registrations depend on which observing hooks a commit has, as in trace verify.
SKIP = frozenset(('hook',))
ACTIONS = frozenset(('press', 'release', 'tick', 'write', 'load', 'input'))
NEXT = 6
TOP_ROWS = 5


def _body(record):
    return {key: value for key, value in record.items() if key not in ('index', 'frame', 'hash')}


def short(record):
    """One action as a few words, such as ``press a`` or ``tick 12``."""
    kind = record['kind']
    if kind in ('press', 'release'):
        return f'{kind} {record.get("button")}'
    if kind == 'tick':
        hooks = sum(len(entry[3]) for entry in record.get('hooks', ()))
        return f'tick {record.get("frames")}' + (f' with {hooks} hook writes' if hooks else '')
    if kind == 'write':
        return f'write {record.get("address")}={record.get("value")}' if 'address' in record else 'write unrecorded'
    if kind == 'input':
        return f'input {record.get("source")}'
    if kind == 'decide':
        return f'decide {record.get("goal")} at {record.get("map")} ({record.get("x")}, {record.get("y")})'
    return kind


def _place(decide, start):
    if decide is None:
        return None
    return {'frame': decide['frame'] - start, **{key: decide.get(key) for key in ('goal', 'map', 'x', 'y')}}


def _stream(records, start, kinds):
    """(frame offset, record, last decide at or before it) for each record of ``kinds``."""
    last, out = None, []
    for record in records:
        kind = record['kind']
        if kind in SKIP:
            continue
        if kind == 'decide':
            last = record
        if kinds is None or kind in kinds:
            out.append((record['frame'] - start, record, last))
    return out


def _side(stream, position, start):
    offset, record, decide = stream[position]
    return {'frame': offset, 'kind': record['kind'], 'what': short(record), 'decide': _place(decide, start),
            'next': [short(item[1]) for item in stream[position:position + NEXT]]}


def first_difference(a, b, kinds=None, starts=(0, 0)):
    """The first record of ``kinds`` that differs between record lists ``a`` and ``b``, or None.

    ``kinds`` None means every kind but hook registrations. ``starts`` are the segment start
    frames, since records compare by frame offset.
    """
    left, right = _stream(a, starts[0], kinds), _stream(b, starts[1], kinds)
    for position, (x, y) in enumerate(zip(left, right)):
        if x[0] != y[0] or _body(x[1]) != _body(y[1]):
            return {'position': position, 'a': _side(left, position, starts[0]), 'b': _side(right, position, starts[1])}
    if len(left) == len(right):
        return None
    position = min(len(left), len(right))
    found = {'position': position, 'ended': 'a' if len(left) < len(right) else 'b'}
    for name, stream, start in (('a', left, starts[0]), ('b', right, starts[1])):
        if position < len(stream):
            found[name] = _side(stream, position, start)
    return found


def goal_changes(records, start=0):
    """Each decide whose goal differs from the one before, as frame offset, goal and place."""
    out, last, seen = [], None, False
    for record in records:
        if record['kind'] == 'decide' and (not seen or record.get('goal') != last):
            out.append(_place(record, start))
            last, seen = record.get('goal'), True
    return out


def goal_divergence(a, b, starts=(0, 0)):
    """The first goal change that differs in frame or goal, with the change before it, or None."""
    left, right = goal_changes(a, starts[0]), goal_changes(b, starts[1])
    for change, (x, y) in enumerate(zip(left, right)):
        if (x['frame'], x['goal']) != (y['frame'], y['goal']):
            return {'change': change, 'a': x, 'b': y, 'before': left[change - 1] if change else None}
    if len(left) == len(right):
        return None
    change = min(len(left), len(right))
    longer = left if len(left) > len(right) else right
    return {'change': change, 'ended': 'a' if len(left) < len(right) else 'b', 'next': longer[change],
            'before': left[change - 1] if change else None}


def wasted_rows(run_file, top=TOP_ROWS):
    """The rows that wasted the most frames, with their share of the run."""
    frames = max(run_file.get('frames') or 0, 1)
    rows = sorted((run_file.get('wasted') or {}).items(), key=lambda item: (-item[1], item[0]))[:top]
    return [{'row': row, 'frames': value, 'share': round(100 * value / frames, 2)} for row, value in rows]


def stand_downs(run_file, run_frame=None):
    """Each stand-down with its frame offset from the segment start, when the header names the run's frame."""
    out = []
    for entry in run_file.get('stand_downs') or []:
        frame = entry.get('frame')
        offset = frame - run_frame if run_frame is not None and frame is not None else None
        out.append({**entry, 'offset': offset})
    return out


def loops(downs):
    """Stand-downs per key: how many, the first frame and the frames between one and the next."""
    frames = defaultdict(list)
    for entry in downs:
        frames[entry['key']].append(entry['frame'])
    return {key: {'count': len(seen), 'first': seen[0], 'periods': [b - a for a, b in zip(seen, seen[1:])]}
            for key, seen in frames.items()}


def loop_start(changes, downs):
    """The goal change that began the span the first stand-down ended, from the side's goal changes."""
    first = next((entry for entry in downs if entry.get('offset') is not None), None)
    if first is None:
        return None
    key = str(first.get('goal') or '').split(' ')[0]
    begun = [change for change in changes if change['frame'] <= first['offset'] and change['goal'] == key]
    return begun[-1] if begun else None


def _read(folder, name):
    path = Path(folder) / name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def side(folder):
    """What one recorded run says about itself, and its trace."""
    folder = Path(folder)
    trace = Trace.read(folder / SEGMENT)
    summary, run_file = _read(folder, 'summary.json') or {}, _read(folder, 'run.json') or {}
    replay = _read(folder, 'replay.json') or {}
    header = trace.header
    downs = stand_downs(run_file, header.get('run_frame'))
    start = header.get('frame', 0)
    changes = goal_changes(trace.records, start)
    info = {'folder': str(folder), 'commit': header.get('commit'), 'pyboy': header.get('emulator', {}).get('version'),
            'pokecore': header.get('pokecore'), 'head': trace.head, 'records': len(trace.records),
            'truncated': trace.truncated, 'frames': summary.get('frames'), 'waste': summary.get('waste'),
            'stall': summary.get('stall'), 'errors': summary.get('errors'), 'wasted_rows': wasted_rows(run_file),
            'stand_downs': downs, 'loops': loops(downs), 'loop_start': loop_start(changes, downs),
            'goal_changes': len(changes), 'clock': header.get('clock'), 'seconds': replay.get('seconds')}
    return info, trace


def compare(a, b):
    """The diverge report of run folders ``a`` and ``b``."""
    left, ta = side(a)
    right, tb = side(b)
    starts = (ta.header.get('frame', 0), tb.header.get('frame', 0))
    first = first_difference(ta.records, tb.records, None, starts)
    # The head covers the header, which names the commit, so two commits differ there even when every record agrees.
    return {'a': left, 'b': right, 'same_head': ta.head == tb.head, 'same_records': first is None,
            'first_record': first,
            'first_action': first_difference(ta.records, tb.records, ACTIONS, starts),
            'first_goal': goal_divergence(ta.records, tb.records, starts)}


def _where(place):
    if not place:
        return 'before any decide'
    return f'goal {place["goal"]} at map {place["map"]} ({place["x"]}, {place["y"]}), decided at frame {place["frame"]}'


def _found(title, found):
    if found is None:
        return [f'- {title}: none, the two agree.']
    lines = [f'- {title}: position {found["position"]}.']
    if 'ended' in found:
        lines.append(f'  - Side {found["ended"].upper()} ended there.')
    for name in ('a', 'b'):
        if name in found:
            item = found[name]
            lines.append(f'  - {name.upper()} at frame {item["frame"]}: {item["what"]}. Last decide: {_where(item["decide"])}.')
            lines.append(f'    Next: {", ".join(item["next"])}.')
    return lines


def markdown(report, title='Diverge'):
    lines = [f'# {title}', '']
    for name in ('a', 'b'):
        info = report[name]
        stall = info['stall']['reason'] if info.get('stall') else 'none'
        lines.append(f'- {name.upper()}: {str(info["commit"])[:12]} on pyboy-rs {info["pyboy"]}, '
                     f'{info["frames"]} frames, {info["waste"]}% wasted, stall {stall}, {info["records"]} records.')
    if report['same_head']:
        lines.append('- Same head: yes.')
    elif report.get('same_records'):
        lines.append('- Same head: no, only the headers differ. Every record agrees.')
    else:
        lines.append('- Same head: no.')
    lines += _found('First record that differs', report['first_record'])
    lines += _found('First action that differs', report['first_action'])
    goal = report['first_goal']
    if goal is None:
        lines.append('- First goal change that differs: none.')
    elif 'ended' in goal:
        lines.append(f'- First goal change that differs: change {goal["change"]}, side {goal["ended"].upper()} '
                     f'has no more. The other goes to {_where(goal["next"])}.')
    else:
        lines.append(f'- First goal change that differs: change {goal["change"]}. A: {_where(goal["a"])}. '
                     f'B: {_where(goal["b"])}. Before it: {_where(goal["before"])}.')
    for name in ('a', 'b'):
        info = report[name]
        rows = ', '.join(f'{row["row"]} {row["share"]}%' for row in info['wasted_rows']) or 'none'
        lines.append(f'- {name.upper()} top wasted rows: {rows}.')
        for key, loop in info['loops'].items():
            periods = ', '.join(str(period) for period in loop['periods']) or 'none'
            lines.append(f'- {name.upper()} stood down {loop["count"]} times on {key}, first at run frame '
                         f'{loop["first"]}, frames between: {periods}.')
        if info['loop_start']:
            lines.append(f'- {name.upper()} first loop round began with {_where(info["loop_start"])}.')
    return '\n'.join(lines) + '\n'
