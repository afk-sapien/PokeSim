"""A deterministic randomizer that turns a seed into a :mod:`romdata` override map.

:func:`randomize` draws one species map per seed, a shuffle of every species the
cartridge holds, and applies it to the parts :class:`Options` selects: wild encounter
slots, starters and (opt-in) trainer parties. Levels never change, so
:func:`pokecore.romdata.patch_rom` can write the result in place.

A draw is kept only when every HM the story requires has a wild learner catchable before
the point where the game asks for it (:data:`HM_GATES`). Otherwise the same generator
draws again. The maps behind each gate are a conservative subset of what the player can
reach, and starters never count, so a kept draw cannot softlock on an HM.

Share codes name a game, the options and the seed: ``PSR1-RED-SW-12345``.
The same code and cartridge always give the same overrides.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random

__all__ = ['HM_GATES', 'MAX_DRAWS', 'Options', 'decode_share_code', 'default_moves', 'encode_share_code',
           'hm_gates', 'missing_hm_learners', 'randomize']

MAX_DRAWS = 1000
PREFIX = 'PSR1'
MAX_SEED = 2 ** 64
# Share code letters, in the order they appear in a code.
OPTION_CODES = (('wild', 'W'), ('starters', 'S'), ('trainers', 'T'))
GAMES = ('red', 'blue', 'yellow', 'gold', 'silver', 'crystal')


@dataclass(frozen=True)
class Options:
    """What a seed randomizes. Trainer parties are opt-in."""
    wild: bool = True
    starters: bool = True
    trainers: bool = False

    def code(self):
        return ''.join(letter for name, letter in OPTION_CODES if getattr(self, name))


# pret map IDs. Red, Blue and Yellow share every Gen I ID.
_GEN1 = {
    'ROUTE_1': 0x0C, 'ROUTE_2': 0x0D, 'ROUTE_3': 0x0E, 'ROUTE_4': 0x0F, 'ROUTE_5': 0x10, 'ROUTE_6': 0x11,
    'ROUTE_7': 0x12, 'ROUTE_8': 0x13, 'ROUTE_9': 0x14, 'ROUTE_10': 0x15, 'ROUTE_11': 0x16, 'ROUTE_12': 0x17,
    'ROUTE_13': 0x18, 'ROUTE_14': 0x19, 'ROUTE_15': 0x1A, 'ROUTE_16': 0x1B, 'ROUTE_17': 0x1C, 'ROUTE_18': 0x1D,
    'ROUTE_19': 0x1E, 'ROUTE_20': 0x1F, 'ROUTE_21': 0x20, 'ROUTE_22': 0x21, 'ROUTE_23': 0x22, 'ROUTE_24': 0x23,
    'ROUTE_25': 0x24, 'VIRIDIAN_FOREST': 0x33, 'MT_MOON_1F': 0x3B, 'MT_MOON_B1F': 0x3C, 'MT_MOON_B2F': 0x3D,
    'ROCK_TUNNEL_1F': 0x52, 'ROCK_TUNNEL_B1F': 0xE8, 'POWER_PLANT': 0x53, 'POKEMON_TOWER_3F': 0x90,
    'POKEMON_TOWER_4F': 0x91, 'POKEMON_TOWER_5F': 0x92, 'POKEMON_TOWER_6F': 0x93, 'POKEMON_TOWER_7F': 0x94,
    'SEAFOAM_ISLANDS_1F': 0xC0, 'SEAFOAM_ISLANDS_B1F': 0x9F, 'SEAFOAM_ISLANDS_B2F': 0xA0,
    'SEAFOAM_ISLANDS_B3F': 0xA1, 'SEAFOAM_ISLANDS_B4F': 0xA2, 'POKEMON_MANSION_1F': 0xA5,
    'POKEMON_MANSION_2F': 0xD6, 'POKEMON_MANSION_3F': 0xD7, 'POKEMON_MANSION_B1F': 0xD8, 'DIGLETTS_CAVE': 0xC5,
    'SAFARI_ZONE_EAST': 0xD9, 'SAFARI_ZONE_NORTH': 0xDA, 'SAFARI_ZONE_WEST': 0xDB, 'SAFARI_ZONE_CENTER': 0xDC,
}
# Gen II IDs are group * 256 + number. Crystal renumbers some dungeon maps.
_GOLD = {
    'ROUTE_27': 6146, 'ROUTE_29': 6147, 'ROUTE_30': 6657, 'ROUTE_31': 6658, 'ROUTE_32': 2561, 'ROUTE_33': 2054,
    'ROUTE_34': 2817, 'ROUTE_35': 2562, 'ROUTE_36': 2563, 'ROUTE_37': 2564, 'ROUTE_38': 268, 'ROUTE_39': 269,
    'ROUTE_40': 5633, 'ROUTE_41': 5634, 'ROUTE_42': 517, 'ROUTE_43': 2309, 'ROUTE_44': 518, 'ROUTE_45': 1288,
    'ROUTE_46': 1289, 'NEW_BARK_TOWN': 6148, 'CHERRYGROVE_CITY': 6659, 'VIOLET_CITY': 2565, 'CIANWOOD_CITY': 5635,
    'OLIVINE_CITY': 270, 'ECRUTEAK_CITY': 1033, 'LAKE_OF_RAGE': 2310, 'BLACKTHORN_CITY': 1290,
    'SPROUT_TOWER_2F': 770, 'SPROUT_TOWER_3F': 771, 'NATIONAL_PARK': 783, 'BURNED_TOWER_1F': 781,
    'RUINS_OF_ALPH_OUTSIDE': 790, 'UNION_CAVE_1F': 797, 'SLOWPOKE_WELL_B1F': 800, 'ILEX_FOREST': 812,
    'MOUNT_MORTAR_1F_OUTSIDE': 817, 'ICE_PATH_1F': 821, 'ICE_PATH_B1F': 822, 'ICE_PATH_B2F_MAHOGANY_SIDE': 823,
    'ICE_PATH_B2F_BLACKTHORN_SIDE': 824, 'ICE_PATH_B3F': 825, 'DARK_CAVE_VIOLET_ENTRANCE': 838,
    'DARK_CAVE_BLACKTHORN_ENTRANCE': 839, 'DRAGONS_DEN_B1F': 841,
}
_CRYSTAL = {**_GOLD, 'UNION_CAVE_1F': 805, 'SLOWPOKE_WELL_B1F': 808, 'ILEX_FOREST': 820,
            'MOUNT_MORTAR_1F_OUTSIDE': 825, 'ICE_PATH_1F': 829, 'ICE_PATH_B1F': 830,
            'ICE_PATH_B2F_MAHOGANY_SIDE': 831, 'ICE_PATH_B2F_BLACKTHORN_SIDE': 832, 'ICE_PATH_B3F': 833,
            'DARK_CAVE_VIOLET_ENTRANCE': 846, 'DARK_CAVE_BLACKTHORN_ENTRANCE': 847, 'DRAGONS_DEN_B1F': 849}

# Each gate: the HM (numbered after the 50 TMs, so HM01 is 51), then the grass and water
# maps a player reaches before the game asks for it, added to the maps of earlier gates.
_GEN1_GATES = (
    (51, ('ROUTE_1', 'ROUTE_2', 'ROUTE_22', 'VIRIDIAN_FOREST', 'ROUTE_3', 'MT_MOON_1F', 'MT_MOON_B1F',
          'MT_MOON_B2F', 'ROUTE_4', 'ROUTE_24', 'ROUTE_25', 'ROUTE_5', 'ROUTE_6', 'ROUTE_11', 'DIGLETTS_CAVE'), ()),
    (53, ('ROUTE_9', 'ROUTE_10', 'ROCK_TUNNEL_1F', 'ROCK_TUNNEL_B1F', 'ROUTE_8', 'ROUTE_7', 'POKEMON_TOWER_3F',
          'POKEMON_TOWER_4F', 'POKEMON_TOWER_5F', 'POKEMON_TOWER_6F', 'POKEMON_TOWER_7F', 'ROUTE_12', 'ROUTE_13',
          'ROUTE_14', 'ROUTE_15', 'ROUTE_16', 'ROUTE_17', 'ROUTE_18', 'SAFARI_ZONE_EAST', 'SAFARI_ZONE_NORTH',
          'SAFARI_ZONE_WEST', 'SAFARI_ZONE_CENTER'), ()),
    (54, ('ROUTE_21', 'ROUTE_23', 'POWER_PLANT', 'SEAFOAM_ISLANDS_1F', 'SEAFOAM_ISLANDS_B1F',
          'SEAFOAM_ISLANDS_B2F', 'SEAFOAM_ISLANDS_B3F', 'SEAFOAM_ISLANDS_B4F', 'POKEMON_MANSION_1F',
          'POKEMON_MANSION_2F', 'POKEMON_MANSION_3F', 'POKEMON_MANSION_B1F'),
     # Red and Blue have only the Route 19 to 21 water tables. Yellow adds the rest.
     ('ROUTE_6', 'ROUTE_12', 'ROUTE_13', 'ROUTE_19', 'ROUTE_20', 'ROUTE_21', 'SEAFOAM_ISLANDS_B3F',
      'SEAFOAM_ISLANDS_B4F')),
)
_GEN2_GATES = (
    (51, ('ROUTE_29', 'ROUTE_30', 'ROUTE_31', 'ROUTE_32', 'ROUTE_33', 'ROUTE_46', 'SPROUT_TOWER_2F',
          'SPROUT_TOWER_3F', 'DARK_CAVE_VIOLET_ENTRANCE', 'UNION_CAVE_1F', 'SLOWPOKE_WELL_B1F', 'ILEX_FOREST'), ()),
    (53, ('ROUTE_34', 'ROUTE_35', 'ROUTE_36', 'ROUTE_37', 'ROUTE_38', 'ROUTE_39', 'NATIONAL_PARK',
          'BURNED_TOWER_1F', 'RUINS_OF_ALPH_OUTSIDE'), ()),
    (54, ('ROUTE_42', 'ROUTE_43', 'ROUTE_44', 'MOUNT_MORTAR_1F_OUTSIDE'),
     ('ROUTE_30', 'ROUTE_31', 'ROUTE_32', 'ROUTE_34', 'ROUTE_35', 'ROUTE_40', 'ROUTE_41', 'ROUTE_42', 'ROUTE_43',
      'ROUTE_44', 'NEW_BARK_TOWN', 'CHERRYGROVE_CITY', 'VIOLET_CITY', 'CIANWOOD_CITY', 'OLIVINE_CITY',
      'ECRUTEAK_CITY', 'LAKE_OF_RAGE', 'MOUNT_MORTAR_1F_OUTSIDE')),
    (57, ('ICE_PATH_1F', 'ICE_PATH_B1F', 'ICE_PATH_B2F_MAHOGANY_SIDE', 'ICE_PATH_B2F_BLACKTHORN_SIDE',
          'ICE_PATH_B3F', 'DARK_CAVE_BLACKTHORN_ENTRANCE', 'ROUTE_45', 'ROUTE_27'),
     ('BLACKTHORN_CITY', 'DRAGONS_DEN_B1F', 'ROUTE_45', 'DARK_CAVE_BLACKTHORN_ENTRANCE', 'ROUTE_27')),
)
_KANTO = {'ROUTE_27'}


def _gen1_keys(names, kind):
    return [f'{kind}:{_GEN1[name]}' for name in names]


def _gen2_keys(maps, names, kind):
    return [f'{"kanto" if name in _KANTO else "johto"}_{kind}:{maps[name]}' for name in names]


def _build(gates, keys):
    built, reachable = [], []
    for hm, grass, water in gates:
        reachable += keys(grass, 'grass') + keys(water, 'water')
        built.append((hm, tuple(dict.fromkeys(reachable))))
    return tuple(built)


HM_GATES = {
    **dict.fromkeys(('red', 'blue', 'yellow'), _build(_GEN1_GATES, _gen1_keys)),
    **dict.fromkeys(('gold', 'silver'), _build(_GEN2_GATES, lambda names, kind: _gen2_keys(_GOLD, names, kind))),
    'crystal': _build(_GEN2_GATES, lambda names, kind: _gen2_keys(_CRYSTAL, names, kind)),
}
"""Per version: (HM number, encounter keys reachable before the game requires that HM).
A key the cartridge has no table for is skipped."""


def hm_gates(version):
    return HM_GATES.get(version, ())


def _slots(table):
    slots = table['slots']
    return [slot for time in slots.values() for slot in time] if isinstance(slots, dict) else slots


def missing_hm_learners(data, gates=None):
    """HMs in ``gates`` with no wild learner catchable before the game requires them."""
    gates = hm_gates(data.version) if gates is None else gates
    missing = []
    for hm, keys in gates:
        catchable = {slot[1] for key in keys if key in data.encounters for slot in _slots(data.encounters[key])}
        if not any(hm in data.species[species]['tmhm'] for species in catchable):
            missing.append(hm)
    return missing


def _generator(version, seed, options):
    material = f'{PREFIX}:{version}:{options.code()}:{seed}'.encode()
    return random.Random(int.from_bytes(hashlib.sha256(material).digest(), 'big'))


def _draw(data, rng, options):
    species = sorted(data.species)
    shuffled = species[:]
    rng.shuffle(shuffled)
    remap = dict(zip(species, shuffled))
    overrides = {}
    if options.wild:
        overrides['encounters'] = {
            key: {'slots': {time: [[level, remap[mon]] for level, mon in slots]
                            for time, slots in table['slots'].items()} if isinstance(table['slots'], dict)
                  else [[level, remap[mon]] for level, mon in table['slots']]}
            for key, table in data.encounters.items()}
    if options.starters:
        overrides['starters'] = [remap[species] for species in data.starters]
    if options.trainers:
        overrides['trainers'] = {key: {'party': [_trainer_mon(data, mon, remap[mon['species']])
                                                 for mon in trainer['party']]}
                                 for key, trainer in data.trainers.items()}
    return overrides


def _trainer_mon(data, mon, species):
    """``mon`` as ``species``. Gen II parties with explicit moves get that species' default moveset."""
    mon = dict(mon, species=species)
    if 'moves' in mon:
        mon['moves'] = default_moves(data.learnsets.get(species, []), mon['level'])
    return mon


