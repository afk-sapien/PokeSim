"""Game data read from the caller's own cartridge, with an override layer for randomizers.

Core ships no game tables. :func:`load` reads species base data, evolutions, level-up
learnsets, the TM and HM move list, wild encounter and fishing tables, trainer parties
and starters straight from a ROM, using only the per-version addresses in :mod:`.layouts`.
A modified or randomized ROM of a supported version reads the same way when ``version``
is given. :func:`load_cached` reads each ROM once.

:meth:`GameData.with_overrides` returns the effective data after an override map, without
touching the ROM. With no overrides the effective data is the ROM data, byte for byte in
:meth:`GameData.canonical`. :func:`effective_data` loads and applies overrides in one
call, and :func:`patch_rom` writes them into a copy of the ROM.

Species IDs are the values the game stores in memory: the Gen I internal index, or the
Gen II dex number. TM and HM numbers in ``tmhm`` are 1-based, with HMs (and Crystal's
tutor moves) numbered after the TMs, matching positions in ``tm_moves``.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from ..cartridges import UnsupportedCartridge, identify, read_header, resembles
from . import gen1, gen2
from .layouts import LAYOUTS, Layout, layout, rom_offset
from .patch import effective_data, patch_rom

__all__ = ['GameData', 'LAYOUTS', 'Layout', 'OVERRIDE_KEYS', 'UnsupportedCartridge', 'effective_data', 'load',
           'load_cached', 'layout', 'patch_rom', 'rom_offset']

FIELDS = ('species', 'evolutions', 'learnsets', 'tm_moves', 'encounters', 'fishing', 'fish_groups', 'trainers',
          'starters')
OPTIONAL = {'fishing': {}, 'fish_groups': {}}
RODS = ('old_rod', 'good_rod', 'super_rod')
# GetFishGroupIndex swaps these fish groups for their swarm groups on a swarm day.
SWARMS = {'qwilfish': (11, 6), 'remoraid': (12, 7)}
OVERRIDE_KEYS = ('species_map', 'species', 'evolutions', 'learnsets', 'tm_moves', 'encounters', 'trainers',
                 'starters')


class GameData:
    """One cartridge's game tables. Treat it as read-only. Overrides return a new copy."""

    def __init__(self, version, tables, overrides=None):
        self.layout = layout(version)
        self.version = version
        self.generation = self.layout.generation
        for name in FIELDS:
            setattr(self, name, tables[name] if name in tables or name not in OPTIONAL else deepcopy(OPTIONAL[name]))
        self.overrides = overrides or {}

    def fishing_slots(self, rod, map_id, *, time='day', swarm=None):
        """What ``rod`` can hook on ``map_id``, or None when nothing bites there.

        ``rod`` is 'old_rod', 'good_rod' or 'super_rod'. Returns ``{'bite': p, 'slots':
        [{'level', 'species', 'probability'}]}``. ``bite`` is the chance a cast hooks
        anything, and a slot's ``probability`` is its chance once something bites, so
        a cast meets a slot with ``bite * probability``. Gen I's Old and Good Rod hook the
        same Pokemon on every map. Gen II tables depend on ``time`` ('morn', 'day' or
        'nite') and, on a swarm day, ``swarm`` ('qwilfish' or 'remoraid').

        The tables are read from the ROM. Overrides do not change them yet.
        """
        if rod not in RODS:
            raise ValueError(f'Unknown rod {rod!r}. Use one of {", ".join(RODS)}')
        if self.generation == 1:
            table = self.fishing.get(rod if rod != 'super_rod' else f'super_rod:{map_id}')
            return None if table is None else {'bite': table['bite'], 'slots': deepcopy(table['slots'])}
        group = self.fish_groups.get(map_id)
        if group is None:
            return None
        if swarm is not None:
            if swarm not in SWARMS:
                raise ValueError(f'Unknown swarm {swarm!r}. Use one of {", ".join(SWARMS)}')
            normal, swarming = SWARMS[swarm]
            group = swarming if group == normal else group
        table = self.fishing.get(f'{rod}:{group}')
        if table is None:
            return None
        if time not in table['slots']:
            raise ValueError(f'Unknown time {time!r}. Use one of {", ".join(table["slots"])}')
        return {'bite': table['bite'], 'slots': deepcopy(table['slots'][time])}

    def as_dict(self):
        return {'version': self.version, 'generation': self.generation,
                **{name: deepcopy(getattr(self, name)) for name in FIELDS}}

    def canonical(self) -> bytes:
        """Stable JSON bytes of the tables, for comparing two readings exactly."""
        return json.dumps(self.as_dict(), sort_keys=True, separators=(',', ':')).encode()

    def starter_sites(self):
        """Every ROM offset that holds each starter's species, first site first."""
        return [list(sites) for sites in self.layout.starters]

    def with_overrides(self, overrides) -> GameData:
        """Return the effective data after ``overrides``. ``self`` is unchanged.

        Keys, all optional:

        - ``species_map``: {species: species}. Rewrites every placed Pokemon: starters,
          wild slots and trainer parties. Base data, evolutions and learnsets are not remapped.
        - ``species``: {species: {field: value}}. Replaces fields of a species record.
        - ``evolutions`` and ``learnsets``: {species: list}. Replaces the whole list.
        - ``tm_moves``: the full TM and HM move list, the same length as the ROM's.
        - ``encounters``: {table key: {field: value} or another table key}. A dict replaces
          fields such as ``slots``. A key swaps in that table's rate and slots, after
          ``species_map``. Both tables must be the same kind.
        - ``trainers``: {trainer key: {field: value}}, for example a new ``party``.
        - ``starters``: the full starter list, the same length as the ROM's.

        Explicit ``encounters``, ``trainers`` and ``starters`` are used as given, so
        ``species_map`` never rewrites them.
        """
        overrides = deepcopy(dict(overrides or {}))
        unknown = set(overrides) - set(OVERRIDE_KEYS)
        if unknown:
            raise ValueError(f'Unknown override keys: {sorted(unknown)}')
        tables = {name: deepcopy(getattr(self, name)) for name in FIELDS}
        species = tables['species']

        def known(value, where):
            if value not in species:
                raise ValueError(f'{where}: {value!r} is not a species of {self.version}')
            return value

        remap = {known(old, 'species_map'): known(new, 'species_map')
                 for old, new in overrides.get('species_map', {}).items()}
        for key, fields in overrides.get('species', {}).items():
            record = species[known(key, 'species')]
            extra = set(fields) - set(record)
            if extra:
                raise ValueError(f'Unknown species fields: {sorted(extra)}')
            record.update(fields)
        for name in ('evolutions', 'learnsets'):
            for key, value in overrides.get(name, {}).items():
                tables[name][known(key, name)] = value
        if 'tm_moves' in overrides:
            tables['tm_moves'] = _same_length(overrides['tm_moves'], tables['tm_moves'], 'tm_moves')

        if remap:
            tables['starters'] = [remap.get(value, value) for value in tables['starters']]
            for table in tables['encounters'].values():
                for slot in _slots(table):
                    slot[1] = remap.get(slot[1], slot[1])
            for trainer in tables['trainers'].values():
                for mon in trainer['party']:
                    mon['species'] = remap.get(mon['species'], mon['species'])

        remapped = deepcopy(tables['encounters'])
        for key, change in overrides.get('encounters', {}).items():
            table = _entry(tables['encounters'], key, 'encounters')
            if isinstance(change, str):
                source = _entry(remapped, change, 'encounters')
                if source['kind'] != table['kind']:
                    raise ValueError(f'Cannot swap {source["kind"]} table {change} into {key}')
                change = {name: deepcopy(value) for name, value in source.items() if name not in ('kind', 'map')}
            _merge(table, change, key)
            for slot in _slots(table):
                known(slot[1], key)
        for key, change in overrides.get('trainers', {}).items():
            trainer = _entry(tables['trainers'], key, 'trainers')
            _merge(trainer, change, key)
            for mon in trainer['party']:
                known(mon['species'], key)
        if 'starters' in overrides:
            tables['starters'] = [known(value, 'starters') for value in
                                  _same_length(overrides['starters'], tables['starters'], 'starters')]
        return GameData(self.version, tables, overrides)


