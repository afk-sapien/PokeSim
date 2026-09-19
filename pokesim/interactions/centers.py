"""Verified retail Red and Blue Cable Club preparation locations."""

_STANDARD = {
    41: 'Viridian Pokémon Center',
    58: 'Pewter Pokémon Center',
    64: 'Cerulean Pokémon Center',
    68: 'Mt. Moon Pokémon Center',
    81: 'Rock Tunnel Pokémon Center',
    89: 'Vermilion Pokémon Center',
    133: 'Celadon Pokémon Center',
    141: 'Lavender Pokémon Center',
    154: 'Fuchsia Pokémon Center',
    171: 'Cinnabar Pokémon Center',
    182: 'Saffron Pokémon Center',
}

CENTERS = {map_id: {'name': name, 'pc': (map_id, 13, 4),
                    'rendezvous': (map_id, 11, 3)} for map_id, name in _STANDARD.items()}
CENTERS[174] = {'name': 'Indigo Plateau lobby', 'pc': (174, 15, 8),
                'rendezvous': (174, 13, 7)}


def safe_center(snapshot, map_id, memory):
    """Require a loaded overworld, not the save data shown by Continue."""
    from pokesim.screen import Screen
    screen = Screen(memory)
    return (type(map_id) is int and map_id in CENTERS and snapshot.valid and snapshot.started
            and snapshot.map == map_id and not snapshot.in_battle
            and not snapshot.textbox and not snapshot.start_menu
            and memory[0xcfcb] == 1 and screen.cursor is None
            and 'CONTINUE' not in screen.text and 'NEW GAME' not in screen.text
            and screen.kind(snapshot) == 'overworld')
