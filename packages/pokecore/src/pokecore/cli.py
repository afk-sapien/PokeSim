"""The ``pokecore`` command."""
from __future__ import annotations

import argparse
import json
import sys

from .save_summary import SaveError, summarize_save


def _lines(summary):
    badges = f'{summary.badge_count} ({", ".join(summary.badges)})' if summary.badges else '0'
    hours, minutes, seconds = summary.play_time
    lines = [f'Stage: {summary.stage}',
             f'Game: {summary.version or "unknown"} (Generation {summary.generation})',
             f'Player: {summary.player_name}', f'Rival: {summary.rival_name}', f'Badges: {badges}']
    if summary.generation == 2:
        lines += [f'Johto badges: {len(summary.johto_badges)}', f'Kanto badges: {len(summary.kanto_badges)}',
                  f'Kanto entered: {"yes" if summary.kanto_entered else "no"}',
                  f'Red beaten: {"yes" if summary.red_beaten else "no"}']
    lines += [f'Pokedex: {summary.dex_owned} owned, {summary.dex_seen} seen', f'Hall of Fame: {summary.hall_of_fame}',
              f'Money: {summary.money}', f'Play time: {hours}:{minutes:02d}:{seconds:02d}',
              f'Boxes: {summary.box_total}', f'Map: {summary.map_id}', f'Party: {len(summary.party)}']
    lines += [f'  {mon.name or f"species {mon.species}"} L{mon.level}' for mon in summary.party]
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(prog='pokecore')
    commands = parser.add_subparsers(dest='command', required=True)
    summary = commands.add_parser('summary', help='print what a cartridge save holds')
    summary.add_argument('save', help='path to a 32 KiB .sav file')
    summary.add_argument('--rom', help='cartridge ROM, for the version and species names')
    summary.add_argument('--json', action='store_true', help='print JSON')
    args = parser.parse_args(argv)
    try:
        result = summarize_save(args.save, rom=args.rom)
    except (SaveError, OSError) as error:
        print(f'pokecore: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result.to_dict(), indent=2) if args.json else '\n'.join(_lines(result)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
