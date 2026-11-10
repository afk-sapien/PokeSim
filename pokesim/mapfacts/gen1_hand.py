"""Gen I map facts written by hand. A script lists each square, but what it does there is code no tool reads.

Each row holds the map facts schema. tiles are walk squares, or None for the whole map. until names
the flags that end the row once all of them are set, and is empty when the row always holds. effect
says what navigation does there: avoid keeps routine routes off the squares, fall drops the player
to the square in to, and skip keeps routes off the map. source is the script file and the label the
row was read from. tests/test_gen1_hand_facts.py pins every row and checks it against its source
whenever a checkout is present.
"""
from typing import NamedTuple


class Row(NamedTuple):
    map: str
    kind: str
    tiles: tuple | None
    effect: str
    source: tuple
    reason: str
    until: tuple = ()
    to: tuple | None = None
    generated: bool = False


_HOLE = 'A boulder pushed in falls to the floor below, and so does the player. Routine routes take the ladders.'
_BOULDERS = ('EVENT_SEAFOAM3_BOULDER1_DOWN_HOLE', 'EVENT_SEAFOAM3_BOULDER2_DOWN_HOLE')
_CURRENT = 'The current pushes the player away from this apparent exit until both boulders from B2F block it.'
_LIFT = 'The lift picks its floor from a menu. Routes take the stairs.'

HAND = (
    Row('SEAFOAM_ISLANDS_1F', 'hole', ((17, 6), (24, 6)), 'avoid',
        ('SeafoamIslands1F', 'Seafoam1HolesCoords'), _HOLE),
    Row('SEAFOAM_ISLANDS_B1F', 'hole', ((18, 6), (23, 6)), 'avoid',
        ('SeafoamIslandsB1F', 'Seafoam2HolesCoords'), _HOLE),
    Row('SEAFOAM_ISLANDS_B2F', 'hole', ((19, 6), (22, 6)), 'avoid',
        ('SeafoamIslandsB2F', 'Seafoam3HolesCoords'), _HOLE),
    Row('SEAFOAM_ISLANDS_B3F', 'hole', ((3, 16), (6, 16)), 'avoid',
        ('SeafoamIslandsB3F', 'Seafoam4HolesCoords'), _HOLE),
    Row('SEAFOAM_ISLANDS_B3F', 'current', ((15, 8),), 'avoid',
        ('SeafoamIslandsB3F', 'SeafoamIslandsB3FDefaultScript'), _CURRENT, until=_BOULDERS),
    Row('SEAFOAM_ISLANDS_B4F', 'current', ((20, 16), (21, 16), (20, 17), (21, 17)), 'avoid',
        ('SeafoamIslandsB4F', 'SeafoamIslandsB4FDefaultScript.Coords'), _CURRENT, until=_BOULDERS),
    Row('POKEMON_MANSION_3F', 'hole', ((16, 14), (17, 14)), 'fall',
        ('PokemonMansion3F', 'PokemonMansion3FDefaultScript.holeCoords'),
        'The player falls to 1F. Only the Mansion planner routes through the fall.',
        to=('POKEMON_MANSION_1F', 16, 14)),
    Row('VICTORY_ROAD_3F', 'hole', ((23, 15),), 'fall',
        ('VictoryRoad3F', 'VictoryRoad3FDefaultScript.SwitchOrHoleCoords'),
        'The player falls to 2F. Routes take the fall as a forced move.',
        to=('VICTORY_ROAD_2F', 22, 16)),
    Row('CELADON_MART_ELEVATOR', 'lift', None, 'skip',
        ('CeladonMartElevator', 'CeladonMartElevatorFloors'), _LIFT),
    Row('SILPH_CO_ELEVATOR', 'lift', None, 'skip',
        ('SilphCoElevator', 'SilphCoElevatorFloors'), _LIFT),
)
