"""Game formulas shared by Red, Blue, Yellow, Gold, Silver and Crystal.

The experience curves are the same in both generations. ``growth`` is the curve's name
without the GROWTH_ prefix: 'FAST', 'MEDIUM_FAST', 'MEDIUM_SLOW' or 'SLOW'. Any other
value, including None, reads as MEDIUM_FAST, the cube curve.
"""


def experience_at(level, growth):
    """The total experience a Pokémon has on reaching ``level``, clamped to 1 to 100."""
    n = max(1, min(100, level))
    if growth == 'FAST':
        return 4 * n ** 3 // 5
    if growth == 'SLOW':
        return 5 * n ** 3 // 4
    if growth == 'MEDIUM_SLOW':
        return max(0, 6 * n ** 3 // 5 - 15 * n ** 2 + 100 * n - 140)
    return n ** 3


def experience_progress(total, level, growth):
    """Progress through ``level``: its start and the next level's, what remains and a percent."""
    start = experience_at(level, growth)
    end = experience_at(min(100, level + 1), growth)
    return {'total': total, 'level_start': start, 'next_level': end,
            'remaining': max(0, end - total), 'max_level': level >= 100,
            'percent': 100 if level >= 100 else round(max(0, min(100, (total - start) * 100 / max(1, end - start))), 1)}
