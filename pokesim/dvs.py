"""Determinant-value checks that need no game data, so Gen II workers can use them without Gen I data."""


def is_perfect(mon):
    dvs = mon.get('dvs')
    return isinstance(dvs, (list, tuple)) and len(dvs) == 5 and all(
        type(value) is int and value == 15 for value in dvs)
