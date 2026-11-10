"""Record each test module's run time from pytest JUnit reports into tests/durations.json.

The root conftest.py splits CI shards by these times. A module found in the reports gets its new time.
Every other module keeps its old one, so a browser-only report leaves the rest of the suite alone, and a
module whose file is gone is dropped. Times are the sum of each test's setup, call and teardown.

Usage: python tools/record_durations.py report.xml [report.xml ...]
"""
import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tests' / 'durations.json'
ABOUT = 'Seconds per test module from pytest JUnit reports. Rewrite with python tools/record_durations.py.'


def module_of(classname, root=ROOT):
    """The test file a JUnit classname such as tests.browser.test_flows.TestPage names, or None."""
    parts = classname.split('.')
    for end in range(len(parts), 0, -1):
        path = '/'.join(parts[:end]) + '.py'
        if (root / path).is_file():
            return path
    return None


def measure(reports, root=ROOT):
    modules = {}
    for report in reports:
        for case in ET.parse(report).getroot().iter('testcase'):
            if case.find('skipped') is not None:
                continue
            module = module_of(case.get('classname') or '', root)
            if module is None:
                continue
            entry = modules.setdefault(module, {'seconds': 0.0, 'tests': 0})
            entry['seconds'] += float(case.get('time') or 0)
            entry['tests'] += 1
    return modules


def merge(old, new, root=ROOT):
    merged = {name: entry for name, entry in old.items() if (root / name).is_file()}
    merged.update(new)
    return {name: {'seconds': round(entry['seconds'], 1), 'tests': entry['tests']} for name, entry in sorted(merged.items())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('reports', nargs='+', type=Path)
    arguments = parser.parse_args(argv)
    try:
        old = json.loads(OUT.read_text(encoding='utf-8')).get('modules', {})
    except (OSError, ValueError):
        old = {}
    new = measure(arguments.reports)
    if not new:
        sys.exit('No test times found in the reports')
    OUT.write_text(json.dumps({'about': ABOUT, 'modules': merge(old, new)}, indent=1) + '\n', encoding='utf-8')
    print(f'Recorded {len(new)} modules into {OUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
