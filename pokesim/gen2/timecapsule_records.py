"""Preserve an individual's League history across generation-specific species IDs."""
import hashlib
import json

from ..trade.preferences import identity
from . import league
from .ram import decode_mon
from .timecapsule_conversion import convert


def bundle(directory):
    from pathlib import Path
    from .data import GameData
    for game in ('crystal', 'gold', 'silver'):
        if (Path(directory) / 'gen2' / game).is_dir():
            return GameData.load(directory, game)
    raise ValueError('Time Capsule species data is unavailable')


def remap(record, signature, name, version):
    if record is None:
        return None
    individual = hashlib.sha256(json.dumps([signature, name]).encode()).hexdigest()[:24]
    return {**record, 'version': version, 'signature': signature, 'individual': individual,
            'names': sorted(set(record.get('names', [])) | {name}), 'incomplete': record.get('incomplete', False)}


def to_gen2(record, encoded, data):
    from .. import league_partners as old
    from ..ram import individual_data, decode_text
    row = {key: bytes.fromhex(value) for key, value in encoded.items()}
    mon = {**individual_data(row['struct']), 'species': row['struct'][0], 'nick': decode_text(row['nickname'])}
    old.validate(record, identity(mon), mon)
    converted = convert(row, 2, data)
    target = decode_mon(converted['struct'], converted['nickname'], data).to_dict()
    signature, name = league.signature(data, target)
    return remap(record, signature, name, 'gen2-1')


def to_gen1(record, encoded, data):
    from .. import league_partners as old
    from ..ram import individual_data, decode_text
    row = {key: bytes.fromhex(value) for key, value in encoded.items()}
    mon = decode_mon(row['struct'], row['nickname'], data).to_dict()
    league.validate(record, data, mon)
    converted = convert(row, 1, data)
    target = {**individual_data(converted['struct']), 'species': converted['struct'][0],
              'nick': decode_text(converted['nickname'])}
    return remap(record, old.signature(target), old.nickname(target), 2)