def _same_length(value, current, name):
    value = list(value)
    if len(value) != len(current):
        raise ValueError(f'{name} needs {len(current)} entries, got {len(value)}')
    return value


def _entry(tables, key, name):
    if key not in tables:
        raise ValueError(f'Unknown {name} key {key!r}')
    return tables[key]


def _merge(record, change, key):
    extra = set(change) - set(record) - {'class', 'index', 'kind', 'map'}
    fixed = set(change) & {'class', 'index', 'kind', 'map'}
    if extra or fixed:
        raise ValueError(f'{key}: cannot set {sorted(extra | fixed)}')
    record.update(change)


def _slots(table):
    slots = table['slots']
    return [slot for time in slots.values() for slot in time] if isinstance(slots, dict) else slots


def load(rom, version=None) -> GameData:
    """Read game data from ROM bytes.

    Without ``version`` the ROM must be a verified clean cartridge. Pass ``version`` to
    read a modified ROM of that version with the same layout. Its header title must
    still name a Pokémon game of that generation. Otherwise, as for an unknown ROM
    without ``version``, :class:`UnsupportedCartridge` (a ValueError) is raised before
    anything is read.
    """
    rom = bytes(rom)
    cartridge = identify(rom)
    if version is None:
        if cartridge is None:
            raise UnsupportedCartridge(f'Unknown ROM {_title(rom)!r}. Pass version= to read a modified cartridge.',
                                       _title(rom))
        version = cartridge.version
    elif cartridge is not None and cartridge.version != version:
        raise ValueError(f'This ROM is {cartridge.version}, not {version}')
    found = layout(version)
    similar = resembles(rom)
    if cartridge is None and (similar is None or similar.generation != found.generation):
        raise UnsupportedCartridge(f'{_title(rom)!r} is not a Gen {found.generation} Pokémon cartridge, '
                                   f'so it cannot be read as {version}', _title(rom))
    reader = gen1 if found.generation == 1 else gen2
    return GameData(version, reader.read(rom, found))


def _title(rom):
    try:
        return read_header(rom).title
    except ValueError:
        return None


_LOADED = {}


def load_cached(rom, version=None) -> GameData:
    """:func:`load`, read once per ROM content and ``version``.

    Repeat calls hash the ROM bytes (about a millisecond) and return the same
    :class:`GameData`, so treat it as read-only. A handful of ROMs are kept.
    """
    rom = bytes(rom)
    key = (hashlib.sha256(rom).digest(), version)
    data = _LOADED.pop(key, None) or load(rom, version)
    _LOADED[key] = data
    while len(_LOADED) > 8:
        del _LOADED[next(iter(_LOADED))]
    return data
