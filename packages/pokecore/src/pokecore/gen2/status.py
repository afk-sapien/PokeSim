"""The shared adventure status payload for a Gen II game.

Ported from PokeSim's pokesim/gen2/web.py ``live_status`` with identical output.
"""
from .battle_power import battle_power
from .memory_map import VERSIONS

DEFAULT_VERSION = 'crystal'

__all__ = ['DEFAULT_VERSION', 'VERSIONS', 'live_status']


def live_status(game, collection=None, *, data=None, **kwargs):
    """Status for one game dict. Each Pokémon gains ``battle_power`` when ``data`` is given."""
    collection = collection or {}
    game = game or {}

    def rated(mon):
        return {**mon, 'battle_power': battle_power(mon, data) if data is not None else None}

    storage = game.get('storage')
    if storage:
        storage = {**storage, 'pokemon': [rated(mon) for mon in storage.get('pokemon', [])]}
    party = [{**rated(mon), 'slot': index + 1} for index, mon in enumerate(game.get('party', []))]
    return {'started': bool(game), 'version': collection.get('version', DEFAULT_VERSION),
            'generation': 2, 'dex_total': 251, 'owned': game.get('dex_owned', []),
            'seen': game.get('dex_seen', []), 'party': party,
            'storage': storage, 'player_name': game.get('player_name', ''),
            'playtime': game.get('playtime', ''), 'plan': collection.get('plan', []),
            'phase': collection.get('phase', 'journey'), 'hunting': collection.get('hunting'),
            'protected_species': collection.get('protected_species', []), 'catches': {}}
