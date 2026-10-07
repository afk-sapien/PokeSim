"""Simulate elapsed cartridge clock time in an isolated format 15 checkpoint."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct


def advance(raw, hours):
    if raw[0] != 15 or len(raw) < 100000:
        raise ValueError('Clock simulation requires a format 15 checkpoint')
    if not math.isfinite(hours) or not 0 < hours <= 24 * 7:
        raise ValueError('Advance the clock by at most seven days per simulation step')
    # The state ends with the RTC epoch, halt and carry bytes, two joypad bytes, then 36 serial-port bytes.
    offset = len(raw) - 48
    epoch = struct.unpack_from('d', raw, offset)[0]
    if not math.isfinite(epoch) or not 946684800 <= epoch <= 4102444800:
        raise ValueError('The checkpoint does not have the expected RTC timestamp')
    result = bytearray(raw)
    struct.pack_into('d', result, offset, epoch - hours * 3600)
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--hours', type=float, required=True)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    result = advance(raw, args.hours)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result)
    metadata = args.source.with_suffix('.policy.json')
    if metadata.exists():
        shutil.copyfile(metadata, args.output.with_suffix('.policy.json'))
    args.output.with_suffix('.clock.json').write_text(json.dumps({
        'source': str(args.source.resolve()), 'hours_elapsed': args.hours,
        'source_sha256': hashlib.sha256(raw).hexdigest(),
        'result_sha256': hashlib.sha256(result).hexdigest(),
        'changed': 'Only the emulator RTC epoch. No cartridge RAM or Pokémon data was changed.'}, indent=2))


if __name__ == '__main__':
    main()
