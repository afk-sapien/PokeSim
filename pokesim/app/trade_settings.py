"""Library-wide trading settings: auto trading, open to offers and auto trading with other people, per adventure.

Earlier 0.5.0 builds also stored a wish list per adventure. It is no longer read or offered,
but a stored one is left in place, so an older release still finds it after a downgrade.

The library-wide Ask me first switch below is kept for the unwired trade_requests module.
Nothing in 0.5.0 reads it, so automatic trades always start on their own.

They live in the library registry, not in each adventure's settings, so an older release
that validates adventure settings still opens the library after a downgrade.
"""
from __future__ import annotations

import threading

from .registry import validate_id

KEY = 'trade_auto'
# Settings that cover every adventure at once. Only the unwired Ask me first switch lives here.
LIBRARY_KEY = 'trade_auto_library'
# Every adventure's settings share one registry value, so each change reads and writes it whole.
_write = threading.Lock()


def _all(registry):
    value = registry.setting(KEY, {})
    return value if isinstance(value, dict) else {}


def _clean(entry):
    entry = entry if isinstance(entry, dict) else {}
    # With accounts, an adventure takes offers from other people, and trades automatically with
    # their adventures, only when its owner turns that on.
    return {'enabled': entry.get('enabled', True) is not False,
            'open_to_offers': entry.get('open_to_offers') is True,
            'across_owners': entry.get('across_owners') is True}


def get(registry, aid):
    """The automatic trading settings of one adventure. New adventures trade automatically."""
    validate_id(aid)
    return _clean(_all(registry).get(aid))


SWITCHES = {'enabled': 'Auto trading', 'open_to_offers': 'Open to offers', 'across_owners': 'Auto trading with other people'}


def update(registry, aid, **values):
    validate_id(aid)
    for name, value in values.items():
        if name not in SWITCHES:
            raise ValueError(f'Unknown trade setting {name}')
        if value is not None and not isinstance(value, bool):
            raise ValueError(f'{SWITCHES[name]} is either on or off')
    with _write:
        settings = _all(registry)
        stored = settings.get(aid)
        # Other stored keys, such as an old wish list, stay as they were.
        stored = dict(stored) if isinstance(stored, dict) else {}
        stored.update({name: value for name, value in values.items() if value is not None})
        settings[aid] = stored
        registry.set_setting(KEY, settings)
        return _clean(stored)


def ask_first(registry):
    """Whether automatic trading would suggest exchanges for the owner to approve. Unused in 0.5.0."""
    value = registry.setting(LIBRARY_KEY, {})
    return not isinstance(value, dict) or value.get('ask_first', True) is not False


def set_ask_first(registry, value):
    if not isinstance(value, bool):
        raise ValueError('Ask me first is either on or off')
    with _write:
        current = registry.setting(LIBRARY_KEY, {})
        current = dict(current) if isinstance(current, dict) else {}
        current['ask_first'] = value
        registry.set_setting(LIBRARY_KEY, current)
    return value
