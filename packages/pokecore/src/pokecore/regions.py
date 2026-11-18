"""Decoded memory regions kept while their raw bytes are unchanged.

A region is one named part of a snapshot, such as the party or one box. Its decoded value is kept
under its name together with the raw bytes and the static game data it was built from, and is
handed back, the same object, while both still match. Each name keeps only its latest entry, so
the store stays small and never outlives a change of those bytes. Only immutable values belong
here, because every caller shares them.
"""

_regions = {}


def region(name, key, data, build):
    """``build()``, or the value kept for ``name`` when ``key`` equals and ``data`` is the same object."""
    entry = _regions.get(name)
    if entry is not None and entry[0] is data and entry[1] == key:
        return entry[2]
    value = build()
    _regions[name] = (data, key, value)
    return value


def clear_region_cache():
    _regions.clear()