def default_moves(learnset, level):
    """The four moves a wild or trainer Pokemon at ``level`` knows, as the cartridge fills them.

    Each learnset move up to ``level`` goes into the next free slot, or pushes out the oldest
    move once all four are full. A move already known is skipped. Empty slots are 0.
    """
    moves = []
    for learned, move in learnset:
        if learned <= level and move and move not in moves:
            moves = (moves + [move])[-4:]
    return moves + [0] * (4 - len(moves))


def randomize(rom_data, seed, options=None, gates=None):
    """The override map for ``seed``. ``rom_data`` is the :class:`romdata.GameData` to randomize.

    ``gates`` replaces :func:`hm_gates` for this version. Raises ``ValueError`` for a bad
    seed and ``RuntimeError`` if :data:`MAX_DRAWS` draws all leave an HM without a learner.
    """
    options = Options() if options is None else options
    _check_seed(seed)
    if not options.code():
        raise ValueError('Choose at least one thing to randomize')
    rng = _generator(rom_data.version, seed, options)
    for _ in range(MAX_DRAWS):
        overrides = _draw(rom_data, rng, options)
        if not options.wild or not missing_hm_learners(rom_data.with_overrides(overrides), gates):
            return overrides
    raise RuntimeError(f'No draw in {MAX_DRAWS} gave every required HM a catchable learner')


