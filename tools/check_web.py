"""Check every browser script and run all Node browser tests from any directory."""
from pathlib import Path
import shutil
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    if not node:
        raise SystemExit('Node.js is required for browser checks. CI uses Node.js 22.')
    scripts = sorted((root / 'pokesim').glob('*/static/*.js'))
    tests = sorted((root / 'tests').glob('*.test.cjs'))
    if not scripts or not tests:
        raise SystemExit('Browser scripts or tests are missing from this checkout.')
    for script in scripts:
        subprocess.run([node, '--check', str(script)], cwd=root, check=True)
    subprocess.run([node, '--test', *map(str, tests)], cwd=root, check=True)
    print(f'Checked {len(scripts)} browser scripts and {len(tests)} test files.')


if __name__ == '__main__':
    main()
