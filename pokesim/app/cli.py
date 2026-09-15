"""Administrative commands for the managed application."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
import uuid

import httpx


def _options(parser):
    parser.add_argument('--data-dir', type=Path, default=argparse.SUPPRESS,
                        help='Application data directory, defaults to POKESIM_APP_DIR or pokesim-app')
    return parser


def parser():
    result = _options(argparse.ArgumentParser(description='Manage a PokeSim adventure library'))
    commands = result.add_subparsers(dest='command', required=True)
    adventures = _options(commands.add_parser('adventures', help='Manage adventures in a running application'))
    actions = adventures.add_subparsers(dest='action', required=True)
    _options(actions.add_parser('list', help='List adventures and their current state'))
    create = _options(actions.add_parser('create', help='Create an independent adventure'))
    create.add_argument('--name', required=True)
    source = create.add_mutually_exclusive_group(required=True)
    source.add_argument('--rom', type=Path, help='ROM to add to the application')
    source.add_argument('--rom-id', help='Previously installed ROM identifier')
    create.add_argument('--starter', choices=['random', 'bulbasaur', 'charmander', 'squirtle'], default='random')
    create.add_argument('--start', action='store_true', help='Start the adventure after creating it')
    for action in ('start', 'stop'):
        command = _options(actions.add_parser(action, help=f'{action.capitalize()} one adventure'))
        command.add_argument('id', help='Adventure ID from adventures list')
    importing = _options(commands.add_parser('import', help='Copy a stopped legacy adventure into a stopped application'))
    importing.add_argument('source', type=Path, help='Legacy data folder or desktop adventure folder')
    importing.add_argument('--stopped', action='store_true', required=True,
                           help='Confirm the old service and its coordinator are stopped')
    importing.add_argument('--rom', type=Path, help='Original ROM if not found in the source folder')
    importing.add_argument('--name', help='Display name for the imported adventure')
    pair = _options(commands.add_parser('import-pair', help='Import a resolved legacy trading pair with coordinator evidence'))
    pair.add_argument('--red', type=Path, required=True, help='Stopped legacy Red data directory')
    pair.add_argument('--blue', type=Path, required=True, help='Stopped legacy Blue data directory')
    pair.add_argument('--red-rom', type=Path, required=True)
    pair.add_argument('--blue-rom', type=Path, required=True)
    pair.add_argument('--coordinator-root', type=Path, required=True, help='Retained legacy coordinator data directory')
    pair.add_argument('--stopped', action='store_true', required=True,
                      help='Confirm both legacy adventures and their coordinator are stopped')
    pair.add_argument('--request-id', help='Optional stable import operation ID for retrying an interrupted command')
    _options(commands.add_parser('backup', help='Request a consistent backup from the running application'))
    restoring = _options(commands.add_parser('restore', help='Restore a backup into an empty data directory'))
    restoring.add_argument('archive', type=Path)
    return result


class RunningApplication:
    def __init__(self, root):
        root = Path(root)
        try:
            identity = json.loads((root / 'manager.json').read_text())
            token = (root / 'owner.token').read_text().strip()
        except (OSError, ValueError) as error:
            raise ValueError('Start the PokeSim application for this data directory before using this command') from error
        address = urlsplit(identity.get('url', ''))
        if address.scheme not in {'http', 'https'} or not address.netloc or address.username or address.password:
            raise ValueError('The application address in manager.json is invalid')
        self.expected_application = identity['application_id']
        self.client = httpx.Client(base_url=identity['url'].rstrip('/'), trust_env=False,
                                   headers={'Authorization': 'Bearer ' + token}, timeout=300)
        try:
            health = self.request('GET', '/health/live')
            if health.get('application_id') != self.expected_application:
                raise ValueError('The running application does not match this data directory')
        except BaseException:
            self.client.close()
            raise

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        try:
            data = response.json()
        except ValueError as error:
            raise ValueError('The application returned an invalid response') from error
        if not response.is_success:
            detail = data.get('detail', f'Application request failed ({response.status_code})')
            raise ValueError(detail if isinstance(detail, str) else json.dumps(detail))
        return data

    def close(self):
        self.client.close()


def run(args):
    root = getattr(args, 'data_dir', Path(os.environ.get('POKESIM_APP_DIR', 'pokesim-app'))).expanduser().resolve()
    if args.command == 'restore':
        from .backup import restore_backup
        return {'restored_to': str(restore_backup(args.archive, root))}
    if args.command in {'import', 'import-pair'}:
        from .manager import Manager
        from .migration import import_directory
        try:
            manager = Manager(root)
        except BlockingIOError as error:
            raise ValueError('Stop the destination PokeSim application before importing a directory') from error
        try:
            if args.command == 'import-pair':
                from .legacy_import import import_pair
                return {'adventures': import_pair(manager, sources={'red': args.red, 'blue': args.blue},
                    roms={'red': args.red_rom, 'blue': args.blue_rom}, coordinator_root=args.coordinator_root,
                    stopped=args.stopped, request_id=args.request_id)}
            return import_directory(manager, args.source, rom=args.rom, name=args.name, stopped=args.stopped)
        finally:
            manager.close()
    app = RunningApplication(root)
    try:
        if args.command == 'backup':
            return app.request('POST', '/api/v1/backups', json={})
        if args.action == 'list':
            return app.request('GET', '/api/v1/adventures')
        if args.action == 'create':
            rom_id = args.rom_id
            if args.rom:
                from ..desktop_setup import MAX_ROM
                if args.rom.stat().st_size > MAX_ROM:
                    raise ValueError('ROM files may be no larger than 1 MB')
                rom_id = app.request('POST', '/api/v1/assets/rom', content=args.rom.read_bytes(),
                                     headers={'Content-Type': 'application/octet-stream'})['id']
            adventure = app.request('POST', '/api/v1/adventures', json={
                'name': args.name, 'rom_id': rom_id, 'starter': args.starter, 'request_id': uuid.uuid4().hex})
            if args.start:
                return app.request('POST', f'/api/v1/adventures/{adventure["id"]}/start', json={})
            return adventure
        from .registry import validate_id
        aid = validate_id(args.id)
        return app.request('POST', f'/api/v1/adventures/{aid}/{args.action}', json={})
    finally:
        app.close()


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = run(args)
    except (ValueError, OSError, httpx.HTTPError) as error:
        print(f'PokeSim: {error}', file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
