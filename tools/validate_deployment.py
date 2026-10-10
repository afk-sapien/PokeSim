"""Exercise an upgrade from an older image and a backup-based version rollback."""
import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--old-image', default='pokesim:0.1.0')
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    report = {'image': args.image, 'old_image': args.old_image, 'checks': {}}
    container = 'pokesim-upgrade-validation'

    def healthy(fetch):
        for attempt in range(60):
            try:
                result = fetch()
                if result['health']['ok']:
                    return result
            except Exception:
                pass
            time.sleep(1)
        raise AssertionError('Service did not become healthy')

    def direct_state():
        with urlopen('http://127.0.0.1:18942/api/state', timeout=5) as response:
            return json.load(response)

    def ownership(path):
        run('docker', 'run', '--rm', '--user', '0', '-v', f'{path}:/target', '--entrypoint', 'chown', args.image, '-R', '10001:10001', '/target')

    def copy_backup(source, target):
        target.mkdir()
        script = (
            "import os, shutil\n"
            "from pathlib import Path\n"
            "shutil.copytree('/source', '/target', dirs_exist_ok=True)\n"
            "for path in [Path('/target'), *Path('/target').rglob('*')]:\n"
            f"    os.chown(path, {os.getuid()}, {os.getgid()})\n"
        )
        run('docker', 'run', '--rm', '--user', '0', '-v', f'{source}:/source:ro',
            '-v', f'{target}:/target', args.image, 'python', '-c', script)

    def start_direct(image, path):
        run('docker', 'run', '-d', '--name', container, '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:size=64m,mode=1777',
            '-p', '127.0.0.1:18942:8000', '-v', f'{path}:/data', '-v', f'{args.rom.resolve()}:/roms/pokered.gb:ro',
            '-e', 'SPEED=1', '-e', 'AUTOSAVE_SECONDS=10', image)
        return healthy(direct_state)

    try:
        upgrade = root / 'upgrade'
        upgrade.mkdir()
        ownership(upgrade)
        first = start_direct(args.old_image, upgrade)
        assert first['version'] == '0.1.0'
        time.sleep(20)
        prior = direct_state()['frame']
        run('docker', 'stop', '--time', '15', container)
        run('docker', 'rm', container)
        saved = max((upgrade / 'states').glob('auto-v1-*.json'), key=lambda p: p.stat().st_mtime)
        backup = root / 'pre-upgrade-backup'
        copy_backup(upgrade, backup)
        original_checkpoint = json.loads((backup / 'states' / saved.name).read_text())
        run('docker', 'run', '--rm', '--network', 'none', '--read-only', '-v', f'{upgrade}:/data',
            '-v', f'{args.source.resolve()}:/source:ro', args.image, 'python', '-m', 'pokesim.prepare_data', '/source')
        upgraded = start_direct(args.image, upgrade)
        assert upgraded['version'] != first['version']
        assert upgraded['frame'] >= prior
        time.sleep(15)
        assert direct_state()['frame'] > upgraded['frame']
        run('docker', 'stop', '--time', '15', container)
        run('docker', 'rm', container)
        rollback = root / 'rollback'
        shutil.copytree(backup, rollback)
        ownership(rollback)
        rolled_back = start_direct(args.old_image, rollback)
        assert rolled_back['version'] == '0.1.0'
        assert rolled_back['frame'] >= prior
        report['checks']['upgrade_and_backup_rollback'] = {
            'from': first['version'], 'to': upgraded['version'], 'restored': rolled_back['version'],
            'before_frame': prior, 'upgraded_frame': upgraded['frame'], 'rollback_frame': rolled_back['frame'],
            'checkpoint_sha256': original_checkpoint['sha256'],
        }
        report['passed'] = True
    finally:
        for command in (['docker', 'stop', '--time', '15', container], ['docker', 'rm', container]):
            try:
                run(*command)
            except subprocess.CalledProcessError:
                pass
        (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
