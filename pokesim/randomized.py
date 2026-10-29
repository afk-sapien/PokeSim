"""Seeded randomizer runs: the patched cartridge and the game data the planner sees.

An adventure stores one share code, such as ``PSR1-RED-WS-12345``, chosen when it is created.
Its worker patches the clean ROM in memory and boots from those bytes. The patched copy is never
written to disk, so the clean file keeps the identity that saves, checkpoints, trackers and trades
rely on. Only the tables the planner reads (wild slots, starters and leader parties) follow the
seed. Fishing, gifts, trades and static encounters are not randomized.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

ENV = 'RANDOMIZER'


def validate(code, version=None):
    """The canonical share code, or '' for off. ``version`` is the adventure's cartridge."""
    if code in ('', None):
        return ''
    if not isinstance(code, str):
        raise ValueError('The randomizer share code must be text')
    from pokecore.randomizer import decode_share_code, encode_share_code
    try:
        game, seed, options = decode_share_code(code)
    except ValueError as error:
        raise ValueError('That randomizer share code is not valid') from error
    if version is not None and game != version:
        raise ValueError(f'That share code is for Pokémon {game.title()}, not {version.title()}')
    return encode_share_code(game, seed, options)


@dataclass(frozen=True)
class Run:
    code: str
    version: str
    options: object
    rom: bytes
    clean: object
    effective: object


@lru_cache(maxsize=4)
def _run(code, rom_path, size, mtime):
    from pokecore import romdata
    from pokecore.randomizer import decode_share_code, randomize
    version, seed, options = decode_share_code(code)
    clean_rom = Path(rom_path).read_bytes()
    clean = romdata.load(clean_rom, version)
    overrides = randomize(clean, seed, options)
    return Run(code, version, options, romdata.patch_rom(clean_rom, overrides, version), clean,
               clean.with_overrides(overrides))


def current(rom_path=None):
    """This process's randomized run, or None. The worker's settings install the share code."""
    code = os.environ.get(ENV, '')
    if not code:
        return None
    if rom_path is None:
        from . import config
        rom_path = config.ROM_PATH
    stat = Path(rom_path).stat()
    return _run(code, str(rom_path), stat.st_size, stat.st_mtime_ns)


def rom_stream(rom_path):
    """What an emulator boots from: the patched bytes in memory, or the clean path."""
    run = current(rom_path)
    if run is None:
        return str(rom_path)
    import io
    return io.BytesIO(run.rom)


def status():
    """Share code and options for the run page, or None when this adventure is not randomized."""
    run = current()
    if run is None:
        return None
    return {'code': run.code, 'wild': run.options.wild, 'starters': run.options.starters,
            'trainers': run.options.trainers}


# Gen I ----------------------------------------------------------------------------------------

def _gen1_tables(run):
    grass, surf = {}, {}
    for table in run.effective.encounters.values():
        target = grass if table['kind'] == 'grass' else surf
        target.setdefault(table['map'], set()).update((species, level) for level, species in table['slots'])
    return grass, surf


def gen1_game_data(name, data, variant):
    """Rewrite a loaded Gen I bundle file for this process's randomized run."""
    run = current() if name in ('strategy.json', 'collection.json') else None
    if run is None or run.effective.generation != 1 or (variant == 'yellow') != (run.version == 'yellow'):
        return data
    if not run.options.wild:
        return data
    grass, surf = _gen1_tables(run)
    if name == 'strategy.json':
        for key, world in data['world'].items():
            if 'encounters' in world:
                world['encounters'] = sorted([species, level] for species, level in grass.get(int(key), ()))
        return data
    safari = {int(key) for key, world in _strategy_world().items() if world['symbol'].startswith('SAFARI_ZONE_')}
    sources = data['versions'].get(run.version)
    if sources is None:
        return data
    rebuilt = {}
    for sid, rows in sources.items():
        kept = [row for row in rows if row['method'] not in ('grass', 'surf', 'safari')]
        if kept:
            rebuilt[sid] = kept
    for tables, method in ((grass, 'grass'), (surf, 'surf')):
        for map_id, slots in sorted(tables.items()):
            for species, level in sorted(slots, key=lambda slot: (slot[1], slot[0])):
                source = {'map': map_id, 'method': 'safari' if map_id in safari else method, 'level': level}
                rows = rebuilt.setdefault(str(species), [])
                if source not in rows:
                    rows.append(source)
    data['versions'][run.version] = rebuilt
    return data


def _strategy_world():
    from .game_data import load
    return load('strategy.json')['world']


# pret trainer classes for each leader bit in policies.team.OPPONENTS. Red, Blue and Yellow agree.
LEADER_CLASSES = {1: 34, 2: 35, 4: 36, 8: 37, 16: 38, 32: 40, 64: 39, 128: 29,
                  256: 44, 257: 33, 258: 46, 259: 47, 260: 43}


def gen1_opponents(opponents, species):
    """Leader aces after a trainer shuffle: the species now in the ace's party slot."""
    run = current()
    if run is None or run.effective.generation != 1 or not run.options.trainers:
        return opponents
    names = {sid: data.get('name') for sid, data in species.items()}
    ids = {name: sid for sid, name in names.items()}
    result = dict(opponents)
    for bit, (name, ace, level) in opponents.items():
        cls = LEADER_CLASSES.get(bit)
        for key, trainer in run.clean.trainers.items():
            if trainer['class'] != cls:
                continue
            slot = next((i for i, mon in enumerate(trainer['party'])
                         if mon['level'] == level and mon['species'] == ids.get(ace)), None)
            if slot is not None:
                result[bit] = (name, names.get(run.effective.trainers[key]['party'][slot]['species'], ace), level)
                break
    return result


# Gen II ---------------------------------------------------------------------------------------

# Gen II grass and surf rows come from the cartridge's own tables in planning/cost.py, shuffled or not.