def _check_seed(seed):
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < MAX_SEED:
        raise ValueError(f'A seed is a whole number from 0 to {MAX_SEED - 1}')


def encode_share_code(version, seed, options=None) -> str:
    """``PSR1-<GAME>-<OPTS>-<seed>``, for example ``PSR1-CRYSTAL-WST-42``."""
    options = Options() if options is None else options
    if version not in GAMES:
        raise ValueError(f'No randomizer for {version!r}')
    _check_seed(seed)
    if not options.code():
        raise ValueError('Choose at least one thing to randomize')
    return f'{PREFIX}-{version.upper()}-{options.code()}-{seed}'


def decode_share_code(code):
    """The (version, seed, options) a share code names. Raises ``ValueError`` if it is malformed."""
    parts = code.strip().upper().split('-')
    if len(parts) != 4 or parts[0] != PREFIX:
        raise ValueError(f'Not a {PREFIX} share code: {code!r}')
    _, game, letters, seed = parts
    version = game.lower()
    order = ''.join(letter for _, letter in OPTION_CODES)
    if version not in GAMES or not letters or not seed.isdigit() \
            or ''.join(sorted(letters, key=order.find)) != letters or len(set(letters)) != len(letters) \
            or set(letters) - set(order):
        raise ValueError(f'Not a valid {PREFIX} share code: {code!r}')
    options = Options(**{name: letter in letters for name, letter in OPTION_CODES})
    seed = int(seed)
    _check_seed(seed)
    if encode_share_code(version, seed, options) != code.strip().upper():
        raise ValueError(f'Not a canonical {PREFIX} share code: {code!r}')
    return version, seed, options
