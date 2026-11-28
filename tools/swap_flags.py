"""The one event flag that decides a swapped map block, for both generations' map facts.

tools/gen1_map_facts.py and tools/gen2_map_facts.py each read their scripts into the cases of a
site, a list of (block, conditions), and this evaluates them over every flag state the same way.
"""
import itertools


def decide(name, site, cases):
    """(flag, block once set, block until set) for a site one flag decides. None draws nothing."""
    flags = sorted({flag for _, conds in cases for flag, _ in conds})

    def outcome(state):
        blocks = {block for block, conds in cases if all(state[flag] == value for flag, value in conds)}
        if len(blocks) > 1:
            raise ValueError(f'{name} {site} draws {sorted(blocks)} under the same flags')
        return next(iter(blocks), None)

    states = [dict(zip(flags, values)) for values in itertools.product((False, True), repeat=len(flags))]
    deciding = [flag for flag in flags if any(outcome(state) != outcome({**state, flag: not state[flag]})
                                              for state in states)]
    if len(deciding) != 1:
        raise ValueError(f'{name} {site} depends on {deciding}, not on one flag')
    flag = deciding[0]
    rest = {other: False for other in flags}
    return flag, outcome({**rest, flag: True}), outcome({**rest, flag: False})
